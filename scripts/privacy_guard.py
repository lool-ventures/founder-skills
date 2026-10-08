#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""Privacy leak detector for commits / CI — without disclosing the names it guards.

Three layers, in order of value and precision:

  1. document  — a confidential-document file type (.xlsx/.pdf/.docx/…) tracked
                 anywhere outside a short, explicit allowlist of synthetic
                 fixtures. Catches real cap tables / term sheets dropped into the
                 repo. NAME-FREE — safe to run in CI.
  2. provenance — the "named-after-a-real-thing" anti-pattern in text:
                 "the Acmecorp P-1 failure", "the R-5 shape", round/case IDs.
                 NAME-FREE — safe to run in CI. (Conservative; bypass a false
                 positive with `git commit --no-verify`.)
  3. name      — an exact real company name from a LOCAL denylist file that is
                 never committed (lives in the already-git-ignored docs/internal/).
                 The detector logic ships in the repo; the names do NOT. CI has no
                 list, so layer 3 simply no-ops there.

Three more layers keep figures and quoted lines from private data out of ADDED text (staged lines,
commit messages, a push range). None of them discloses what it guards: findings print a path, a line
and the added token only, never which private file matched or any of its text.

  4. figure     — LOCAL ONLY. A figure token the change adds ($ amounts, thousands-separated numbers,
                  decimals, percentages, multiples, integers of 3+ digits) that also occurs in the
                  local private sources. Whole-token: 385 never matches inside 1385 or $3,850.
  5. verbatim   — LOCAL ONLY. A 6-word run of added text that also occurs in the private sources and
                  not in our own tracked code. A machine recording (RECORDING_PREFIXES) is matched
                  only against the founder-supplied DOCUMENTS among the sources (INPUT_DOC_EXTS, and
                  .md/.txt beside one): kept run transcripts and reports share the skills' own prose
                  with every recording, while a document quoted into a recording is the leak.
                  Layers 4-5 skip a file listed in GENERATED_FILES (generated from a scanned source and
                  held equal to it by a test).
  6. figure-provenance — everywhere. A figure token on a line that also says where real data came
                  from ("a live run", "the founder's", …). Blocking locally, warning-only in CI. A
                  reviewed line is accepted with the inline marker `privacy-guard: synthetic`.

The private sources are folders listed in a LOCAL, git-ignored file (default
docs/internal/privacy-private-sources.txt): one path per line, `#` comments, and `!<substring>` lines
that exclude any file whose path contains the substring (copies of our own code). Without that file
layers 4-5 skip silently, like layer 3 without its list. The index holds HASHES only and is cached
outside the repo (~/.cache/founder-skills/privacy-guard), rebuilt when a source file changes. False
alarms go in a LOCAL, git-ignored allowlist (docs/internal/privacy-figure-allowlist.txt, one figure
per line): a committed one would reveal that a public number equals a private one.

Usage:
  privacy_guard.py --staged              # staged files (layers 1-3) + staged ADDED lines (4-6)
  privacy_guard.py --commit-msg FILE     # a commit message (commit-msg hook; layers 3-6)
  privacy_guard.py --range A..B          # added lines + messages of a range (pre-push; layers 3-6)
  privacy_guard.py --tree                # scan all tracked files (CI; layers 1+2, layer 6 warn-only)
  privacy_guard.py FILE [FILE ...]       # scan specific files
  privacy_guard.py --staged --names-file docs/internal/privacy-denylist.txt
  privacy_guard.py --tree --no-names     # force-skip layer 3

Exit 0 = clean, 1 = findings (printed to stderr), 2 = usage error.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass, field

# Confidential document file types. .csv is intentionally excluded (commonly
# legitimate structured test data); add it here if that changes.
DOC_EXTS = {".xlsx", ".xls", ".pdf", ".docx", ".doc", ".pptx", ".ppt", ".numbers", ".key"}

# The ONLY document-type files allowed in the tracked tree — all synthetic
# fixtures. A new doc file must be added here deliberately (that is the point:
# it forces a conscious "is this synthetic?" decision at review time).
ALLOWLISTED_DOCS = frozenset(
    {
        "cowork-tests/fixtures/carta-folder/synthetic_carta.xlsx",
        "cowork-tests/fixtures/freeform_lane3.xlsx",
        "cowork-tests/fixtures/safe_cap_plus_discount.pdf",
        "cowork-tests/fixtures/sample_model.xlsx",
        "cowork-tests/fixtures/synthetic_carta.xlsx",
        "cowork-tests/fixtures/term_sheet_blank_exclusivity.pdf",
        "founder-skills/tests/fixtures/cap-table-corpus/synthetic_carta.xlsx",
        "founder-skills/tests/fixtures/sample_model.xlsx",
        # Two-page IMAGE-ONLY deck for fictional Foobar Fleet: synthetic text rendered to PNG and
        # wrapped back into a PDF, so the market-sizing OCR sidecar and document-citation checks
        # can be exercised on a page with no text layer. Regenerate rather than hand-edit.
        "founder-skills/tests/fixtures/market-sizing/synthetic-deck-scanned.pdf",
        # Landing-page capture fixtures. Fictional Acmecorp; generated by
        # tools/landing-capture/fixtures/build_xlsx.py, never hand-edited.
        "tools/landing-capture/fixtures/acmecorp-cap-table.xlsx",
        "tools/landing-capture/fixtures/acmecorp-model.xlsx",
    }
)

