"""Classify each top-level key of a page's embedded JS payload as read, unread, or unverifiable.

An unread key is a founder-facing feature that silently does not exist while still costing payload
size, so `unread` is a defect. Three verdicts, because two are not enough:

  read          the script names the key — dotted (`DATA.k`), static bracket (`DATA["k"]`), or named
                destructuring (`const {k} = DATA`).
  unread        access to the payload is entirely static and no read of this key exists.
  unverifiable  the script indexes the payload with a computed name (`DATA[k]`), iterates it, or
                spreads it. Such access names no specific key, so this key cannot be shown either
                read or dead.

`unverifiable` must not be treated as clean, and must not be reported as dead. Callers decide the
policy; conflating it in either direction produces false negatives or false positives respectively.
"""

from __future__ import annotations

import re
from typing import Any

# `const X = DATA;` binds an ALIAS for the whole object, so `X.key` is a real read. The negative
# lookahead excludes a MEMBER binding (`const pre = DATA.pre_financing`), whose member reads say
# nothing about the payload's other keys.
_ALIAS_RE_TEMPLATE = r"(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*{var}\s*(?![.\[\w])"

# Whole-object consumption: the script reaches every key without naming any, so no read can be
# attributed to a specific key.
#
# The trailing `(?![.\[\w])` on each is required. Without it, `for (const s of DATA.scenarios)` reads as
# iteration over DATA itself, which would mark every other key unverifiable and hide real dead keys
# behind a false "cannot tell".
_WHOLE_OBJECT_TEMPLATES = (
    r"Object\.(?:keys|values|entries|assign)\s*\(\s*{var}(?![.\[\w])",
    r"for\s*\((?:const|let|var)?\s*[\w$]+\s+(?:in|of)\s+{var}(?![.\[\w])",
    r"\.\.\.\s*{var}(?![.\[\w])",
    r"JSON\.stringify\s*\(\s*{var}(?![.\[\w])",
)


def find_aliases(script: str, var: str) -> set[str]:
    """Names bound to the whole payload object, so their member reads count."""
    pattern = _ALIAS_RE_TEMPLATE.format(var=re.escape(var))
    return {m.group(1) for m in re.finditer(pattern, script)}


def _has_dynamic_access(script: str, name: str) -> bool:
    """True when the script indexes `name` with something other than a string literal."""
    if re.search(rf"\b{re.escape(name)}\s*\[\s*(?!['\"])", script):
        return True
    return any(re.search(tpl.format(var=re.escape(name)), script) for tpl in _WHOLE_OBJECT_TEMPLATES)


def _destructured_keys(script: str, name: str) -> set[str]:
    """Keys named in `const {a, b: c} = name`: `a` and `b` are reads; `c` is a local alias, not a key."""
    keys: set[str] = set()
    for m in re.finditer(rf"\{{([^{{}}]*)\}}\s*=\s*{re.escape(name)}\b", script):
        for part in m.group(1).split(","):
            part = part.strip()
            if not part or part.startswith("..."):
                continue
            # `b: c` reads key `b`; `a = 1` is a default, key `a`.
            token = re.split(r"[:=]", part, maxsplit=1)[0].strip()
            if re.fullmatch(r"[A-Za-z_$][\w$]*", token):
                keys.add(token)
    return keys


def _reads_key(script: str, name: str, key: str) -> bool:
    k = re.escape(key)
    n = re.escape(name)
    if re.search(rf"\b{n}\s*\??\s*\.\s*{k}\b", script):  # DATA.key / DATA?.key
        return True
    if re.search(rf"\b{n}\s*(?:\?\.)?\s*\[\s*(['\"]){k}\1\s*\]", script):  # DATA["key"] / DATA?.["key"]
        return True
    return False


def analyze(script: str, keys: list[str] | set[str], *, var: str = "DATA") -> dict[str, Any]:
    """Classify each top-level payload key as read, unread, or unverifiable.

    Returns {"read", "unread", "unverifiable", "dynamic_access", "aliases"}. `unread` is non-empty only
    when access is fully static; otherwise an unmatched key goes to `unverifiable`.
    """
    names = {var} | find_aliases(script, var)
    dynamic = any(_has_dynamic_access(script, n) for n in names)

    destructured: set[str] = set()
    for n in names:
        destructured |= _destructured_keys(script, n)

    read: set[str] = set()
    for key in keys:
        if key in destructured or any(_reads_key(script, n, key) for n in names):
            read.add(key)

    unmatched = sorted(set(keys) - read)
    return {
        "read": sorted(read),
        "unread": [] if dynamic else unmatched,
        "unverifiable": unmatched if dynamic else [],
        "dynamic_access": dynamic,
        "aliases": sorted(names - {var}),
    }


_OBJECT_RE_TEMPLATE = r"const\s+{var}\s*=\s*(\{{.*?\}})\s*;"


def extract_payload(html: str, var: str = "DATA") -> dict[str, Any]:
    """Parse the embedded `const <var> = {...};` object out of a generated page.

    Raises AssertionError when it cannot be found or parsed: a payload that silently parses as empty
    makes every downstream scan vacuous.
    """
    import json

    match = re.search(_OBJECT_RE_TEMPLATE.format(var=re.escape(var)), html, re.DOTALL)
    assert match, f"could not locate the embedded `const {var} = {{...}};` object"
    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError as exc:  # pragma: no cover - a real failure should be loud
        raise AssertionError(f"embedded {var} object is not valid JSON: {exc}") from exc
    assert isinstance(payload, dict), f"embedded {var} is not an object"
    return payload
