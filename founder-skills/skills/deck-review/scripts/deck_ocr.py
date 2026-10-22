#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Step 3.95's machine read: render and OCR the image slides whose figures the numbers section uses.

    deck_ocr.py --deck PDF --ledger L --reconciliation R --deck-text D --run-id ID -o "$HANDOFF_DIR/ocr"
                [--max-pages 40] [--budget-seconds 30] [--dpi 200]

`-o` is a folder: it gets `receipt.json` and one `p<N>.txt` per page read. Run it again until it prints
`"complete": true`; each call resumes where the last stopped, starting a new page only while the call is
inside its time budget (always at least one), so no call outlives the shell tool. A page that fails twice is
`failed`; pages past `--max-pages` are `not_read`. OCR text never becomes deck text: nothing but
`ocr_check.py` reads this folder.

Every tooling problem exits 0 with the reason in the receipt (`unavailable`: no pdftoppm or tesseract, or an
unreadable PDF), so a missing binary never blocks a review. The receipt says `not_applicable` when the file is
not the deck the deck text was read from (`deck_mismatch`, checked first), is not a PDF, has another page count
than the deck text (`page_count_mismatch`), or has no slide read from how it looks (`no_inventory`); and
`no_figures` when no figure the section uses sits on such a slide.

Exit 1, nothing written: a missing `--deck`; `-o` an existing file (`OUTPUT_NOT_DIR`); an unreadable ledger
(`LEDGER_UNREADABLE`) or reconciliation; another run's deck text; a folder that is not this run's.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from typing import Any

import _deck_text_file
import _ocr_scope
import _pdf_pages

_START = time.monotonic()
RECEIPT = "receipt.json"
PDFTOPPM_TIMEOUT = 15
TESSERACT_TIMEOUT = 30
MAX_ATTEMPTS = 2
_SLIDE_HEADING = re.compile(r"^## Slide \d+\s*$", re.M)


def _reject(code: str, message: str) -> int:
    sys.stdout.write(json.dumps({"status": "rejected", "code": code, "message": message}) + "\n")
    print(f"Error ({code}): {message}; nothing was written", file=sys.stderr)
    return 1


def _write_receipt(out_dir: str, receipt: dict[str, Any]) -> None:
    os.makedirs(out_dir, exist_ok=True)
    tmp = os.path.join(out_dir, RECEIPT + f".tmp.{os.getpid()}")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(receipt, fh, indent=2)
    os.replace(tmp, os.path.join(out_dir, RECEIPT))