DEFAULT_NAMES_FILE = "docs/internal/privacy-denylist.txt"

# Layer-2 pattern (name-free, HIGH PRECISION — it gates commits, so generic
# English must not trip it). It catches the observed "named-after-an-unknown-
# company" leak shape: "the <ProperNoun> [P-1] failure/shape/…". The token after
# "the" must be a Capitalized proper noun (mid-sentence) — so "the same shape",
# "the bug shape", "the exact shape" do NOT match. A common false-friend
# (capitalized library/tool name) is bypassable with `git commit --no-verify`.
# Known real names are caught precisely by layer 3, so this is defense-in-depth
# for names not yet on the local list. Version/round-ID policing is deliberately
# out of scope here (a privacy guard, not a provenance linter).
_PROV_NOUN = r"(?:failure|shape|bug|incident|saga|episode|fiasco|debacle|case|deal)"
PROVENANCE_PATTERNS = [
    # The full antipattern triple is REQUIRED: <ProperNoun> + <round/case-ID> +
    # <failure-word>, e.g. "the Acmecorp P-1 failure". Requiring the ID is what
    # keeps "the Carta shape" / "the JSON shape" (proper noun, no ID) from
    # tripping it. Known names are caught precisely by layer 3 regardless.
    re.compile(rf"\bthe\s+[A-Z][A-Za-z]{{2,}}(?:[/-][A-Za-z]+)?\s+[PR]-\d{{1,3}}\s+{_PROV_NOUN}\b"),
]

# Files whose own job is to describe these patterns — exempt from layer 2 so the
# guard and its tests don't flag themselves.
_SELF_EXEMPT = {"scripts/privacy_guard.py", "scripts/test_privacy_guard.py"}

_TEXT_SKIP_EXTS = DOC_EXTS | {".png", ".jpg", ".jpeg", ".gif", ".woff", ".woff2", ".ttf", ".otf", ".ico", ".zip", ".gz"}


@dataclass
class Finding:
    path: str
    layer: str  # "document" | "provenance" | "name" | "figure" | "verbatim" | "figure-provenance"
    detail: str
    token: str = ""  # the ADDED token, never private text


def load_names(path: str) -> list[str]:
    """Load the local denylist (one name per line, # comments, blanks ignored).
    Missing file → empty list (so CI, which has no list, simply skips layer 3)."""
    if not os.path.isfile(path):
        return []
    names: list[str] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if s and not s.startswith("#"):
                names.append(s)
    return names


def _ext(path: str) -> str:
    return os.path.splitext(path)[1].lower()


def find_document_violations(paths: list[str]) -> list[Finding]:
    out = []
    for p in paths:
        if _ext(p) in DOC_EXTS and p not in ALLOWLISTED_DOCS:
            out.append(Finding(p, "document", f"confidential document type not in allowlist ({_ext(p)})"))
    return out


def find_provenance(path: str, text: str) -> list[Finding]:
    if path in _SELF_EXEMPT:
        return []
    out = []
    for pat in PROVENANCE_PATTERNS:
        m = pat.search(text)
        if m:
            out.append(Finding(path, "provenance", f"provenance/named-after tag: {m.group(0)!r}"))
            break
    return out


def find_names(path: str, text: str, names: list[str]) -> list[Finding]:
    if path in _SELF_EXEMPT or not names:
        return []
    low = text.lower()
    for name in names:
        # whole-word, case-insensitive
        if re.search(rf"(?<![\w]){re.escape(name.lower())}(?![\w])", low):
            out_detail = "matches a locally-denylisted real name"
            return [Finding(path, "name", out_detail)]
    return []


def scan_text_and_paths(paths: list[str], contents: dict[str, str], names: list[str]) -> list[Finding]:
    """Pure core: classify a set of paths + their text contents. `contents` maps
    path→text for text files (binary/doc files omitted)."""
    findings: list[Finding] = []
    findings.extend(find_document_violations(paths))
    for p in paths:
        # Layer 3 on the PATH too: a denylisted name in a file/dir name (a fixture
        # named after the real company) must be caught even with no matching text.
        # Normalize separators to spaces so path tokens are whole-word-bounded.
        path_tokens = re.sub(r"[/_.\-]+", " ", p)
        findings.extend(find_names(p, path_tokens, names))
        text = contents.get(p)
        if text is None:
            continue
        findings.extend(find_provenance(p, text))
        findings.extend(find_names(p, text, names))
    return findings


# ---------------------------------------------------------------------------
# Layers 4-6: figures, verbatim runs, figure + provenance phrase
# ---------------------------------------------------------------------------

