"""The founder's own filenames, as the founder named them.

On the cloud-lane Cowork session an attachment is stored as `<8-hex>-<original name>`, and the
skill mirrors it under that name. Downstream the prefixed name is load-bearing -- `red_team.py`
opens `<uploads-dir>/<file>` to check a citation, and the OCR sidecars are keyed on it -- so it is
not renamed at the source. It is renamed only where a founder reads it: "from
a1b2c3d4-market-study.pdf, page 1" names a file the founder never saw.

ONE OWNER. `compose_report.py` (report.md, the verdict the chat hand-over prints) and
`visualize.py` (report.html) both load this module, so the two renderers cannot disagree on what a
file is called.

THE RULE. The platform prefixes EVERY upload in a session, so the prefix is stripped only when
every known name carries `^[0-9a-f]{8}-` -- a single founder file that happens to be named
`deadbeef-notes.pdf` next to a `deck.pdf` is left alone. A batch of one gets a stricter test (at
least one a-f letter), because `20240115-deck.pdf` is a date the founder wrote. A stripped name
that would collide with another name (two uploads of `deck.pdf`) keeps its prefix: the prefix is
then the only thing that says which one is meant.

Known names come from `redteam.json`: `sources_read` + `sources_unread` + every `document:`
citation. Those are the names the validator checked against the mirrored directory. Free text is
rewritten by exact match on those names only, never by a pattern over arbitrary prose.

NOT covered, by design: the coaching payload carries the raw names (its builder is not touched
here), so the coaching commentary can still repeat one.
"""

from __future__ import annotations

import re
from typing import Any

_PREFIX = re.compile(r"^([0-9a-f]{8})-(.+)$")
_DOC_CITE = re.compile(r"^document:([^#]+)(?:#page=\d+)?$")


def known_names(redteam: Any) -> list[str]:
    """Every filename redteam.json names: read, unread, and cited."""
    if not isinstance(redteam, dict):
        return []
    names: list[str] = []
    for key in ("sources_read", "sources_unread"):
        vals = redteam.get(key)
        if isinstance(vals, list):
            names.extend(str(v).strip() for v in vals if isinstance(v, str) and v.strip())
    findings = redteam.get("findings")
    if isinstance(findings, list):
        for f in findings:
            if isinstance(f, dict):
                m = _DOC_CITE.match(str(f.get("source_url") or "").strip())
                if m:
                    names.append(m.group(1))
    return list(dict.fromkeys(names))


def display_map(names: list[str]) -> dict[str, str]:
    """{prefixed name: name as uploaded}, empty unless the batch looks platform-prefixed."""
    names = list(dict.fromkeys(n for n in names if n))
    if not names:
        return {}
    matches = [_PREFIX.match(n) for n in names]
    if not all(matches):
        return {}
    if len(names) == 1 and not re.search(r"[a-f]", matches[0].group(1)):  # type: ignore[union-attr]
        return {}
    stripped = {n: m.group(2) for n, m in zip(names, matches, strict=True) if m}
    targets = list(stripped.values())
    return {n: s for n, s in stripped.items() if targets.count(s) == 1 and s not in stripped}


def for_redteam(redteam: Any) -> dict[str, str]:
    return display_map(known_names(redteam))


def humanize(text: str, mapping: dict[str, str]) -> str:
    """Replace each known prefixed name with its display name, in one pass, longest first."""
    if not mapping or not text:
        return text
    pattern = re.compile("|".join(re.escape(k) for k in sorted(mapping, key=len, reverse=True)))
    return pattern.sub(lambda m: mapping[m.group(0)], text)
