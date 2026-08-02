#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""Seed the local privacy denylist from the real source documents + run outputs.

The privacy guard (`privacy_guard.py`, layer 3) blocks commits containing any
name/figure on a LOCAL, git-ignored denylist. The hard part is keeping that list
fresh: a new critique campaign introduces new real companies, and if the list is
stale the guard silently passes their names. This tool refreshes the list.

It is NAME-FREE: the mechanism ships in the repo; the real names/figures it
harvests are written ONLY to `docs/internal/privacy-denylist.txt`, which lives
under the git-ignored `docs/internal/` and never enters the repo or CI.

Two high-precision sources (NOT prose regex over transcripts — that false-
positives on synthetic fixtures):
  * source-document FILENAMES — they enumerate the real parties
    ("Foo - Convertible Note (Bar Capital II).pdf" → "Foo", "Bar Capital II").
  * run-output `instruments.json` — distinctive figures (cents-precision or long
    non-round integers), which filenames don't carry.

Name candidates are split into AUTO (clearly distinctive: CamelCase, coined
alphanumerics, all-caps coinages, or multi-word phrases) and #REVIEW (bare
single words that could be common English — the human promotes the real ones).
This honors the denylist's "only DISTINCTIVE names/phrases" rule.

The source roots are NOT hardcoded: pass `--source DIR` (repeatable) or list them
in the git-ignored `docs/internal/privacy-sources.txt` (one path per line).

Usage:
  privacy_denylist_from_sources.py --source ~/path/to/docs --source /path/to/runs
  privacy_denylist_from_sources.py            # reads docs/internal/privacy-sources.txt
  privacy_denylist_from_sources.py --dry-run  # print, don't write
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

# --- config paths (the denylist + the source-roots list both git-ignored) ---
DEFAULT_DENYLIST = "docs/internal/privacy-denylist.txt"
DEFAULT_SOURCES_CONFIG = "docs/internal/privacy-sources.txt"

_DOC_EXTS = {".pdf", ".docx", ".doc", ".xlsx", ".xls", ".pptx", ".ppt"}

# Path segments that are mounted COPIES of this repo (or vendored trees) inside a
# run corpus — harvesting from them would recycle the repo's OWN synthetic
# fixtures back into the denylist and self-block. Skip them.
_EXCLUDED_SEGMENTS = {
    ".local-plugins",
    ".remote-plugins",
    "marketplaces",
    "cowork_plugins",
    "node_modules",
    ".git",
    ".venv",
}

# Generic cap-table / paperwork words that are never a company identity. Kept
# lowercase; matched case-insensitively. Deliberately broad — a dropped real
# token resurfaces via the #REVIEW list, but a generic word auto-added would
# false-positive everywhere.
_GENERIC = {
    "safe",
    "note",
    "notes",
    "cap",
    "table",
    "term",
    "sheet",
    "terms",
    "series",
    "seed",
    "round",
    "rounds",
    "pre",
    "money",
    "post",
    "amendment",
    "amendments",
    "convertible",
    "promissory",
    "pro",
    "forma",
    "proforma",
    "final",
    "clean",
    "redline",
    "signed",
    "executed",
    "tracked",
    "changes",
    "change",
    "valuation",
    "discount",
    "exhibit",
    "illustration",
    "voting",
    "agreement",
    "rights",
    "investors",
    "investor",
    "israeli",
    "tax",
    "ruling",
    "flip",
    "secondary",
    "preemptive",
    "preferred",
    "legacy",
    "cover",
    "covers",
    "simulation",
    "including",
    "additional",
    "closing",
    "restated",
    "filed",
    "draft",
    "drafts",
    "summary",
    "intermediate",
    "detailed",
    "grouped",
    "ledgers",
    "ledger",
    "share",
    "shares",
    "purchase",
    "securities",
    "exchange",
    "sale",
    "ancillaries",
    "and",
    "the",
    "with",
    "for",
    "des",
    "as",
    "of",
    "a",
    "an",
    "to",
    "coi",
    "rofr",
    "ira",
    "de",
    "us",
    "form",
    "company",
    "inc",
    "ltd",
    "llc",
    "lp",
    "co",
    "corp",
}