DEFAULT_SOURCES_FILE = "docs/internal/privacy-private-sources.txt"
DEFAULT_ALLOWLIST_FILE = "docs/internal/privacy-figure-allowlist.txt"
DEFAULT_CACHE_DIR = os.path.join(os.path.expanduser("~"), ".cache", "founder-skills", "privacy-guard")
SYNTHETIC_MARKER = "privacy-guard: synthetic"
NGRAM = 6
# Bump when what the index holds changes, so a cached index built by older logic is never reused.
INDEX_VERSION = "3"
# Machine-generated recordings of synthetic runs: their timings, byte and token counts collide with
# private figures by chance, and they narrate those runs in the skills' own words ("the founder's",
# "the deck's"), so the figure and figure-provenance layers skip them. Verbatim and names still scan
# them; verbatim against the documents-only gram set (see INPUT_DOC_EXTS), because the same skill
# prose sits in every kept run transcript and report, while a founder document quoted into a
# recording is the leak the layer exists for there.
RECORDING_PREFIXES = ("cowork-tests/cassettes/",)
# Founder-supplied documents among the private sources: their grams form `grams_inputs`. Kept apart
# from layer 1's DOC_EXTS (which governs files tracked in the repo, and has no .csv).
INPUT_DOC_EXTS = frozenset({".pdf", ".csv", ".docx", ".pptx", ".xlsx"})
# A .md/.txt is an input only when its OWN directory holds an INPUT_DOC_EXTS file and its lowercased
# basename carries none of these: they are our skills' own output names (reports, hand-offs, run
# records), which a run writes beside the founder's document.
OUTPUT_NAME_MARKERS = (
    "report", "coaching", "checklist", "slide_review", "compose", "handoff", "sizing", "validation",
    "ledger", "reconcil", "stage_profile", "explorer", "events", "transcript", "result", "session",
    "run_status", "gates", "prompt", "dispatch", "redteam", "receipt", "inputs", "instruments",
    "scenario", "sweep", "counsel", "cap_state", "model_data", "runway", "unit_economics", "landscape",
    "moat", "positioning", "verification", "research", "sensitivity", "fund_profile", "conflicts",
    "score_dimensions",
)  # fmt: skip
_OOXML_EXTS = frozenset({".docx", ".pptx", ".xlsx"})
_LEGACY_OFFICE_EXTS = frozenset({".xls", ".doc", ".ppt"})
# Files generated from a tracked source, each held equal to it by a test. Their figures and text come
# only from that source, which every layer scans, so the figure and verbatim layers skip the generated
# copy: its layout puts our own words beside key names ("label", "question") in runs a founder's form
# reply also produced, which the verbatim layer cannot tell from a leak. Every other layer still scans it.
# Each entry: generated file -> (its source, the test that fails when they differ).
GENERATED_FILES = {
    "founder-skills/data/host-contract.json": (
        "founder-skills/scripts/_gates.py",
        "founder-skills/tests/test_gate_registry.py",
    ),
}

# A figure token. The look-arounds make it WHOLE-TOKEN: no digit, letter, `.`, `,` or `$` may touch
# either side, so 385 is not found inside 1385, $3,850, 2.1.385 or 0x385.
_FIGURE_RE = re.compile(
    r"(?<![\w.,$-])"
    r"(\$\s?\d{1,3}(?:,\d{3})+(?:\.\d+)?|\$\s?\d+(?:\.\d+)?"  # $ amounts
    r"|\d{1,3}(?:,\d{3})+(?:\.\d+)?"  # thousands-separated
    r"|\d+\.\d+"  # decimals
    r"|\d{3,})"  # integers of 3+ digits
    r"([%x]|[kKmMbB](?![a-zA-Z]))?"  # percent / multiple / scale suffix
    r"(?![\w]|[.,]\d|-\w)"
)
_SMALL_PCT_OR_MULT = re.compile(r"(?<![\w.,$-])(\d{1,2})([%x])(?![\w]|[.,]\d)")

# Values too common to mean anything. Keep this list MINIMAL: every entry is a figure the guard can
# no longer see. Years 1900-2100 are skipped by rule, not listed.
GENERIC_FIGURES = frozenset({"100", "1000", "10000", "100000", "1000000", "0.5", "10%", "25%", "50%", "100%"})


def _norm_figure(raw: str, suffix: str | None) -> str:
    core = re.sub(r"[$,\s]", "", raw)
    return core + (suffix.lower() if suffix else "")


def extract_figures(text: str) -> list[tuple[str, str]]:
    """(normalised, raw) figure tokens in `text`, generic values dropped."""
    out: list[tuple[str, str]] = []
    for m in list(_FIGURE_RE.finditer(text)) + list(_SMALL_PCT_OR_MULT.finditer(text)):
        raw, suffix = m.group(1), m.group(2)
        norm = _norm_figure(raw, suffix)
        digits = re.sub(r"\D", "", raw)
        plain = not suffix and "." not in raw and "," not in raw and "$" not in raw
        if plain and len(digits) == 4 and 1900 <= int(digits) <= 2100:
            continue  # a year
        if norm in GENERIC_FIGURES:
            continue
        out.append((norm, m.group(0)))
    return out


def _words(text: str) -> list[str]:
    toks = re.findall(r"[A-Za-z0-9$%.\-']+", text.lower())
    return [t.strip(".'-") for t in toks if t.strip(".'-")]


