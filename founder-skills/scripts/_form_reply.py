"""Read a founder's reply to a Desktop question form into gate answers.

On Desktop a first question can be steered to a form, whose answer arrives as the founder's next plain
message: `<header> — Label: value · Label: value`, sometimes with a `--- Full content ---` section
carrying values the first line folded. The shapes here come from synthetic fixtures; no live reply has
been captured. So the reader ships switched off (`FORM_REPLY_ENABLED = False`) and the recorder refuses
`--form-reply` with "ask with AskUserQuestion" until a captured reply proves the shape.

Matching is against the labels the form was built from, never a blind split: a value may itself contain
`·` or `:`. All or nothing: an unmatched key or value refuses with the allowed labels.

Pure: no I/O. Loaded by a hook (`asked_gate_check.py`), so Python 3.9-clean: no `match`, no runtime
`X | Y`.
"""

from __future__ import annotations

import difflib
import re
from collections.abc import Sequence
from typing import NamedTuple

FORM_REPLY_ENABLED = False

# The Skip line Desktop sends when the founder skips the form (`two_figures_check.SKIP_LINE`).
SKIP_LINE = "(Skipped the form — proceed with defaults or ask me in plain text)"
FULL_CONTENT = "--- Full content ---"

_UPLOADS_RE = re.compile(r"\A\s*<uploaded_files>.*?</uploaded_files>\s*", re.DOTALL)
_DASHES = "—–-"
_QUOTE_PAIRS = (('"', '"'), ("“", "”"), ("'", "'"), ("‘", "’"))

# (option id, label, takes_value)
Option = tuple[str, str, bool]


class Field(NamedTuple):
    gate_key: str
    form_label: str
    options: Sequence[Option]
    multi: bool


class Parsed(NamedTuple):
    skipped: bool
    # (gate key, option ids, value or None)
    answers: list[tuple[str, list[str], str | None]]


class FormReplyError(Exception):
    def __init__(self, code: str, message: str, allowed: dict | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.allowed = allowed or {}


def normalise(text: str) -> str:
    """Whitespace squashed, dashes and quotes unified, case folded."""
    t = text
    for d in "—–‒−":
        t = t.replace(d, "-")
    for q in "“”„″":
        t = t.replace(q, '"')
    for q in "‘’′":
        t = t.replace(q, "'")
    return re.sub(r"\s+", " ", t).strip().casefold()


def _unquote(value: str) -> str:
    v = value.strip()
    for open_q, close_q in _QUOTE_PAIRS:
        if len(v) >= 2 and v.startswith(open_q) and v.endswith(close_q):
            return v[1:-1].strip()
    return v


def _strip_header(line: str, header: str) -> str | None:
    for head in (header + " details", header):
        if line.startswith(head):
            rest = line[len(head) :]
            m = re.match(r"^ [" + _DASHES + r"] ", rest)
            if m:
                return rest[m.end() :]
    return None


# The reply's header test, for a check that only asks whether a message answers a form.
strip_header = _strip_header


def _split_by_labels(body: str, labels: Sequence[str], *, line_start_only: bool) -> list[tuple[str, str]]:
    """(label, raw value) pairs, each value running to the next known label."""
    alternation = "|".join(re.escape(lab) for lab in sorted(labels, key=len, reverse=True))
    if line_start_only:
        pattern = re.compile(r"(?m)^(" + alternation + r"):[ \t]*")
    else:
        pattern = re.compile(r"(?:^|(?<= · ))(" + alternation + r"):[ \t]*")
    hits = list(pattern.finditer(body))
    out: list[tuple[str, str]] = []
    for i, m in enumerate(hits):
        end = hits[i + 1].start() if i + 1 < len(hits) else len(body)
        value = body[m.end() : end].strip()
        if not line_start_only and value.endswith(" ·"):
            value = value[:-2].rstrip()
        elif not line_start_only and value.endswith("·"):
            value = value[:-1].rstrip()
        out.append((m.group(1), value))
    return out


def _close(a: str, b: str) -> bool:
    """Near enough to be a mistyped or trimmed label rather than a stated value."""
    if not a or not b:
        return False
    if min(len(a), len(b)) >= 4 and (a in b or b in a):
        return True
    return difflib.SequenceMatcher(None, a, b).ratio() >= 0.8


def _match(field: Field, raw: str) -> tuple[list[str], str | None]:
    value = _unquote(raw)
    want = normalise(value)
    for oid, label, _takes in field.options:
        if normalise(label) == want:
            return [oid], None
    if field.multi:
        parts = [normalise(p) for p in value.split(", ")]
        by_label = {normalise(lab): oid for oid, lab, _t in field.options}
        if parts and all(p in by_label for p in parts):
            return [by_label[p] for p in parts], None
    takes = [(oid, lab) for oid, lab, t in field.options if t]
    if len(takes) == 1:
        # Free text goes to the one value option only when it is not a near-miss of another choice: a
        # garbled "No option pol" is that choice mistyped, not a value someone stated.
        near = [lab for oid, lab, t in field.options if not t and _close(want, normalise(lab))]
        if near:
            raise FormReplyError(
                "FORM_REPLY_UNMATCHED",
                f"{field.form_label}: {value!r} is close to the choice {near[0]!r} but is not it",
                {field.form_label: [lab for _o, lab, _t in field.options]},
            )
        return [takes[0][0]], value
    for oid, lab in takes:
        prefix = normalise(lab) + ":"
        if want.startswith(prefix):
            return [oid], value[len(lab) + 1 :].strip()
    raise FormReplyError(
        "FORM_REPLY_UNMATCHED",
        f"{field.form_label}: {value!r} matches no choice",
        {field.form_label: [lab for _o, lab, _t in field.options]},
    )


def parse(reply: str, header: str, fields: Sequence[Field]) -> Parsed:
    text = _UPLOADS_RE.sub("", reply, count=1)
    first, _, rest = text.partition("\n")
    first = first.strip()
    if first == SKIP_LINE:
        return Parsed(True, [])
    allowed = {f.form_label: [lab for _o, lab, _t in f.options] for f in fields}
    body = _strip_header(first, header)
    if body is None:
        raise FormReplyError("FORM_REPLY_UNMATCHED", f"the reply does not start with {header!r} and a dash", allowed)
    labels = [f.form_label for f in fields]
    pairs = dict(_split_by_labels(body, labels, line_start_only=False))
    if FULL_CONTENT in rest:
        section = rest.split(FULL_CONTENT, 1)[1]
        for label, value in _split_by_labels(section, labels, line_start_only=True):
            pairs[label] = value
    stray = [p.split(":", 1)[0].strip() for p in body.split(" · ") if ":" in p]
    unknown = [s for s in stray if s and s not in labels and not any(s in v for v in pairs.values())]
    if unknown:
        raise FormReplyError(
            "FORM_REPLY_UNMATCHED", f"the reply names {unknown[0]!r}, which this form did not ask", allowed
        )
    answers: list[tuple[str, list[str], str | None]] = []
    for f in fields:
        if f.form_label not in pairs:
            raise FormReplyError("FORM_REPLY_UNMATCHED", f"the reply has no answer for {f.form_label!r}", allowed)
        ids, picked_value = _match(f, pairs[f.form_label])
        answers.append((f.gate_key, ids, picked_value))
    return Parsed(False, answers)