# Words that never stand alone as a name but extend a multi-word phrase
# ("Bar Capital II", "Foo Robotics Ltd", "Baz Ventures").
_CONNECTORS = {
    "capital",
    "ventures",
    "partners",
    "fund",
    "funds",
    "holdings",
    "robotics",
    "bio",
    "tech",
    "group",
    "labs",
    "systems",
    "health",
    "ai",
    "inc",
    "ltd",
    "llc",
    "lp",
    "co",
    "corp",
    "gmbh",
    "sa",
    "plc",
}
_ROMAN = {"ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x"}

# Publicly-referenced firms (law firms, standard bodies) that legitimately appear
# in the repo's own domain material (citations, top-firm lists). They may show up
# in a source filename (the firm that prepared a cap table), but they are NOT
# confidential deal parties — denylisting them would false-positive on the
# reference docs that cite them. These are PUBLIC names, so listing them in the
# committed script discloses nothing. Matched case-insensitively. Extend as
# needed via the git-ignored config's `#allow <name>` lines (see read_allowlist).
_PUBLIC_ALLOWLIST = {
    "pearl cohen",
    "herzog",
    "meitar",
    "goldfarb",
    "gornitzky",
    "naschitz",
    "shibolet",
    "gross",
    "barnea",
    "cooley",
    "nvca",
    "carta",
    "sequoia",
}

# Months, so "Dec2017"/"06SEP22" style date tokens are not mistaken for coinages.
_MONTHS = {"jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"}
_MONTH_NAMES = {
    "january",
    "february",
    "march",
    "april",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
}
# Month tokens are pervasive in dated filenames and are never a company name.
_GENERIC |= _MONTHS | _MONTH_NAMES


# --------------------------------------------------------------------------
# Name classification (from a filename)
# --------------------------------------------------------------------------
def _is_camelcase(word: str) -> bool:
    """Internal case change: FooBarRx, iZoom, NorthCap, MegaCorp."""
    return bool(re.search(r"[a-z][A-Z]", word) or re.search(r"[A-Z]{2,}[a-z]", word))


def _is_coined_alnum(word: str) -> bool:
    """Letters+digits coinage with >= 4 letters, letter-initial (Acme7x,
    Zeta42) — excludes date/amount tokens (06SEP22, 100K, Dec2017)."""
    if not word[:1].isalpha():
        return False
    if not re.search(r"\d", word):
        return False
    if sum(c.isalpha() for c in word) < 4:
        return False
    return word.lower().rstrip("0123456789") not in _MONTHS


def _is_allcaps_coinage(word: str) -> bool:
    """All-caps, length >= 5, alphabetic (QRSMOO, FOOBAR) — excludes short
    acronyms (SAFE, ROFR) which are generic/common anyway."""
    return word.isupper() and word.isalpha() and len(word) >= 5


def _is_distinctive_single(word: str) -> bool:
    return _is_camelcase(word) or _is_coined_alnum(word) or _is_allcaps_coinage(word)


def _is_plain_capitalized(word: str) -> bool:
    """First-letter-capitalized ordinary word (Rivers, Placeholder, Bowery)."""
    return len(word) >= 2 and word[0].isupper() and word[1:].islower() and word.isalpha()


def _tokenize_stem(stem: str) -> list[str]:
    return [w for w in re.split(r"[\s\-_(),.\[\]/]+", stem) if w]