_JSON_U_ESCAPE = re.compile(r"\\u([0-9a-fA-F]{4})")
_JSON_WS_ESCAPE = re.compile(r"\\[nrtbf]")
_JSON_CHAR_ESCAPE = re.compile(r'\\(["\\/])')


def _unescape_json(text: str, passes: int = 3) -> str:
    """Decode JSON string escapes in a recording line, to a fixed point (at most `passes`: a cassette's
    events are JSON strings inside JSON, so a line break can arrive escaped twice). A document carries no
    escapes, so without this a line break it had becomes `\\n` + word, one token, and the 6-word run the
    document holds across that break is never seen. Whitespace escapes become a space."""
    for _ in range(passes):
        nxt = _JSON_U_ESCAPE.sub(lambda m: chr(int(m.group(1), 16)), text)
        nxt = _JSON_WS_ESCAPE.sub(" ", nxt)
        nxt = _JSON_CHAR_ESCAPE.sub(r"\1", nxt)
        if nxt == text:
            break
        text = nxt
    return text


def _h(value: str) -> str:
    return hashlib.blake2b(value.encode("utf-8"), digest_size=10).hexdigest()


def _grams(words: list[str]) -> Iterable[str]:
    for i in range(len(words) - NGRAM + 1):
        yield " ".join(words[i : i + NGRAM])


@dataclass
class SourcesSpec:
    roots: list[str]
    excludes: list[str]
    config_text: str


@dataclass
class PrivateIndex:
    figures: set[str] = field(default_factory=set)  # hashes of normalised figures
    grams: set[str] = field(default_factory=set)  # hashes of 6-word runs, our own code's removed
    grams_inputs: set[str] = field(default_factory=set)  # the same, from founder documents only
    allow: set[str] = field(default_factory=set)  # normalised figures accepted locally


def load_sources(path: str) -> SourcesSpec | None:
    """The local sources file, or None when it is absent (layers 4-5 then skip silently)."""
    if not os.path.isfile(path):
        return None
    roots: list[str] = []
    excludes: list[str] = []
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if s.startswith("!"):
            excludes.append(s[1:].strip())
        else:
            roots.append(os.path.expanduser(s))
    return SourcesSpec(roots, excludes, text)


_BINARY_EXTS = _TEXT_SKIP_EXTS - {".pdf"} - _OOXML_EXTS


def _walk_sources(spec: SourcesSpec) -> list[str]:
    files: list[str] = []
    for root in spec.roots:
        for dirpath, _dirs, names in os.walk(root):
            for n in names:
                fp = os.path.join(dirpath, n)
                if not any(ex in fp for ex in spec.excludes):
                    files.append(fp)
    return sorted(files)


def _source_files(spec: SourcesSpec, notes: list[str] | None = None) -> list[str]:
    """Every readable source file (text, PDF, .docx/.pptx/.xlsx). Binary office formats with no stdlib
    reader are dropped, and counted into `notes` (never named: a note prints, a path could disclose)."""
    files: list[str] = []
    legacy: dict[str, int] = {}
    for fp in _walk_sources(spec):
        e = _ext(fp)
        if e in _LEGACY_OFFICE_EXTS:
            legacy[e] = legacy.get(e, 0) + 1
            continue
        if e in _BINARY_EXTS:
            continue
        files.append(fp)
    if legacy and notes is not None:
        counts = ", ".join(f"{n} {e}" for e, n in sorted(legacy.items()))
        notes.append(f"privacy-guard: {counts} source file(s) skipped (binary office format, no stdlib reader)")
    return files


def _input_files(files: list[str]) -> set[str]:
    """The founder-supplied documents among `files`: INPUT_DOC_EXTS anywhere, and a .md/.txt whose own
    directory holds one and whose name carries no OUTPUT_NAME_MARKERS."""
    doc_dirs = {os.path.dirname(fp) for fp in files if _ext(fp) in INPUT_DOC_EXTS}
    out: set[str] = set()
    for fp in files:
        e, base = _ext(fp), os.path.basename(fp).lower()
        if e in INPUT_DOC_EXTS or (
            e in {".md", ".txt"} and os.path.dirname(fp) in doc_dirs and not any(m in base for m in OUTPUT_NAME_MARKERS)
        ):
            out.add(fp)
    return out


_OOXML_MAX_PART = 50_000_000


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _paragraph_texts(root: ET.Element) -> list[str]:
    """docx/pptx: each paragraph's runs joined with no separator (a word can be split across runs)."""
    out = []
    for el in root.iter():
        if _local(el.tag) == "p":
            out.append("".join(t.text or "" for t in el.iter() if _local(t.tag) == "t"))
    return out


