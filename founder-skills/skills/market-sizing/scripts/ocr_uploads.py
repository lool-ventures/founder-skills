#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Write a machine-read text sidecar for every page of every image-only upload.

WHY. On the live run that motivated the adversarial step, all seven of the founder's PDFs had no
text layer. The red team's read of the page that mattered was a second vision read by the same
model that had already misread it -- and a citation to a scanned page could not be checked by
anything. With a sidecar per page, `red_team.py` can verify a quoted sentence against the page, and
the dispatch prompt can point the red team at text rather than at pixels.

Binary-only (`pdftoppm` + `tesseract`, the cap-table pattern): NO Python OCR dependency. When
either binary is absent this exits 0 with `ocr_available: false` and writes nothing -- the red team
then reads by vision and every document citation stays `quote_verified: null`, which is the current
behaviour, disclosed. A missing OCR binary must never block a run.

COMPLETION IS A FILE, NOT A RETURN CODE. Measured on a live run: eight documents, 35 pages, about
2.5 minutes of tesseract -- past the shell tool's 120 s limit. The tool call returned with only the
mirror listing, the OCR kept running orphaned, and the model generated the dispatch prompt twice
before the last two documents' sidecars existed. Nothing said so: `dispatch_prompt.py` listed what
was on disk, and the red team reported those two as "no machine-read copy provided". So this
script writes `O/receipt.json` -- per document as it goes (`complete: false`) and once at the end
(`complete: true`) -- and `dispatch_prompt.py` refuses to generate a prompt for an image-only PDF
the receipt does not cover. A re-run RESUMES: documents the receipt already covers are skipped, so
recovering from a timeout costs only the remaining ones. Pages OCR in parallel.

Usage:
    ocr_uploads.py --uploads-dir U --out O [--dpi 200] [--pretty]

Writes `O/<filename>.p<N>.txt` for each page of each image-only PDF (per pdf_probe.py) that OCR'd
to at least one word, and `O/receipt.json`. Prints the receipt.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from typing import Any

RECEIPT_FILENAME = "receipt.json"

DOCUMENT_SUFFIXES = (".pdf", ".md", ".txt", ".docx", ".pptx", ".xlsx", ".csv")


def list_documents(uploads_dir: str | None) -> list[str]:
    """Regular files with a document suffix, sorted; dotfiles and AppleDouble `._*` excluded.

    Copy of dispatch_prompt.list_documents (skill scripts cannot import each other).
    """
    if not uploads_dir or not os.path.isdir(uploads_dir):
        return []
    out: list[str] = []
    for name in sorted(os.listdir(uploads_dir)):
        if name.startswith(".") or not name.lower().endswith(DOCUMENT_SUFFIXES):
            continue
        if os.path.isfile(os.path.join(uploads_dir, name)):
            out.append(name)
    return out


def _probe(path: str) -> dict[str, Any]:
    probe = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pdf_probe.py")
    try:
        r = subprocess.run([sys.executable, probe, path], capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            return {"ok": False}
        parsed = json.loads(r.stdout)
        return parsed if isinstance(parsed, dict) else {"ok": False}
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return {"ok": False}


def ocr_pdf_pages(pdf_path: str, dpi: int) -> list[str]:
    """One string per page: pdftoppm renders, tesseract reads. Raises on a tool failure."""
    with tempfile.TemporaryDirectory() as td:
        prefix = os.path.join(td, "page")
        subprocess.run(["pdftoppm", "-png", "-r", str(dpi), pdf_path, prefix], check=True, capture_output=True)
        pngs = sorted(f for f in os.listdir(td) if f.endswith(".png"))

        def read(png: str) -> str:
            return subprocess.run(
                ["tesseract", os.path.join(td, png), "stdout"], capture_output=True, text=True, check=True
            ).stdout

        with ThreadPoolExecutor(max_workers=max(1, min(4, os.cpu_count() or 1))) as pool:
            return list(pool.map(read, pngs))


def _load_receipt(out_dir: str) -> dict[str, Any]:
    try:
        with open(os.path.join(out_dir, RECEIPT_FILENAME), encoding="utf-8") as fh:
            r = json.load(fh)
        return r if isinstance(r, dict) and isinstance(r.get("documents"), dict) else {}
    except (OSError, ValueError):
        return {}


def _write_receipt(out_dir: str, receipt: dict[str, Any]) -> None:
    os.makedirs(out_dir, exist_ok=True)
    tmp = os.path.join(out_dir, RECEIPT_FILENAME + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(receipt, fh, indent=2)
    os.replace(tmp, os.path.join(out_dir, RECEIPT_FILENAME))


def run(uploads_dir: str, out_dir: str, dpi: int) -> dict[str, Any]:
    docs = [d for d in list_documents(uploads_dir) if d.lower().endswith(".pdf")]
    available = shutil.which("pdftoppm") is not None and shutil.which("tesseract") is not None
    if not available:
        unavailable: dict[str, Any] = {
            "ok": True,
            "ocr_available": False,
            "pages_written": 0,
            "skipped": docs,
            "documents": {},
        }
        _write_receipt(out_dir, {**unavailable, "complete": True})
        return unavailable
    prior = _load_receipt(out_dir)
    done: dict[str, Any] = dict(prior.get("documents") or {}) if prior.get("ocr_available") else {}
    written = 0
    skipped: list[str] = []
    receipt: dict[str, Any] = {
        "ok": True,
        "ocr_available": True,
        "pages_written": 0,
        "skipped": skipped,
        "documents": done,
        "complete": False,
    }
    for name in docs:
        if name in done:
            print(f"ocr: {name}: already read ({done[name].get('written')} pages), skipped", file=sys.stderr)
            continue
        full = os.path.join(uploads_dir, name)
        p = _probe(full)
        if not p.get("ok") or not p.get("image_only"):
            skipped.append(name)
            continue
        try:
            pages = ocr_pdf_pages(full, dpi)
        except (OSError, subprocess.CalledProcessError):
            skipped.append(name)
            continue
        os.makedirs(out_dir, exist_ok=True)
        wrote = 0
        for i, text in enumerate(pages, start=1):
            if not text.strip():
                continue
            with open(os.path.join(out_dir, f"{name}.p{i}.txt"), "w", encoding="utf-8") as fh:
                fh.write(text)
            wrote += 1
        written += wrote
        done[name] = {"pages": len(pages), "written": wrote}
        receipt["pages_written"] = written
        _write_receipt(out_dir, receipt)  # progress survives a killed process; a re-run resumes here
        print(f"ocr: {name}: {wrote}/{len(pages)} pages", file=sys.stderr)
    receipt["pages_written"] = written
    receipt["complete"] = True
    _write_receipt(out_dir, receipt)
    return receipt


def main() -> int:
    p = argparse.ArgumentParser(description="OCR text sidecars for image-only uploads (binary-only)")
    p.add_argument("--uploads-dir", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--dpi", type=int, default=200)
    p.add_argument("--pretty", action="store_true")
    a = p.parse_args()
    receipt = run(a.uploads_dir, a.out, a.dpi)
    print(json.dumps(receipt, indent=2 if a.pretty else None))
    return 0


if __name__ == "__main__":
    sys.exit(main())