def classify_filename(filename: str, allowlist: set[str] | None = None) -> tuple[set[str], set[str]]:
    """Return (auto, review) name candidates for a single filename.

    auto  — clearly distinctive: coined/CamelCase single tokens + multi-word
            phrases (a phrase is distinctive even when its words are ordinary).
    review— bare single ordinary words (could be common English): surfaced for
            the human to promote, never auto-added.

    `allowlist` (lowercased public-reference names) is dropped from both sets.
    """
    allow = _PUBLIC_ALLOWLIST if allowlist is None else allowlist
    stem = os.path.splitext(os.path.basename(filename))[0]
    words = _tokenize_stem(stem)

    def kind(w: str) -> str:
        low = w.lower()
        if low in _GENERIC:
            return "generic"
        if low in _ROMAN or low in _CONNECTORS:
            return "connector"
        if _is_distinctive_single(w):
            return "distinct"
        if _is_plain_capitalized(w):
            return "name"
        return "drop"

    kinds = [kind(w) for w in words]

    auto: set[str] = set()
    review: set[str] = set()

    # Walk runs of adjacent name/distinct/connector words → phrases; a run with
    # >= 2 words and >= 1 real name word is an auto phrase. Singletons fall
    # through to per-word handling.
    i = 0
    n = len(words)
    while i < n:
        if kinds[i] in ("name", "distinct"):
            j = i
            while j < n and kinds[j] in ("name", "distinct", "connector"):
                j += 1
            # Keep the full run, including trailing connectors ("Capital II",
            # "Robotics Ltd") — they are part of the investor/company name.
            run = words[i:j]
            has_name = any(kinds[k] in ("name", "distinct") for k in range(i, j))
            if len(run) >= 2 and has_name:
                auto.add(" ".join(run))
            elif kinds[i] == "distinct":
                auto.add(words[i])
            else:
                review.add(words[i])
            i = j
        else:
            i += 1
    auto = {a for a in auto if a.lower() not in allow}
    review = {r for r in review if r.lower() not in allow}
    return auto, review


# --------------------------------------------------------------------------
# Distinctive figures (from instruments.json)
# --------------------------------------------------------------------------
def _group(digits: str, sep: str) -> str:
    """Group an integer digit-string in threes from the right with `sep`."""
    out = []
    for idx, ch in enumerate(reversed(digits)):
        if idx and idx % 3 == 0:
            out.append(sep)
        out.append(ch)
    return "".join(reversed(out))


def figure_forms(value: int | float) -> set[str]:
    """The plain / comma-grouped / underscore-grouped spellings of a figure —
    so the denylist matches whatever formatting a leaked copy used."""
    if isinstance(value, float) and not value.is_integer():
        cents = f"{value:.2f}"
        int_part, frac = cents.split(".")
        neg = int_part.startswith("-")
        digits = int_part.lstrip("-")
        return {
            ("-" if neg else "") + digits + "." + frac,
            ("-" if neg else "") + _group(digits, ",") + "." + frac,
            ("-" if neg else "") + _group(digits, "_") + "." + frac,
        }
    iv = int(value)
    neg = iv < 0
    digits = str(abs(iv))
    pref = "-" if neg else ""
    return {pref + digits, pref + _group(digits, ","), pref + _group(digits, "_")}


def _is_distinctive_figure(value: int | float) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, float):
        if value.is_integer():
            value = int(value)
        else:
            return abs(value) >= 1000  # cents-precision, non-trivial magnitude
    # integer path: long AND not a round number (round = trailing >=4 zeros)
    s = str(abs(int(value)))
    if len(s) < 6:
        return False
    return not re.search(r"0{4,}$", s)


def distinctive_figures(obj: object) -> set[str]:
    """Recurse a JSON-ish structure; return all form-spellings of distinctive
    numeric values (cents-precision, or long non-round integers)."""
    out: set[str] = set()

    def walk(o: object) -> None:
        if isinstance(o, dict):
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
        elif isinstance(o, (int, float)) and not isinstance(o, bool) and _is_distinctive_figure(o):
            out.update(figure_forms(o))

    walk(obj)
    return out


# --------------------------------------------------------------------------
# Harvest + merge
# --------------------------------------------------------------------------
def harvest(roots: list[str], allowlist: set[str] | None = None) -> tuple[set[str], set[str], set[str]]:
    """Walk source roots: names from document filenames, figures from every
    instruments.json. Returns (auto_names, review_names, figures)."""
    allow = _PUBLIC_ALLOWLIST if allowlist is None else allowlist
    auto_names: set[str] = set()
    review_names: set[str] = set()
    figures: set[str] = set()
    for root in roots:
        if not os.path.isdir(root):
            if os.path.isfile(root):  # a single file passed directly
                _ingest_file(root, auto_names, review_names, figures, allow)
            continue
        for dirpath, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in _EXCLUDED_SEGMENTS]  # prune mounts
            for name in files:
                _ingest_file(os.path.join(dirpath, name), auto_names, review_names, figures, allow)
    return auto_names, review_names, figures