def _xlsx_texts(zf: zipfile.ZipFile, parts: list[str]) -> list[str]:
    """Cells in sheet and row order. A shared-string cell's `v` is an index into the string table, so it
    is resolved, never read as a value (it would add a spurious number to the index)."""
    shared: list[str] = []
    if "xl/sharedStrings.xml" in parts:
        sst = ET.fromstring(zf.read("xl/sharedStrings.xml"))
        shared = [
            "".join(t.text or "" for t in si.iter() if _local(t.tag) == "t") for si in sst if _local(si.tag) == "si"
        ]
    out: list[str] = []
    for part in parts:
        if not (part.startswith("xl/worksheets/") and part.endswith(".xml")):
            continue
        for row in ET.fromstring(zf.read(part)).iter():
            if _local(row.tag) != "row":
                continue
            cells = []
            for c in row:
                if _local(c.tag) != "c":
                    continue
                kind = c.get("t")
                if kind == "inlineStr":
                    cells.append("".join(t.text or "" for t in c.iter() if _local(t.tag) == "t"))
                    continue
                v = next((x.text for x in c if _local(x.tag) == "v"), None)
                if v is None:
                    continue
                if kind == "s":
                    i = int(v) if v.strip().isdigit() else -1
                    cells.append(shared[i] if 0 <= i < len(shared) else "")
                else:
                    cells.append(v)
            out.append(" ".join(cells))
    return out


_OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


def _ooxml_text(fp: str) -> str | None:
    """Text of a .docx/.pptx/.xlsx with the stdlib only; None when it cannot be read (encrypted: a
    password-protected OOXML file is an OLE container; corrupt; truncated). These are untrusted bytes, so
    any exception means "unreadable" and is counted by the caller, never raised and never silent."""

    def order(name: str) -> tuple[str, int]:
        m = re.search(r"(\d+)\.xml$", name)
        return (re.sub(r"\d+\.xml$", "", name), int(m.group(1)) if m else 0)

    try:
        with open(fp, "rb") as fh:
            if fh.read(8) == _OLE_MAGIC:
                return None
        with zipfile.ZipFile(fp) as zf:
            infos = [i for i in zf.infolist() if i.file_size <= _OOXML_MAX_PART]
            parts = sorted((i.filename for i in infos), key=order)
            e = _ext(fp)
            if e == ".xlsx":
                return "\n".join(_xlsx_texts(zf, parts))
            if e == ".docx":
                wanted = [
                    p
                    for p in parts
                    if re.match(r"word/(document|header\d*|footer\d*|footnotes|endnotes|comments)\.xml$", p)
                ]
            else:
                wanted = [p for p in parts if re.match(r"ppt/(slides/slide|notesSlides/notesSlide)\d+\.xml$", p)]
            out: list[str] = []
            for part in wanted:
                out.extend(_paragraph_texts(ET.fromstring(zf.read(part))))
            return "\n".join(out)
    except Exception:  # zlib.error, RuntimeError (encrypted entry), BadZipFile, ParseError, EOFError, ...
        return None


def _source_text(fp: str, notes: list[str], unreadable: dict[str, int] | None = None) -> str:
    if _ext(fp) in _OOXML_EXTS:
        text = _ooxml_text(fp)
        if text is None:
            if unreadable is not None:
                unreadable[_ext(fp)] = unreadable.get(_ext(fp), 0) + 1
            return ""
        return text
    if _ext(fp) == ".pdf":
        if not shutil.which("pdftotext"):
            if "pdftotext" not in " ".join(notes):
                notes.append("privacy-guard: pdftotext not found; PDF sources skipped")
            return ""
        out = subprocess.run(["pdftotext", "-q", fp, "-"], capture_output=True, text=True)
        return out.stdout
    try:
        if os.path.getsize(fp) > 20_000_000:
            return ""
        with open(fp, encoding="utf-8") as f:
            return f.read()
    except (OSError, UnicodeDecodeError):
        return ""


def _own_code_texts() -> Iterable[str]:
    """Our tracked files at origin/main: figures and 6-word runs found there are ours, not private.
    Read in ONE `git cat-file --batch` stream; a subprocess per file is minutes on this repo."""
    # Only the PUBLISHED tree counts as ours. Falling back to HEAD would let a leak already committed
    # locally subtract itself out of the index, so with no origin/main nothing is subtracted.
    ref = "origin/main"
    if subprocess.run(["git", "rev-parse", "--verify", "-q", ref], capture_output=True).returncode != 0:
        return
    listing = subprocess.run(["git", "ls-tree", "-r", "-z", ref], capture_output=True, text=True).stdout
    shas = []
    for entry in listing.split("\0"):
        if not entry or "\t" not in entry:
            continue
        meta, name = entry.split("\t", 1)
        parts = meta.split()
        if len(parts) == 3 and parts[1] == "blob" and _ext(name) not in _TEXT_SKIP_EXTS:
            shas.append(parts[2])
    proc = subprocess.run(["git", "cat-file", "--batch"], input=("\n".join(shas) + "\n").encode(), capture_output=True)
    buf, pos = proc.stdout, 0
    while pos < len(buf):
        nl = buf.index(b"\n", pos)
        header = buf[pos:nl].split()
        pos = nl + 1
        if len(header) < 3 or header[1] != b"blob":
            continue
        size = int(header[2])
        body, pos = buf[pos : pos + size], pos + size + 1
        try:
            yield body.decode("utf-8")
        except UnicodeDecodeError:
            continue


