#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Step 3.95's check: how many of the figures the numbers section uses from image slides a machine read
found as written. Counts only; no figure is ever named to the founder.

    ocr_check.py --ledger L --reconciliation R --deck-text D --ocr-dir "$HANDOFF_DIR/ocr" --run-id ID -o OUT

Reads `deck_ocr.py`'s receipt and page texts in `--ocr-dir`. Writes `OUT` (status, counts, the pages that were
machine-read, metadata) and, beside the receipt, `figures.json` with each figure's own result, which no later
step's template names.

Exits:
  0  written;
  1  refused, `-o` untouched: an unreadable input, a `DECK_TEXT_` code, or `OCR_OTHER_RUN` (the receipt is
     another run's);
  2  `OCR_NOT_RUN` (no receipt) or `OCR_INCOMPLETE` (the receipt is unreadable, the read has not finished, was
     made from another deck file, or its pages are not this scope's): run Step 3.95's command again. Never a
     producer rejection.

The numeral rule matches each raw figure's numbers against the page's, by value, scale and percent, built from
reconcile's shared grammar (a copy would drift from the grammar the ledger was validated with). Counts only,
because on clean renders about one correct figure in nine goes unfound (charts, styled text), so a per-figure list
would wrongly single figures out. The named residuals are pinned in the tests.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from decimal import Decimal, InvalidOperation
from typing import Any

import _deck_text_file
import _ocr_scope
from _quote_match import normalize_text
from reconcile import (
    _EXPONENT,
    _MANTISSA,
    _NUM_RE,
    _RANGE_RE,
    _SCALE,
    _SCALE_ALT,
    _SUPERSCRIPT_DIGITS,
    numeral_form,
    spelled_number,
    strip_group_marks,
)

LOW_MATCH_MIN = 3  # figures checked before a low find rate can hide the count
SMALL_WORDS = {
    0: "zero",
    1: "one",
    2: "two",
    3: "three",
    4: "four",
    5: "five",
    6: "six",
    7: "seven",
    8: "eight",
    9: "nine",
    10: "ten",
}
_PCT_AFTER = re.compile(r"\s*%")
# A suffix glued to the next word ("493Kin"): exactly what `_NUM_RE`'s guard refuses. Built from the shared
# pieces so a scale one grammar knows is one this pass knows.
GLUED_RE = re.compile(rf"(?P<int>{_MANTISSA})(?:\.(?P<frac>\d+))?(?P<suf>{_SCALE_ALT})(?=[a-zA-Z])", re.I)
GLUED_RANGE_RE = re.compile(
    rf"(?P<a>{_MANTISSA}(?:\.\d+)?)\s*[-–—]\s*\$?\s*(?P<b>{_MANTISSA}(?:\.\d+)?)\s*"
    rf"(?P<suf>{_SCALE_ALT})(?=[a-zA-Z])",
    re.I,
)
_EXP_RE = re.compile(_EXPONENT)

# A token: (value, frozenset of scales it may carry, percent flag).
Token = tuple[Decimal, frozenset[float], bool]


def _scale(suffix: str | None) -> float:
    return float(_SCALE.get((suffix or "").lower(), 1.0)) if suffix else 1.0


def _exp(m: re.Match[str]) -> float:
    e = m.groupdict().get("eexp") or m.groupdict().get("exp")
    if not e:
        return 1.0
    try:
        return 10.0 ** int(e.translate(_SUPERSCRIPT_DIGITS))
    except ValueError:
        return 1.0


def _dec(mantissa: str, frac: str | None = None) -> Decimal | None:
    digits = strip_group_marks(mantissa).replace(" ", "")
    try:
        return Decimal(digits + ("." + frac if frac else ""))
    except InvalidOperation:
        return None


def _split_end(s: str) -> Decimal | None:
    whole, _, frac = s.partition(".")
    return _dec(whole, frac or None)


def guarded(text: str) -> tuple[list[Token], list[tuple[int, int]]]:
    """The guarded pass: ranges first (their shared suffix and a trailing `%` apply to both ends), then
    `_NUM_RE` on the rest. Returns the tokens and the character spans where a match read a suffix."""
    out: list[Token] = []
    suffix_starts: list[tuple[int, int]] = []
    buf = list(text)
    for m in _RANGE_RE.finditer(text):
        sc = _scale(m.group("suf"))
        pct = bool(_PCT_AFTER.match(text, m.end()))
        for end in ("a", "b"):
            v = _split_end(m.group(end))
            if v is not None:
                out.append((v, frozenset({sc}), pct))
        if m.group("suf"):
            suffix_starts.append((m.start(), m.end()))
        for k in range(m.start(), m.end()):
            buf[k] = " "
    rest = "".join(buf)
    for m in _NUM_RE.finditer(rest):
        v = _dec(m.group("int"), m.group("frac"))
        if v is None:
            continue
        out.append((v, frozenset({_scale(m.group("suf")) * _exp(m)}), bool(_PCT_AFTER.match(rest, m.end()))))
        if m.group("suf"):
            suffix_starts.append((m.start(), m.end()))
    return out, suffix_starts


def glued(line: str, suffix_spans: list[tuple[int, int]]) -> list[Token]:
    """The glued pass, on the original line: a suffix run into the next word answers either reading. A glued
    match that starts where a guarded match read a suffix is dropped (offsets on the joined line)."""
    starts = {s for s, _ in suffix_spans}
    out: list[Token] = []
    for m in GLUED_RANGE_RE.finditer(line):
        if m.start() in starts:
            continue
        sc = _scale(m.group("suf"))
        for end in ("a", "b"):
            v = _split_end(m.group(end))
            if v is not None:
                out.append((v, frozenset({1.0, sc}), bool(_PCT_AFTER.match(line, m.end()))))
    for m in GLUED_RE.finditer(line):
        if m.start() in starts:
            continue
        v = _dec(m.group("int"), m.group("frac"))
        if v is not None:
            out.append((v, frozenset({1.0, _scale(m.group("suf"))}), bool(_PCT_AFTER.match(line, m.end()))))
    return out


def _bare(word: str) -> str:
    return re.sub(r"[^\w]", "", word).lower()


def page_tokens(page: str, *, with_glued: bool) -> list[Token]:
    """Every token on the page: each line's guarded pass, each word's on its own (dropped when the next word on
    its line is a scale word, so a bare `1.5` is not found on `1.5 Million`), and, for a raw that carries a
    scale, the glued pass."""
    out: list[Token] = []
    for line in page.split("\n"):
        line_tokens, spans = guarded(line)
        out += line_tokens
        words = line.split()
        for i, word in enumerate(words):
            nxt = _bare(words[i + 1]) if i + 1 < len(words) else ""
            if nxt in _SCALE:
                continue
            out += guarded(word)[0]
        if with_glued:
            out += glued(line, spans)
    return out


def raw_tokens(raw: str) -> list[tuple[Decimal, float, bool]] | None:
    """The raw figure's numbers as (value, scale, percent); None when it prints no digit (the words branch)."""
    if not _NUM_RE.search(raw or ""):
        return None
    return [(v, next(iter(s)), pct) for v, s, pct in guarded(numeral_form(raw))[0]]


def found(raw: str, page: str, allow_spelled: bool = True) -> bool:
    """Whether every number of `raw` appears on `page` as written: equal value, the raw's scale among the page
    token's, and the same percent flag. A raw with no digits is matched by its spelled-out words, and a small
    integer also by its word; `allow_spelled=False` matches numerals only."""
    if not page:
        return False
    low = normalize_text(page).lower()
    rt = raw_tokens(raw)
    if rt is None:
        if not allow_spelled:
            return False
        spelled = spelled_number(raw)
        if spelled is None:
            return False
        words = raw[spelled[1] : spelled[2]].lower().split()
        if len(words) == 1:
            return re.search(rf"\b{re.escape(words[0])}\b", low) is not None
        return "".join(words) in re.sub(r"[^a-z0-9]", "", low)
    if not rt:
        return False
    pt = page_tokens(page, with_glued=any(s != 1.0 for _, s, _ in rt))
    for v, s, pct in rt:
        hit = any(p[0] == v and s in p[1] and p[2] == pct for p in pt)
        if not hit and allow_spelled and not pct and s == 1.0 and v == v.to_integral_value() and 0 <= v <= 10:
            hit = re.search(rf"\b{SMALL_WORDS[int(v)]}\b", low) is not None
        if not hit:
            return False
    return True


# --- the CLI --------------------------------------------------------------------------------------------------


def _fail(code: str, message: str, fix: str, exit_code: int) -> int:
    sys.stdout.write(json.dumps({"status": "rejected", "code": code, "message": message, "fix": fix}) + "\n")
    print(f"Error ({code}): {message}; nothing was written", file=sys.stderr)
    return exit_code


_RERUN = "run Step 3.95's command again (deck_ocr.py until it prints complete, then this check)"


def _load_json(path: str) -> Any:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _sha(path: str) -> str:
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def _write_json(path: str, data: dict[str, Any]) -> None:
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
    tmp = f"{os.path.abspath(path)}.tmp.{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(data, indent=2) + "\n")
    os.replace(tmp, path)


def check(
    ledger: dict[str, Any],
    reconciliation: dict[str, Any],
    pages_source: dict[int, str] | None,
    receipt: dict[str, Any],
    ocr_dir: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """(the run's status and counts, each figure's result). Pure but for reading the page texts."""
    carried = receipt.get("status")
    if carried == "not_applicable":
        return {"status": carried, "reason": receipt.get("reason")}, []
    figures = _ocr_scope.in_scope(ledger, reconciliation, pages_source)
    if not figures:
        return {"status": "no_figures"}, []
    slides = sorted({int(f["slide"]) for f in figures})
    if carried == "unavailable":
        return {"status": carried, "reason": receipt.get("reason"), "slides": slides}, []
    raw_pages = receipt.get("pages")
    page_info: dict[str, Any] = raw_pages if isinstance(raw_pages, dict) else {}
    results: list[dict[str, Any]] = []
    for fig in figures:
        info = page_info.get(str(fig["slide"])) or {}
        kind = info.get("kind")
        if kind == "ocr":
            try:
                with open(os.path.join(ocr_dir, f"p{fig['slide']}.txt"), encoding="utf-8") as fh:
                    text = fh.read()
            except OSError:
                results.append({"id": fig["id"], "slide": fig["slide"], "result": "not_checked", "reason": "failed"})
                continue
            results.append(
                {"id": fig["id"], "slide": fig["slide"], "result": "found" if found(fig["raw"], text) else "not_found"}
            )
        else:
            reason = kind if kind in ("not_read", "failed", "empty") else "not_read"
            results.append({"id": fig["id"], "slide": fig["slide"], "result": "not_checked", "reason": reason})
    counts = {
        "in_scope": len(results),
        "checked": sum(r["result"] in ("found", "not_found") for r in results),
        "found": sum(r["result"] == "found" for r in results),
        "not_found": sum(r["result"] == "not_found" for r in results),
        "not_checked": sum(r["result"] == "not_checked" for r in results),
    }
    if counts["checked"] == 0:
        status = "none_read"
    elif counts["checked"] >= LOW_MATCH_MIN and counts["found"] * 2 < counts["checked"]:
        status = "low_match"
    else:
        status = "checked"
    machine_read = sorted({r["slide"] for r in results if r["result"] in ("found", "not_found")})
    return {"status": status, "counts": counts, "pages_machine_read": machine_read, "slides": slides}, results


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--ledger", required=True)
    p.add_argument("--reconciliation", required=True)
    p.add_argument("--deck-text", required=True)
    p.add_argument("--ocr-dir", required=True, help="deck_ocr.py's output folder (the run's hand-off ocr/)")
    p.add_argument("--run-id", required=True)
    p.add_argument("-o", "--output", required=True)
    p.add_argument("--pretty", action="store_true")
    args = p.parse_args(argv)

    import _out_guard

    figures_path = os.path.join(args.ocr_dir, "figures.json")
    _out_guard.refuse_output_onto_input([args.output, figures_path], script="ocr_check.py")
    import _run_ref

    _run_ref.refuse_not_this_runs(
        os.path.dirname(os.path.abspath(args.output)),
        args.run_id,
        [args.ledger, args.reconciliation, args.deck_text],
        noun="review dir",
    )

    try:
        ledger = _load_json(args.ledger)
        if not isinstance(ledger, dict):
            raise ValueError("not a JSON object")
    except (OSError, ValueError) as exc:
        return _fail("LEDGER_UNREADABLE", f"cannot read {args.ledger}: {exc}", "run Step 3.5's ledger pipe again", 1)
    try:
        reconciliation = _load_json(args.reconciliation)
        if not isinstance(reconciliation, dict):
            raise ValueError("not a JSON object")
    except (OSError, ValueError) as exc:
        return _fail(
            "RECONCILIATION_UNREADABLE",
            f"cannot read {args.reconciliation}: {exc}",
            "run Steps 3.8-3.9 again",
            1,
        )
    deck_text_sha, problem = _deck_text_file.stamp(args.deck_text, args.run_id)
    if problem is not None:
        return _fail(problem["code"], problem["message"], "run Step 2's deck_text.py again", 1)
    with open(args.deck_text, encoding="utf-8") as fh:
        deck_text = fh.read()
    pages_source = _deck_text_file.pages_source(_deck_text_file.front_matter(deck_text))

    receipt_path = os.path.join(args.ocr_dir, "receipt.json")
    if not os.path.exists(receipt_path):
        return _fail("OCR_NOT_RUN", f"no machine-read receipt at {receipt_path}", _RERUN, 2)
    try:
        receipt = _load_json(receipt_path)
        if not isinstance(receipt, dict):
            raise ValueError("not a JSON object")
    except (OSError, ValueError) as exc:
        return _fail("OCR_INCOMPLETE", f"the receipt at {receipt_path} is unreadable: {exc}", _RERUN, 2)
    if receipt.get("run_id") != args.run_id:
        return _fail(
            "OCR_OTHER_RUN",
            f"the receipt at {receipt_path} belongs to run {receipt.get('run_id')!r}, not {args.run_id!r}",
            _RERUN,
            1,
        )
    if not receipt.get("complete"):
        return _fail("OCR_INCOMPLETE", "the machine read has not finished", _RERUN, 2)
    # The receipt must be for this deck and this scope: re-running only this check after the deck file or the
    # kept relations changed must not pass on an earlier read.
    deck_sha = (_deck_text_file.front_matter(deck_text) or {}).get("deck_sha256")
    if receipt.get("reason") != "deck_mismatch" and receipt.get("deck_sha256") != deck_sha:
        return _fail("OCR_INCOMPLETE", "the machine read was made from another deck file", _RERUN, 2)
    figures = _ocr_scope.in_scope(ledger, reconciliation, pages_source)
    recorded = receipt.get("max_pages")
    max_pages: int = recorded if isinstance(recorded, int) else _ocr_scope.MAX_PAGES
    wanted, _over = _ocr_scope.pages(figures, max_pages)
    status = receipt.get("status")
    if status == "no_figures" and figures:
        return _fail("OCR_INCOMPLETE", "the machine read found no figures to read, and this run has some", _RERUN, 2)
    if status not in ("not_applicable", "unavailable", "no_figures") and receipt.get("scope_pages") != wanted:
        return _fail("OCR_INCOMPLETE", "the machine read covered other pages than this run's figures", _RERUN, 2)

    summary, results = check(ledger, reconciliation, pages_source, receipt, args.ocr_dir)
    out: dict[str, Any] = {
        **summary,
        "metadata": {
            "run_id": args.run_id,
            "ocr_receipt_sha256": _sha(receipt_path),
            "deck_text_sha256": deck_text_sha,
            "reconciliation_sha256": _sha(args.reconciliation),
        },
    }
    if results or summary["status"] not in ("not_applicable", "unavailable"):
        _write_json(figures_path, {"run_id": args.run_id, "figures": results})
    _write_json(args.output, out)
    receipt_out = {"ok": True, "path": args.output, "status": out["status"]}
    if "counts" in out:
        receipt_out["counts"] = out["counts"]
    print(json.dumps(receipt_out, indent=2 if args.pretty else None))
    return 0


if __name__ == "__main__":
    sys.exit(main())