def _load_receipt(out_dir: str) -> dict[str, Any]:
    try:
        with open(os.path.join(out_dir, RECEIPT), encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def parse_tsv(stdout: str) -> tuple[str, float | None, int]:
    """(the page's words joined per line, the mean confidence of words with one, the word count)."""
    lines: dict[tuple[int, int, int], list[str]] = {}
    confs: list[float] = []
    for row in stdout.splitlines()[1:]:
        cells = row.split("\t")
        if len(cells) < 12 or not cells[11].strip():
            continue
        try:
            conf = float(cells[10])
            key = (int(cells[2]), int(cells[3]), int(cells[4]))
        except ValueError:
            continue
        if conf >= 0:
            confs.append(conf)
        lines.setdefault(key, []).append(cells[11])
    text = "\n".join(" ".join(words) for _, words in sorted(lines.items()))
    return text, (round(statistics.mean(confs), 1) if confs else None), sum(len(w) for w in lines.values())


def read_page(pdf: str, page: int, dpi: int) -> tuple[str, float | None, int]:
    """Render one page and OCR it. Raises on a tool failure or timeout."""
    with tempfile.TemporaryDirectory() as td:
        stem = os.path.join(td, "page")
        subprocess.run(
            ["pdftoppm", "-f", str(page), "-l", str(page), "-r", str(dpi), "-png", "-singlefile", pdf, stem],
            check=True,
            capture_output=True,
            timeout=PDFTOPPM_TIMEOUT,
        )
        result = subprocess.run(
            ["tesseract", stem + ".png", "stdout", "tsv"],
            check=True,
            capture_output=True,
            text=True,
            timeout=TESSERACT_TIMEOUT,
        )
    return parse_tsv(result.stdout)


def _tesseract_version() -> str | None:
    try:
        out = subprocess.run(["tesseract", "--version"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    first = (out.stdout or out.stderr).splitlines()
    return first[0].strip() if first else None


def _finish(out_dir: str, receipt: dict[str, Any], pretty: bool) -> int:
    _write_receipt(out_dir, receipt)
    pages = receipt.get("pages") or {}
    summary = {
        "complete": receipt.get("complete", False),
        "status": receipt.get("status"),
        "reason": receipt.get("reason"),
        "pages": sum(1 for p in pages.values() if p.get("kind") in ("ocr", "empty")),
        "failed": sum(1 for p in pages.values() if p.get("kind") == "failed"),
        "not_read": sum(1 for p in pages.values() if p.get("kind") == "not_read"),
        "pending": sum(1 for p in pages.values() if p.get("kind") == "pending"),
    }
    print(json.dumps(summary, indent=2 if pretty else None))
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--deck", required=True, help="the PDF Step 2's deck_text.py read")
    p.add_argument("--ledger", required=True)
    p.add_argument("--reconciliation", required=True)
    p.add_argument("--deck-text", required=True)
    p.add_argument("--run-id", required=True)
    p.add_argument("-o", "--output", required=True, help="a folder: the run's hand-off ocr/")
    p.add_argument("--max-pages", type=int, default=_ocr_scope.MAX_PAGES)
    # 30 s + a 15 s render + a 30 s read is 75 s at worst, under the cloud shell's 120 s kill
    # (the local Cowork limit is unmeasured).
    p.add_argument("--budget-seconds", type=float, default=30.0)
    p.add_argument("--dpi", type=int, default=200)
    p.add_argument("--pretty", action="store_true")
    args = p.parse_args(argv)

    out_dir = args.output
    if not os.path.exists(args.deck):
        return _reject("DECK_NOT_FOUND", f"no deck at {args.deck}")
    if os.path.exists(out_dir) and not os.path.isdir(out_dir):
        return _reject("OUTPUT_NOT_DIR", f"{out_dir} is a file; -o names the folder the read is kept in")
    import _out_guard

    _out_guard.refuse_output_onto_input([args.output, os.path.join(args.output, RECEIPT)], script="deck_ocr.py")
    import _run_ref

    # The folder above `-o` is the hand-off dir; the review dir (whose ref decides ownership) holds the inputs.
    _run_ref.refuse_not_this_runs(
        os.path.dirname(os.path.abspath(args.deck_text)),
        args.run_id,
        [args.ledger, args.reconciliation, args.deck_text],
        noun="review dir",
    )
    try:
        with open(args.ledger, encoding="utf-8") as fh:
            ledger = json.load(fh)
        if not isinstance(ledger, dict):
            raise ValueError("not a JSON object")
    except (OSError, ValueError) as exc:
        return _reject("LEDGER_UNREADABLE", f"cannot read {args.ledger}: {exc}")
    try:
        with open(args.reconciliation, encoding="utf-8") as fh:
            reconciliation = json.load(fh)
        if not isinstance(reconciliation, dict):
            raise ValueError("not a JSON object")
    except (OSError, ValueError) as exc:
        return _reject("RECONCILIATION_UNREADABLE", f"cannot read {args.reconciliation}: {exc}")
    _, problem = _deck_text_file.stamp(args.deck_text, args.run_id)
    if problem is not None:
        return _reject(problem["code"], problem["message"])
    with open(args.deck_text, encoding="utf-8") as fh:
        deck_text = fh.read()
    front, body = _deck_text_file.split(deck_text)
    pages_source = _deck_text_file.pages_source(front)

    with open(args.deck, "rb") as deck_fh:
        deck_sha = hashlib.sha256(deck_fh.read()).hexdigest()
    base: dict[str, Any] = {
        "run_id": args.run_id,
        "deck_sha256": deck_sha,
        "created_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    def done(status: str | None, reason: str | None, **extra: Any) -> int:
        return _finish(out_dir, {**base, "status": status, "reason": reason, "complete": True, **extra}, args.pretty)

    # The deck first: a file other than the one the deck text was read from is never read as if it were.
    if (front or {}).get("deck_sha256") != deck_sha:
        return done("not_applicable", "deck_mismatch")
    if not args.deck.lower().endswith(".pdf"):
        return done("not_applicable", "not_pdf")
    if not pages_source or "inventory" not in pages_source.values():
        return done("not_applicable", "no_inventory")
    slides = len(_SLIDE_HEADING.findall(body))
    count = _pdf_pages.page_count(args.deck)
    if count is not None and count != slides:
        return done("not_applicable", "page_count_mismatch", pages_total=count)
    figures = _ocr_scope.in_scope(ledger, reconciliation, pages_source)
    wanted, over = _ocr_scope.pages(figures, args.max_pages)
    if not figures:
        return done("no_figures", "no_figures")
    if shutil.which("pdftoppm") is None or shutil.which("tesseract") is None:
        return done("unavailable", "no_ocr_tools", ocr_available=False)
    # With no page count (no pdfinfo, no pypdf) the count check is skipped; a PDF no page of which renders ends
    # as `unreadable_pdf` below.

    prior = _load_receipt(out_dir)
    same = (
        prior.get("run_id") == args.run_id
        and prior.get("deck_sha256") == deck_sha
        and prior.get("scope_pages") == wanted
        and prior.get("max_pages") == args.max_pages
        and isinstance(prior.get("pages"), dict)
    )
    pages: dict[str, dict[str, Any]] = dict(prior["pages"]) if same else {}
    for n in wanted:
        pages.setdefault(str(n), {"kind": "pending", "attempts": 0})
    for n in over:
        pages[str(n)] = {"kind": "not_read", "attempts": 0}
    receipt: dict[str, Any] = {
        **base,
        "created_at": prior.get("created_at", base["created_at"]) if same else base["created_at"],
        "status": "read",
        "reason": None,
        "ocr_available": True,
        "tesseract_version": _tesseract_version(),
        "pages_total": count,
        "scope_pages": wanted,
        "max_pages": args.max_pages,
        "pages": pages,
        "complete": False,
    }
    started = 0
    for n in wanted:
        entry = pages[str(n)]
        if entry["kind"] != "pending":
            continue
        if int(entry.get("attempts", 0)) >= MAX_ATTEMPTS:
            # A page whose earlier calls were killed mid-read never reached the `except` below.
            entry["kind"] = "failed"
            _write_receipt(out_dir, receipt)
            continue
        if started and time.monotonic() - _START >= args.budget_seconds:
            break
        started += 1
        entry["attempts"] = int(entry.get("attempts", 0)) + 1
        _write_receipt(out_dir, receipt)  # the attempt is on record before the page can hang or be killed
        try:
            text, conf, words = read_page(args.deck, n, args.dpi)
        except (OSError, subprocess.SubprocessError):
            if entry["attempts"] >= MAX_ATTEMPTS:
                entry["kind"] = "failed"
            _write_receipt(out_dir, receipt)
            continue
        with open(os.path.join(out_dir, f"p{n}.txt"), "w", encoding="utf-8") as fh:
            fh.write(text)
        entry.update(
            {
                "kind": "ocr" if words else "empty",
                "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "chars": len(text),
                "mean_conf": conf,
            }
        )
        _write_receipt(out_dir, receipt)
    receipt["complete"] = all(pages[str(n)]["kind"] != "pending" for n in wanted)
    if receipt["complete"] and wanted and all(pages[str(n)]["kind"] == "failed" for n in wanted):
        receipt["status"], receipt["reason"] = "unavailable", "unreadable_pdf"
    return _finish(out_dir, receipt, args.pretty)


if __name__ == "__main__":
    sys.exit(main())