def _pdftotext_id() -> str:
    """Absent, or its path and version banner: part of the index cache key."""
    path = shutil.which("pdftotext")
    if not path:
        return "absent"
    try:
        r = subprocess.run([path, "-v"], capture_output=True, text=True, timeout=10)
        banner = (r.stderr or r.stdout).strip().splitlines()[:1]
    except (OSError, subprocess.SubprocessError):
        banner = []
    return path + "|" + (banner[0] if banner else "")


def _own_tree_id() -> str:
    r = subprocess.run(["git", "rev-parse", "-q", "origin/main^{tree}"], capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else "none"


def build_private_index(
    spec: SourcesSpec,
    own_code_texts: Iterable[str] | None = None,
    cache_dir: str = DEFAULT_CACHE_DIR,
    allowlist_path: str = DEFAULT_ALLOWLIST_FILE,
) -> PrivateIndex:
    """Hashes of every figure and 6-word run in the private sources, minus our own code's runs, and the
    6-word runs of the founder documents among them (`grams_inputs`, see INPUT_DOC_EXTS).

    One walk, one read per file, one cache file holding both gram sets (hashes only) outside the repo;
    the key covers the sources config, every source file's path/size/mtime (which also fixes which files
    are documents) and, when our own code is read from git, the tree it came from."""
    notes: list[str] = []
    files = _source_files(spec, notes)
    inputs = _input_files(files)
    sig = hashlib.sha256()
    sig.update(INDEX_VERSION.encode())
    sig.update(spec.config_text.encode())
    # What can be read, and which files are documents, both change the gram sets without touching a file:
    # a PDF-less index built without pdftotext must not be reused once it is installed, and an edit to
    # INPUT_DOC_EXTS / OUTPUT_NAME_MARKERS must not reuse a cache split under the old rule.
    sig.update(f"pdftotext={_pdftotext_id()}\0".encode())
    sig.update(("inputs:" + "\0".join(sorted(inputs)) + "\0").encode())
    for fp in files:
        st = os.stat(fp)
        sig.update(f"{fp}\0{st.st_size}\0{st.st_mtime_ns}\0".encode())
    own_given = own_code_texts is not None
    sig.update((("given:" + _h("\0".join(own_code_texts or []))) if own_given else _own_tree_id()).encode())
    key = sig.hexdigest()[:24]
    cache = os.path.join(cache_dir, f"index-{key}.json")
    idx = PrivateIndex()
    if os.path.isfile(cache):
        with open(cache, encoding="utf-8") as fh:
            data = json.load(fh)
        idx.figures, idx.grams = set(data["figures"]), set(data["grams"])
        idx.grams_inputs = set(data["grams_inputs"])
    else:
        unreadable: dict[str, int] = {}
        for fp in files:
            text = _source_text(fp, notes, unreadable)
            if not text:
                continue
            for norm, _raw in extract_figures(text):
                idx.figures.add(_h(norm))
            hashed = {_h(g) for g in _grams(_words(text))}
            idx.grams.update(hashed)
            if fp in inputs:
                idx.grams_inputs.update(hashed)
        if unreadable:
            counts = ", ".join(f"{n} {e}" for e, n in sorted(unreadable.items()))
            notes.append(f"privacy-guard: {counts} source file(s) unreadable (encrypted or corrupt); not indexed")
        # Our own code is public: a figure or a 6-word run that also occurs there is not a leak signal.
        own_texts: Iterable[str] = own_code_texts if own_code_texts is not None else _own_code_texts()
        for own in own_texts:
            if idx.grams:
                own_grams = {_h(g) for g in _grams(_words(own or ""))}
                idx.grams.difference_update(own_grams)
                idx.grams_inputs.difference_update(own_grams)
            if idx.figures:
                idx.figures.difference_update(_h(n) for n, _ in extract_figures(own or ""))
        os.makedirs(cache_dir, exist_ok=True)
        with open(cache, "w", encoding="utf-8") as f:
            json.dump(
                {"figures": sorted(idx.figures), "grams": sorted(idx.grams), "grams_inputs": sorted(idx.grams_inputs)},
                f,
            )
    for note in notes:
        print(note, file=sys.stderr)
    if os.path.isfile(allowlist_path):
        with open(allowlist_path, encoding="utf-8") as fh:
            for line in fh:
                entry = line.strip()
                if entry and not entry.startswith("#"):
                    idx.allow.update(n for n, _ in extract_figures(entry))
    return idx


def find_figure_leaks(path: str, lines: list[tuple[int, str]], idx: PrivateIndex) -> list[Finding]:
    out = []
    for lineno, text in lines:
        for norm, raw in extract_figures(text):
            if norm not in idx.allow and _h(norm) in idx.figures:
                out.append(Finding(f"{path}:{lineno}", "figure", "matches a figure in local private sources", raw))
    return out


def _is_line_numbering(words: list[str]) -> bool:
    """Six 1-2 digit integers each one more than the last: the `cat -n` / line-number shape a recording's
    tool results carry once its `\\n` escapes are decoded, and a numbered column in a spreadsheet. It is
    the only all-integer shape that collided (2 grams, one staged cassette line); any other run of small
    integers still matches."""
    if not all(w.isdigit() and len(w) <= 2 for w in words):
        return False
    nums = [int(w) for w in words]
    return all(nums[i + 1] == nums[i] + 1 for i in range(len(nums) - 1))


def is_recording(path: str) -> bool:
    """A cassette file under RECORDING_PREFIXES. Any other file placed there is hand-written: every
    consumer globs `*.cassette.json`, so the suffix is what makes a file a recording."""
    return path.startswith(RECORDING_PREFIXES) and path.endswith(".cassette.json")


def find_verbatim_leaks(
    path: str, lines: list[tuple[int, str]], idx: PrivateIndex, all_sources: bool = False
) -> list[Finding]:
    """A 6-word run of the added text found in the private sources. Runs may span added lines of one file.

    A recording is matched against the founder documents only (`grams_inputs`), its JSON escapes decoded
    first; `all_sources=True` matches it against every source instead (the triage count, never a gate)."""
    out = []
    recording = is_recording(path) and not all_sources
    grams = idx.grams_inputs if recording else idx.grams
    flat: list[tuple[int, str]] = [
        (n, w) for n, text in lines for w in _words(_unescape_json(text) if recording else text)
    ]
    seen_lines: set[int] = set()
    for i in range(len(flat) - NGRAM + 1):
        gram = " ".join(w for _, w in flat[i : i + NGRAM])
        lineno = flat[i][0]
        if recording and _is_line_numbering([w for _, w in flat[i : i + NGRAM]]):
            continue  # line numbering: no text to leak
        if lineno not in seen_lines and _h(gram) in grams:
            seen_lines.add(lineno)
            out.append(Finding(f"{path}:{lineno}", "verbatim", "a 6-word run matches text in local private sources"))
    return out


_PROVENANCE_PHRASES = re.compile(
    r"\b(?:a\s+live\s+(?:run|report)|live\s+run|real\s+run|the\s+real\b|in\s+production\b"
    r"|the\s+founder'?s\b|the\s+deck'?s\b|from\s+the\s+data\s+room)",
    re.IGNORECASE,
)


def find_figure_provenance(path: str, lines: list[tuple[int, str]]) -> list[Finding]:
    if path in _SELF_EXEMPT or is_recording(path):
        return []
    out = []
    for lineno, text in lines:
        if SYNTHETIC_MARKER in text or not _PROVENANCE_PHRASES.search(text):
            continue
        figs = extract_figures(text)
        if figs:
            out.append(
                Finding(f"{path}:{lineno}", "figure-provenance", "a figure beside a real-data phrase", figs[0][1])
            )
    return out


def added_lines_from_diff(diff: str) -> dict[str, list[tuple[int, str]]]:
    """{path: [(new line number, text)]} for the ADDED lines of a `git diff -U0` patch."""
    out: dict[str, list[tuple[int, str]]] = {}
    path: str | None = None
    lineno = 0
    for line in diff.splitlines():
        if line.startswith("+++ "):
            target = line[4:]
            path = None if target == "/dev/null" else target[2:] if target.startswith("b/") else target
            continue
        if line.startswith("@@"):
            m = re.search(r"\+(\d+)", line)
            lineno = int(m.group(1)) if m else 0
            continue
        if path is None or line.startswith("---"):
            continue
        if line.startswith("+"):
            out.setdefault(path, []).append((lineno, line[1:]))
            lineno += 1
        elif line.startswith(" "):
            lineno += 1
    return out


def scan_added(
    added: dict[str, list[tuple[int, str]]],
    idx: PrivateIndex | None,
    names: list[str],
) -> list[Finding]:
    """Layers 3-6 over added text (files, or a commit message under a pseudo-path)."""
    findings: list[Finding] = []
    for path, lines in added.items():
        if idx is not None and path not in _SELF_EXEMPT and path not in GENERATED_FILES:
            if not is_recording(path):
                findings.extend(find_figure_leaks(path, lines, idx))
            findings.extend(find_verbatim_leaks(path, lines, idx))
        findings.extend(find_figure_provenance(path, lines))
        if names:
            findings.extend(find_names(path, "\n".join(t for _, t in lines), names))
    return findings


def _message_lines(text: str) -> list[tuple[int, str]]:
    return [(i, ln) for i, ln in enumerate(text.splitlines(), 1) if not ln.startswith("#")]


def _read_text(path: str) -> str | None:
    if _ext(path) in _TEXT_SKIP_EXTS:
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except (OSError, UnicodeDecodeError):
        return None


def _git_files(staged: bool) -> list[str]:
    cmd = ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"] if staged else ["git", "ls-files"]
    out = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
    return [line for line in out.splitlines() if line]


def scan(paths: list[str], names: list[str]) -> list[Finding]:
    contents = {p: t for p in paths if (t := _read_text(p)) is not None}
    return scan_text_and_paths(paths, contents, names)


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout


def _report(findings: list[Finding], warn_layers: set[str]) -> int:
    blocking = [f for f in findings if f.layer not in warn_layers]
    warnings = [f for f in findings if f.layer in warn_layers]
    for f in warnings:
        tok = f"  ({f.token})" if f.token else ""
        print(f"  warning [{f.layer}] {f.path}{tok}: {f.detail}", file=sys.stderr)
    if blocking:
        print("✗ privacy-guard: potential leak(s) detected:\n", file=sys.stderr)
        for f in blocking:
            tok = f"  ({f.token})" if f.token else ""
            print(f"  [{f.layer:<10}] {f.path}{tok}\n               {f.detail}", file=sys.stderr)
        print(
            "\nFix the text, mark a reviewed synthetic line with `privacy-guard: synthetic`, add a local false "
            "alarm to the git-ignored figure allowlist, or — as a last resort — bypass with `--no-verify`.",
            file=sys.stderr,
        )
        return 1
    return 0


def _verbatim_report(added: dict[str, list[tuple[int, str]]], idx: PrivateIndex | None) -> int:
    """Verbatim finding COUNTS per file, largest first, for triage. Never prints text.

    A recording's row is `<blocking count>  <path>  (all sources: <count>)`: the first number is what
    the gate sees (founder documents only), the second keeps the collision with kept runs measured."""
    if idx is None:
        print("privacy-guard: no local private-sources file; nothing to report", file=sys.stderr)
        return 0
    rows: list[tuple[int, str, int | None]] = []
    for p, lines in added.items():
        if p in _SELF_EXEMPT or p in GENERATED_FILES:
            continue
        n = len(find_verbatim_leaks(p, lines, idx))
        n_all = len(find_verbatim_leaks(p, lines, idx, all_sources=True)) if is_recording(p) else None
        if n or n_all:
            rows.append((n, p, n_all))
    rows.sort(key=lambda r: (-r[0], -(r[2] or 0), r[1]))
    for n, p, n_all in rows:
        print(f"{n:6d}  {p}" + (f"  (all sources: {n_all})" if n_all is not None else ""))
    print(f"total {sum(n for n, _, _ in rows)} in {sum(1 for r in rows if r[0])} file(s)")
    return 0


def _main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Privacy leak detector (pre-commit / commit-msg / pre-push / CI).")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--staged", action="store_true", help="scan git-staged files and their added lines")
    g.add_argument("--tree", action="store_true", help="scan all tracked files")
    g.add_argument("--commit-msg", metavar="FILE", help="scan a commit message file")
    g.add_argument("--range", metavar="REVS", help="scan added lines + commit messages of a rev range")
    ap.add_argument("files", nargs="*", help="explicit files to scan")
    ap.add_argument("--names-file", default=DEFAULT_NAMES_FILE, help="local denylist path")
    ap.add_argument("--no-names", action="store_true", help="skip layer 3 (name list)")
    ap.add_argument("--sources-file", default=DEFAULT_SOURCES_FILE, help="local private-sources list")
    ap.add_argument("--allowlist-file", default=DEFAULT_ALLOWLIST_FILE, help="local figure allowlist")
    ap.add_argument("--cache-dir", default=DEFAULT_CACHE_DIR, help="where the hashed index is cached")
    ap.add_argument("--provenance-warn-only", action="store_true", help="report figure-provenance as warnings")
    ap.add_argument(
        "--verbatim-report",
        action="store_true",
        help="with --range/--staged: print verbatim finding COUNTS per file (no text), exit 0",
    )
    args = ap.parse_args(argv)

    names = [] if args.no_names else load_names(args.names_file)
    warn_layers = {"figure-provenance"} if (args.tree or args.provenance_warn_only) else set()

    def index() -> PrivateIndex | None:
        spec = load_sources(args.sources_file)
        return None if spec is None else build_private_index(spec, None, args.cache_dir, args.allowlist_file)

    if args.commit_msg:
        with open(args.commit_msg, encoding="utf-8") as fh:
            text = fh.read()
        return _report(scan_added({"commit message": _message_lines(text)}, index(), names), warn_layers)

    if args.range:
        added = added_lines_from_diff(_git("diff", "-U0", "--no-color", "--no-ext-diff", args.range))
        for sha in _git("rev-list", args.range).split():
            added[f"commit message {sha[:10]}"] = _message_lines(_git("log", "-1", "--format=%B", sha))
        if args.verbatim_report:
            return _verbatim_report(added, index())
        return _report(scan_added(added, index(), names), warn_layers)

    if args.staged or args.tree:
        paths = _git_files(staged=args.staged)
    elif args.files:
        paths = args.files
    else:
        ap.error("provide --staged, --tree, --commit-msg, --range, or explicit files")
        return 2

    if args.staged and args.verbatim_report:
        return _verbatim_report(
            added_lines_from_diff(_git("diff", "--cached", "-U0", "--no-color", "--no-ext-diff")), index()
        )
    findings = scan(paths, names)
    if args.staged:
        added = added_lines_from_diff(_git("diff", "--cached", "-U0", "--no-color", "--no-ext-diff"))
        findings.extend(f for f in scan_added(added, index(), []) if f.layer != "name")
    else:
        # --tree / explicit files: layer 6 over whole files; layers 4-5 are for ADDED text only.
        for p in paths:
            body = _read_text(p)
            if body is not None:
                findings.extend(find_figure_provenance(p, list(enumerate(body.splitlines(), 1))))
    return _report(findings, warn_layers)


if __name__ == "__main__":
    sys.exit(_main())
