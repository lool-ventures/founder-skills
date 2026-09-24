"""Founder-facing wording for the adversarial review's prose, shared by red_team.py and compose.

The red team writes `claim_attacked`, `what_is_true` and `source_title` as free text, and every word
of the first two is printed to the founder. It reads this run's own artifacts, so it names them the
way it read them: "sizing.json's entire bottom-up build", "validation.json figure_validations",
"arpu=$4,620". Left there, those words invite the analysis's MAIN THREAD to rewrite the review to
remove them -- measured, and with the findings' substance rewritten along with the file names.

So the wording is fixed where the review is produced, deterministically, before anyone else can
see it: nothing is left for the reviewed party to edit. The review's own quote (`evidence_quote`)
is never touched -- it is a quotation, and a quotation that has been reworded is a false one.

Skill scripts are standalone, so this module sits beside its two importers rather than in the
fleet's shared scripts dir.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

# Human-readable parameter names for report presentation
PARAM_LABELS: dict[str, str] = {
    "customer_count": "Customer Count",
    "arpu": "ARPU",
    "serviceable_pct": "Serviceable %",
    "target_pct": "Target Capture %",
    "industry_total": "Industry Total",
    "segment_pct": "Segment %",
    "share_pct": "Market Share %",
    "tam": "TAM",
    "sam": "SAM",
}

_FILE_EXTENSIONS = frozenset({"json", "py", "md", "html", "xlsx", "xls", "csv", "pdf", "docx", "pptx", "txt"})
_EMBEDDED_TOKEN_RE = re.compile(r"(?<![\w./-])[a-z][a-z0-9]*(?:_[a-z0-9]+)+(?:\.[a-z][a-z0-9_]*)*(?![\w/-])")


def humanize_param(name: str) -> str:
    """Convert a parameter name to human-readable label."""
    return PARAM_LABELS.get(name, name.replace("_", " ").title())


def humanize_claim(text: str) -> str:
    """Humanize a red-team `claim_attacked`, which is FREE TEXT and usually a sentence.

    `humanize_param` is built for snake_case parameter NAMES: its fallback is
    `.replace("_", " ").title()`, which on a sentence Title-Cases every word and mangles it --
    measured on a live run, "top-down SAM of $60M from a $3B TAM" came out as "Top-Down Sam Of
    $60M From A $3B Tam", downcasing two acronyms this skill is entirely about.

    So humanize only what is actually a parameter name: a known label, or a single bare
    snake_case token, or -- measured on a later run -- a token EMBEDDED in the prose: the verdict
    the founder read first said "existing_claims.tam = $3.2B", and the shared founder-text scan
    is blind to a dotted path by design (it skips `word.word` so URLs and filenames do not fire).
    Each embedded token becomes its label when it has one, else its words; the rest of the
    sentence is the agent's and is passed through untouched.
    """
    stripped = text.strip()
    if stripped in PARAM_LABELS:
        return PARAM_LABELS[stripped]
    if stripped and " " not in stripped and stripped.replace("_", "").isalnum():
        return humanize_param(stripped)

    def _one(m: re.Match[str]) -> str:
        tok = m.group(0)
        if tok in PARAM_LABELS:
            return PARAM_LABELS[tok]
        head, _, tail = tok.partition(".")
        if tok.rsplit(".", 1)[-1] in _FILE_EXTENSIONS:
            return tok  # a filename: the founder-text scan owns that case and names it
        if head == "existing_claims" and tail:
            return f"the {tail.upper()} your materials state"
        return tok.replace(".", " ").replace("_", " ")

    return _EMBEDDED_TOKEN_RE.sub(_one, stripped)


# --- the review's prose, rewritten once, at the producer ------------------------------------------

# A standalone noun phrase per artifact, so a possessive or a following word reads naturally:
# "sizing.json's entire bottom-up build" -> "the sizing calculation's entire bottom-up build".
INTERNAL_FILE_PHRASES: dict[str, str] = {
    "sizing.json": "the sizing calculation",
    "validation.json": "the source validation",
    "inputs.json": "the recorded inputs",
    "checklist.json": "the self-check",
    "sensitivity.json": "the sensitivity test",
    "methodology.json": "the method notes",
    "redteam.json": "this review",
}
_OTHER_FILE_PHRASE = "the analysis records"

# Words inside an identifier that are abbreviations a founder reads in capitals.
_WORD_MAP: dict[str, str] = {"arpu": "ARPU", "tam": "TAM", "sam": "SAM", "som": "SOM", "pppm": "PPPM"}
_PATH_WORDS: dict[str, str] = {
    "bottom_up": "bottom-up",
    "top_down": "top-down",
    "figure_validations": "figure checks",
    "figure_validation": "figure check",
}

# Left boundary excludes `-`, `.`, `/` and word characters: `founder-notes.md` and a path segment
# are not ours to rewrite.
_B_L = r"(?<![\w.\-/$])"
_FILE_RE = re.compile(_B_L + r"[a-z][a-z0-9_]*\.(?:json|py|md|html)(?![\w\-])")
# Our identifiers: snake_case with at least one underscore, optionally dotted, and -- measured --
# validation ids carry a `$` figure inside them (`arpu_founder_$203_pppm`, `founder_stated_tam_$12B`).
_IDENT_RE = re.compile(_B_L + r"[a-z][a-z0-9]*(?:_[A-Za-z0-9$]+)+(?:\.[a-z][a-z0-9_]*)*(?![\w\-/])")
# The one parameter with no underscore. Lowercase only: "ARPU" is the founder's word already.
_BARE_ARPU_RE = re.compile(_B_L + r"arpu(?![\w\-])")
_URL_RE = re.compile(r"https?://\S+")
_ABBREVIATIONS = frozenset({"vs.", "e.g.", "i.e.", "etc.", "approx.", "u.s.", "no."})


def _ident_words(tok: str) -> str:
    if tok in PARAM_LABELS:
        return PARAM_LABELS[tok]
    parts = [p for p in tok.split(".") if p]
    if parts and parts[-1] == "value":
        parts = parts[:-1]
    head, rest = parts[0], parts[1:]
    if head == "existing_claims" and rest:
        return f"the {rest[0].upper()} your materials state"
    if head == "existing_claims_detail":
        return "the figure your materials state"
    words: list[str] = []
    for p in parts:
        if p in PARAM_LABELS:
            words.append(PARAM_LABELS[p])
        elif p in _PATH_WORDS:
            words.append(_PATH_WORDS[p])
        else:
            words.append(" ".join(_WORD_MAP.get(w, w) for w in p.split("_") if w))
    return " ".join(words)


def humanize_review_text(text: str, protected: Iterable[str] = ()) -> tuple[str, int]:
    """Rewrite our file names and identifiers in one review field. Returns (text, replacements).

    `protected` is the founder's own document names: an uploaded `notes.md` is theirs, not ours.
    URL spans are left alone too. Deterministic, and applied to prose fields only.
    """
    keep = sorted({p for p in protected if p}, key=len, reverse=True)
    slots: list[str] = []

    def _mask(m: re.Match[str]) -> str:
        slots.append(m.group(0))
        return f"\x00{len(slots) - 1}\x00"

    masked = _URL_RE.sub(_mask, text)
    for name in keep:
        masked = re.sub(re.escape(name), _mask, masked)

    count = 0

    # A replacement that opens a sentence starts with a lowercase article; capitalise only OUR
    # replacements there -- never the author's own words, and never after "vs." or "e.g.".
    def _at_sentence_start(src: str, pos: int) -> bool:
        before = src[:pos]
        if not before.strip():
            return True
        m = re.search(r"(\S+)\s+$", before)
        return bool(m and m.group(1)[-1] in ".!?" and m.group(1).lower() not in _ABBREVIATIONS)

    def _emit(src: str, m: re.Match[str], phrase: str) -> str:
        nonlocal count
        count += 1
        return phrase[:1].upper() + phrase[1:] if _at_sentence_start(src, m.start()) else phrase

    out = _FILE_RE.sub(lambda m: _emit(masked, m, INTERNAL_FILE_PHRASES.get(m.group(0), _OTHER_FILE_PHRASE)), masked)
    out = _IDENT_RE.sub(lambda m: _emit(out, m, _ident_words(m.group(0))), out)
    out = _BARE_ARPU_RE.sub(lambda m: _emit(out, m, "ARPU"), out)
    out = re.sub(r"\x00(\d+)\x00", lambda m: slots[int(m.group(1))], out)
    return out, count
