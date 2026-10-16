"""Context supplied with the request: the checks on its value and on each item.

A request may carry `FS_HOST_VALUE host_context=supplied | <one line of JSON>`: an array of `{fact, source, date}`
objects, each a dated fact with the label of where it came from. It is supplied with the request, so it is
third-party to the analysis and never the founder's own statement, whatever its label says.

Two tiers:
- the whole value is malformed (not JSON, not an array, an element that is not an object, too many elements,
  too long, its facts too long in total): `value_problem` names WHERE, never the value, and the question waits;
- one item breaks a rule (`CAUSES`): `filter_items` drops it by index and cause and keeps the rest. Nothing
  copies a dropped item's text into anything the run writes.

The plugin-root `scripts/` holds the canonical copy and ic-sim's `scripts/` an identical one (skill scripts run
by path and cannot import across directories); a test holds the copies equal. Python 3.9-clean.
"""

from __future__ import annotations

import json
import math
import re
import unicodedata
from collections.abc import Callable, Iterable
from datetime import date, timedelta
from typing import Any
from urllib.parse import unquote, urlsplit

# --- whole-value caps -----------------------------------------------------------------------------------
MAX_ITEMS = 60
MAX_VALUE_CHARS = 16_384
MAX_FACT_CHARS_TOTAL = 4_096
# --- per-item caps ---------------------------------------------------------------------------------------
FACT_MAX = 300
SOURCE_MAX = 80
# A date may be the day after the run started (a host in another time zone), never later.
DATE_GRACE_DAYS = 1
ITEM_KEYS = ("fact", "source", "date")

# Why an item was dropped. Codes are contract; the words are the founder's.
CAUSES = {
    "item_shape": "it was not in the expected form",
    "fact_length": "the fact was empty or too long",
    "source_length": "its source label was empty or too long",
    "date_invalid": "its date was not a real date",
    "date_after_run_start": "it was dated after this run started",
    "control_characters": "it contained characters that cannot be shown",
    "header_text": "it contained text reserved for instructions",
    "person_detail": "it contained contact details",
}

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# C0, DEL and C1 (U+0085 among them); the line and paragraph separators `str.splitlines()` also breaks a line on;
# and the zero-width space and the bidirectional controls (U+200B, U+200E-U+200F, U+202A-U+202E, U+2066-U+2069,
# U+FEFF), which can reorder or hide a fact as rendered. The zero-width non-joiner and joiner (U+200C, U+200D) are
# kept: Persian, Urdu and Kurdish spell words with the first, Indic conjuncts and joined emoji need the second.
_CONTROL_RE = re.compile("[\\x00-\\x1f\\x7f-\\x9f\\u200b\\u200e\\u200f\\u2028-\\u202e\\u2066-\\u2069\\ufeff]")
_HEADER_PREFIXES = ("CONTEXT:", "OUTPUT_PATH:", "RUN_ID:")
_EMAIL_RE = re.compile(r"[^\s@<>()\[\]{},;:\"'`]+@[^\s@<>()\[\]{},;:\"'`]+\.[^\W\d_]{2,}")
_TEL_RE = re.compile(r"\btel:", re.IGNORECASE)
# A phone number: a run starting with `+` or `(` of digits joined only by spaces, dots, hyphens and parentheses.
_PHONE_RUN_RE = re.compile(r"[+(][\d\s.()\-]*\d")
_CURRENCY = "$€£¥₪₹"
_URL_RE = re.compile(r"(?:https?:/{1,2}|www\.)[^\s<>\"']+|\b[\w.-]+\.[a-z]{2,}/[^\s<>\"']*", re.IGNORECASE)

# A URL whose path is a person's page by construction: (host suffix, first path segment). A copy of
# ic-sim's `fund_profile._is_person_page` rule, held equal by a test.
_PERSON_PAGES = (("linkedin.com", "in"), ("linkedin.com", "pub"), ("crunchbase.com", "person"))
_PATH_PREFIXES = {"linkedin.com": ("mwlite",)}


def _host_matches(host: str, suffix: str) -> bool:
    return host == suffix or host.endswith("." + suffix)


def _is_person_page(url: Any) -> bool:
    if not isinstance(url, str) or not url.strip():
        return False
    text = url.strip()
    scheme, sep, rest = text.partition(":")
    if sep and scheme.casefold() in ("http", "https") and not rest.startswith("//"):
        text = scheme + "://" + rest.lstrip("/")
    elif "//" not in text:
        text = "//" + text
    try:
        parts = urlsplit(text)
        host = (parts.hostname or "").casefold().rstrip(".")
    except ValueError:
        return False
    segments = [seg for seg in unquote(parts.path).casefold().split("/") if seg]
    for suffix, prefixes in _PATH_PREFIXES.items():
        if _host_matches(host, suffix) and segments and segments[0] in prefixes:
            segments = segments[1:]
    first = segments[0] if segments else ""
    return any(_host_matches(host, suffix) and first == seg for suffix, seg in _PERSON_PAGES)


def _has_phone(text: str) -> bool:
    for m in _PHONE_RUN_RE.finditer(text):
        run = m.group(0)
        if sum(ch.isdigit() for ch in run) < 9:
            continue
        before = text[m.start() - 1] if m.start() > 0 else ""
        after = text[m.end()] if m.end() < len(text) else ""
        after2 = text[m.end() + 1] if m.end() + 1 < len(text) else ""
        if (before and before in _CURRENCY) or (after and after in _CURRENCY) or after == "%":
            continue
        if after and after in ".," and after2.isdigit():
            continue
        return True
    return False