def _ingest_file(path: str, auto: set[str], review: set[str], figures: set[str], allow: set[str]) -> None:
    base = os.path.basename(path)
    ext = os.path.splitext(base)[1].lower()
    if ext in _DOC_EXTS:
        a, r = classify_filename(base, allow)
        auto.update(a)
        review.update(r)
    if base == "instruments.json":
        try:
            with open(path, encoding="utf-8") as f:
                figures.update(distinctive_figures(json.load(f)))
        except (OSError, ValueError):
            pass


_AUTO_BEGIN = "# === AUTO-GENERATED by privacy_denylist_from_sources.py — regenerated each run ==="
_AUTO_END = "# === END AUTO-GENERATED ==="


def merge_denylist(existing: str, auto_names: set[str], figures: set[str], review_names: set[str]) -> str:
    """Preserve everything outside the auto block; regenerate the auto block.
    Idempotent: running over prior output reproduces the same file."""
    # strip a previous auto block (inclusive of markers)
    lines = existing.splitlines()
    kept: list[str] = []
    in_block = False
    for line in lines:
        if line.strip() == _AUTO_BEGIN:
            in_block = True
            continue
        if line.strip() == _AUTO_END:
            in_block = False
            continue
        if not in_block:
            kept.append(line)
    manual = "\n".join(kept).rstrip()

    block: list[str] = [_AUTO_BEGIN]
    if auto_names:
        block.append("# names (distinctive — auto):")
        block.extend(sorted(auto_names, key=str.lower))
    if figures:
        block.append("# distinctive figures (all spellings):")
        block.extend(sorted(figures))
    if review_names:
        block.append("# REVIEW — bare single words; uncomment any that ARE a real company:")
        block.extend(f"#REVIEW {r}" for r in sorted(review_names, key=str.lower))
    block.append(_AUTO_END)

    return manual + "\n\n" + "\n".join(block) + "\n"


def read_source_roots(cli_roots: list[str], config_path: str) -> list[str]:
    """Source roots come from --source args, else the git-ignored config file.
    NEVER a hardcoded default path. Empty result → the CLI must error."""
    if cli_roots:
        return [os.path.expanduser(r) for r in cli_roots]
    if os.path.isfile(config_path):
        roots = []
        with open(config_path, encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if s and not s.startswith("#"):
                    roots.append(os.path.expanduser(s))
        return roots
    return []


def read_allowlist(config_path: str) -> set[str]:
    """Public-reference names to never denylist. Starts from _PUBLIC_ALLOWLIST;
    the git-ignored config may extend it with `#allow <name>` lines."""
    allow = set(_PUBLIC_ALLOWLIST)
    if os.path.isfile(config_path):
        with open(config_path, encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if s.lower().startswith("#allow "):
                    allow.add(s[len("#allow ") :].strip().lower())
    return allow


def _main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Seed the local privacy denylist from source docs + run outputs.")
    ap.add_argument("--source", action="append", default=[], help="source root dir (repeatable)")
    ap.add_argument("--config", default=DEFAULT_SOURCES_CONFIG, help="git-ignored list of source roots")
    ap.add_argument("--denylist", default=DEFAULT_DENYLIST, help="denylist file to update")
    ap.add_argument("--dry-run", action="store_true", help="print, do not write")
    args = ap.parse_args(argv)

    roots = read_source_roots(args.source, args.config)
    if not roots:
        ap.error(f"no source roots — pass --source DIR or list them in {args.config}")
        return 2

    missing = [r for r in roots if not os.path.exists(r)]
    for r in missing:
        print(f"warning: source root does not exist: {r}", file=sys.stderr)

    auto_names, review_names, figures = harvest(roots, read_allowlist(args.config))
    existing = ""
    if os.path.isfile(args.denylist):
        with open(args.denylist, encoding="utf-8") as f:
            existing = f.read()
    merged = merge_denylist(existing, auto_names, figures, review_names)

    print(
        f"harvested: {len(auto_names)} auto names, {len(review_names)} review names, "
        f"{len(figures)} figure-spellings from {len(roots)} root(s)",
        file=sys.stderr,
    )
    if args.dry_run:
        sys.stdout.write(merged)
        return 0
    os.makedirs(os.path.dirname(args.denylist) or ".", exist_ok=True)
    with open(args.denylist, "w", encoding="utf-8") as f:
        f.write(merged)
    print(f"wrote {args.denylist}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(_main())