def has_person_detail(text: str) -> bool:
    """An e-mail address (any script in its local part), a phone number or a person's page, judged on the NFKC form
    so a full-width `＠` is an `@`. Names are not detected."""
    text = unicodedata.normalize("NFKC", text)
    if _EMAIL_RE.search(text) or _TEL_RE.search(text) or _has_phone(text):
        return True
    return any(_is_person_page(m.group(0).rstrip(".,;:)")) for m in _URL_RE.finditer(text))


def _reject_constant(name: str) -> Any:
    """`json.loads`' hook for `NaN`, `Infinity` and `-Infinity`, which JSON does not allow."""
    raise ValueError(f"{name} is not a JSON number")


def has_non_finite(node: Any) -> bool:
    """A number that is not finite (`1e400` reads as infinity), anywhere in a decoded value."""
    if isinstance(node, float):
        return not math.isfinite(node)
    if isinstance(node, list):
        return any(has_non_finite(x) for x in node)
    if isinstance(node, dict):
        return any(has_non_finite(x) for x in node.values())
    return False


def value_problem(value: str) -> str | None:
    """Why the whole value cannot be read, naming where and never echoing it; None when it can. Never raises."""
    if len(value) > MAX_VALUE_CHARS:
        return f"the context is longer than {MAX_VALUE_CHARS:,} characters"
    try:
        items = json.loads(value, parse_constant=_reject_constant)
    except ValueError as e:
        pos = getattr(e, "pos", None)
        where = f" at character {pos + 1}" if isinstance(pos, int) else ""
        return f"the context is not valid JSON{where}"
    except Exception:  # noqa: BLE001 -- a value that cannot be decoded is malformed, never a crash
        return "the context is not valid JSON"
    if has_non_finite(items):
        return "the context holds a number that is not finite"
    if not isinstance(items, list):
        return "the context is not a JSON array"
    if len(items) > MAX_ITEMS:
        return f"the context has more than {MAX_ITEMS} items"
    for i, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            return f"item {i} of the context is not a JSON object"
    total = sum(len(item["fact"]) for item in items if isinstance(item.get("fact"), str))
    if total > MAX_FACT_CHARS_TOTAL:
        return f"the context's facts total more than {MAX_FACT_CHARS_TOTAL:,} characters"
    return None


def _item_cause(item: dict[str, Any], as_of: date) -> str | None:
    if set(item) != set(ITEM_KEYS) or not all(isinstance(item[k], str) for k in ITEM_KEYS):
        return "item_shape"
    fact, source, when = item["fact"], item["source"], item["date"]
    if not 1 <= len(fact) <= FACT_MAX:
        return "fact_length"
    if not 1 <= len(source) <= SOURCE_MAX:
        return "source_length"
    if not _DATE_RE.match(when):
        return "date_invalid"
    try:
        dated = date.fromisoformat(when)
    except ValueError:
        return "date_invalid"
    if dated > as_of + timedelta(days=DATE_GRACE_DAYS):
        return "date_after_run_start"
    if any(_CONTROL_RE.search(s) for s in (fact, source, when)):
        return "control_characters"
    for s in (fact, source):
        if "FS_HOST_" in s or s.lstrip().upper().startswith(_HEADER_PREFIXES):
            return "header_text"
    if has_person_detail(fact) or has_person_detail(source):
        return "person_detail"
    return None


def filter_items(items: list[Any], as_of: date) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(kept, dropped) for an array `value_problem` accepted. Kept items carry their 1-based `index` in the
    host's order with `fact`, `source` and `date`; dropped ones carry only `index` and `cause`."""
    kept: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    for i, item in enumerate(items, start=1):
        cause = _item_cause(item, as_of) if isinstance(item, dict) else "item_shape"
        if cause is None:
            kept.append({"index": i, "fact": item["fact"], "source": item["source"], "date": item["date"]})
        else:
            dropped.append({"index": i, "cause": cause})
    return kept, dropped


def parse_and_filter(value: str, as_of: date) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """`filter_items` over a value `value_problem` accepted. Raises ValueError with its cause otherwise."""
    problem = value_problem(value)
    if problem is not None:
        raise ValueError(problem)
    return filter_items(json.loads(value, parse_constant=_reject_constant), as_of)


def keep_tokens(kept: Iterable[dict[str, Any]], scan: Callable[..., dict[str, list[str]]]) -> list[str]:
    """The tokens the founder-text scan would flag in the kept facts and sources. The report renders those
    verbatim, so the same set is kept by both the substitution and the scan. `scan` is the shared policy's."""
    found: set[str] = set()
    for item in kept:
        for key in ("fact", "source"):
            text = item.get(key)
            if isinstance(text, str):
                found.update(scan(text)["enums"])
    return sorted(found)


def dropped_sentence(dropped: list[dict[str, Any]], total: int) -> str | None:
    """The founder's line for the items not used, by number and cause, never their text."""
    if not dropped:
        return None
    parts = [f"fact {d['index']} ({CAUSES.get(str(d.get('cause')), 'it could not be used')})" for d in dropped]
    noun = "fact" if total == 1 else "facts"
    verb = "was" if len(dropped) == 1 else "were"
    return f"{len(dropped)} of {total} {noun} supplied with this request {verb} not used: {', '.join(parts)}."
