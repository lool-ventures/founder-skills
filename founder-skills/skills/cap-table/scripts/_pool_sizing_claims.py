"""Judge commentary's option-pool sizing sentences against what the model computed.

One instrument, two copies held byte-identical by a sync test: `founder-skills/tests/` (the paid cap-table
lanes and their free table) and the cap-table skill's `scripts/` (the backstop `pool_claims_check.py` runs
before the commentary is inserted).

The rules, and why each exists:

- SEGMENTS, not sentences. Text is split on sentence ends AND line breaks, and list markers are stripped:
  a bullet list with no full stops is several claims, not one.
- A statement that THIS deal's pool is on the other sizing is wrong. The two sizings differ only in the pool's
  denominator, so a sentence saying "the pool is sized pre-money" about a post-money deal is a factual error.
  There is no exemption for a sentence that also names the modeled basis -- "sized pre-money, not post-money"
  is still the wrong claim.
- Known wrong MECHANISMS are wrong whatever the numbers. In this model the pool is created before the round's
  price is set under both sizings; "sized before the pre-money valuation is struck" (as if one sizing sat
  outside the pre-money) and "carved out after the round" describe something else.
- Advice about the OTHER sizing must carry the computed founder percentage. A segment that mentions the other
  sizing in a pool context must contain the counterfactual founders figure (one decimal, +/-0.1). With no
  computed figure, any such advice is unsupported. A "pre-money" that names the valuation ("$12M pre-money",
  "the pre-money valuation", "once pre-money and raise size are agreed") is not a sizing.
- The "only the new options" READING (a post-money target that may count the new options alone) is judged
  against its own figure (`increase_founders_pct`): a figure attached to it must be one of its computed
  figures, never the comparison's. With none computed, the reading may not be raised at all.
- CLOSED-WORLD founders figures (`known_figures`, off unless given): in a pool-sizing sentence about founders,
  every percentage must be one the run computed.
- Residuals the judge cannot see: figures are passed run-wide, not per scenario, and a sentence that swaps the
  modeled and the increase figure cites two computed numbers.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

_WORD = {"pre_money": "pre", "post_money": "post"}
_ROUND_WORD = {"pre_money": "pre-round", "post_money": "post-round"}
# The report names each measure by the share count it counts ("the fully diluted share count before the round").
_ROUND_SIDE = {"pre_money": "before", "post_money": "after"}

_BULLET = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
_SEGMENT_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")
# A segment is about pool sizing if it says so in any of the ways the payload's own labels do -- the labels
# read "unallocated options equal to 10% of the pre-round share count (pre-money basis)" and never say "pool",
# so keying on "pool" alone would skip exactly the sentences the coach is told to write.
# "raise size" / "round size" is not the pool being sized.
_SIZING_CONTEXT = re.compile(
    r"\bpool\b|\bunallocated\s+options\b|\bshare\s+count\b|\bbasis\b"
    r"|(?<!raise\s)(?<!round\s)(?<!deal\s)(?<!check\s)\bsized?\b|\bsizing\b|\btop[- ]?up\b"
    r"|\bnew\s+options\b",
    re.IGNORECASE,
)
# The "only the new options" reading: the payload label's own phrases first (so the coach's sentence built from
# `reading` is always recognised), then the plain ways of saying it.
_INCREASE_READING = re.compile(
    r"\bnew\s+options\s+equal\s+to\b|\bon\s+top\s+of\s+the\s+existing\s+unallocated\s+options\b"
    r"|\bonly\s+the\s+new\s+options\b|\bnew\s+options\s+(?:alone|only)\b|\bsizes?\s+(?:only\s+)?the\s+increase\b"
    r"|\bincrease[- ]sized\b|\bthe\s+new\s+options\s+added\b",
    re.IGNORECASE,
)
_FOUNDERS = re.compile(r"\bfounders?\b", re.IGNORECASE)
_WRONG_MECHANISM = re.compile(
    r"sized\s+(?:before|into)\s+the\s+pre[- ]money\s+valuation"
    r"|before\s+the\s+(?:pre[- ]money\s+)?valuation\s+is\s+(?:struck|set)"
    r"|carved\s+out\s+after\s+the\s+(?:round|price)"
    # In this model the new investors never carry the pool on either sizing.
    r"|(?:shared\s+with|borne\s+by|carried\s+by|split\s+with)\s+(?:the\s+)?new\s+investors"
    r"|new\s+investors\s+(?:share|bear|carry|split)\b",
    re.IGNORECASE,
)
_PCT = re.compile(r"(\d{1,3}(?:\.\d+)?)\s*%")
# A "pre-money" / "post-money" that names the VALUATION, not a pool sizing: "the pre-money valuation", "once
# pre-money and raise size are agreed", "the pre-money is agreed". Only these cues; a bare "or pre-money" in a
# sentence about the pool's sizing is still the other sizing.
_VALUATION_AFTER = re.compile(
    r"\s+valuation\b|\s+(?:and|&)\s+(?:the\s+)?(?:raise|round|new\s+money)\b"
    r"|\s+(?:is|was|has\s+been|are|were)\s+(?:agreed|set|negotiated|fixed)\b",
    re.IGNORECASE,
)
# The report's generated footer, which follows the coaching commentary (insert_coaching.FOOTER_PREFIX).
FOOTER_PREFIX = "*Generated by [founder skills]"
COMMENTARY_HEADING = "## Coaching Commentary"


def coaching_body(report_md: str) -> str | None:
    """The whole coaching commentary in `report_md`: from its heading to the generated footer. None when the
    report has no commentary. Cutting at the first horizontal rule instead judged 490 of 4,570 characters of
    one run's commentary, because a coach may use rules of its own."""
    parts = report_md.split(COMMENTARY_HEADING, 1)
    if len(parts) != 2:
        return None
    body = parts[1]
    end = body.find(FOOTER_PREFIX)
    if end != -1:
        body = body[:end]
    body = body.rstrip()
    if body.endswith("---"):
        body = body[:-3]
    return body.strip()


# A statement is about THIS deal only when it is not conditional ("would", "if", "instead" ...).
_CONDITIONAL = re.compile(r"\b(?:would|could|if|were|instead|had)\b", re.IGNORECASE)


def _segments(text: str) -> list[str]:
    return [seg for _start, _end, seg in _segment_spans(text)]


def _segment_spans(text: str) -> list[tuple[int, int, str]]:
    """(start, end, cleaned segment) over `text`: the span covers the piece between separators, bullet marker
    included, so removing it removes the whole claim."""
    spans: list[tuple[int, int, str]] = []
    pos = 0
    for m in [*_SEGMENT_SPLIT.finditer(text), None]:
        end = m.start() if m is not None else len(text)
        piece = text[pos:end]
        if piece.strip():
            lead = len(piece) - len(piece.lstrip())
            spans.append((pos + lead, pos + len(piece.rstrip()), _BULLET.sub("", piece).strip()))
        if m is not None:
            pos = m.end()
    return spans


def _drop_negated(segment: str, other: str) -> str:
    """Remove "not pre-money" / "rather than a pre-money pool" -- a negated mention restates the modeled basis."""
    word = _WORD[other]
    return re.sub(
        rf"\b(?:not|rather\s+than|instead\s+of|vs\.?|versus)\s+(?:a\s+|on\s+a\s+|the\s+)?{word}[- ]money\b",
        " ",
        segment,
        flags=re.IGNORECASE,
    )


def _recommends_other(segment: str, other: str) -> bool:
    """Advice to pursue the other sizing. "If you can negotiate a pre-money pool, founders would hold 64.8%"
    states a consequence with its figure and is not flagged; "push for a pre-money pool" is."""
    word = _WORD[other]
    pattern = re.compile(
        r"\b(?:negotiat\w*|push\w*|argu\w*|aim\w*|insist\w*|recommend\w*|ask(?:ing)?\s+for|hold\s+out\s+for"
        rf"|go\s+for)\b[^.]{{0,60}}?\b{word}[- ]money\b",
        re.IGNORECASE,
    )
    for m in pattern.finditer(segment):
        if not re.search(r"\bif\s+you\s+(?:can|could|were\s+to)\s+$", segment[: m.start()], re.IGNORECASE):
            return True
    return False


def _other_sizing_mentions(segment: str, other: str) -> list[re.Match[str]]:
    """Mentions of the other sizing that are not a money figure's valuation label ("$12M pre-money")."""
    word, round_word = _WORD[other], _ROUND_WORD[other]
    side = _ROUND_SIDE[other]
    pattern = re.compile(
        rf"\b{word}[- ]money\b|\b{round_word}\s+share\s+count\b|\bshare\s+count\s+{side}\s+the\s+round\b",
        re.IGNORECASE,
    )
    valuation_before = re.compile(r"\$\s?[\d.,]+\s*[kmb]?[a-z]*\s*$", re.IGNORECASE)
    mentions = []
    for m in pattern.finditer(segment):
        if valuation_before.search(segment[: m.start()]) and not re.search(
            r"\bpool\b", segment[m.end() : m.end() + 12]
        ):
            continue  # "$12M pre-money" -- a valuation, unless the next words make it the pool's sizing
        if _VALUATION_AFTER.match(segment, m.end()):
            continue  # "the pre-money valuation", "pre-money and raise size", "the pre-money is agreed"
        mentions.append(m)
    return mentions


def _states_this_deal_is_other(segment: str, other: str) -> bool:
    word = _WORD[other]
    return bool(
        re.search(
            rf"\bpool\s+(?:is|was|has\s+been)\s+(?:sized\s+)?(?:on\s+a\s+|at\s+a\s+)?{word}[- ]money\b", segment, re.I
        )
        or re.search(rf"\b(?:your|this)\s+(?:option\s+)?pool\b[^.]{{0,40}}\b{word}[- ]money\b", segment, re.I)
    )


def _figures(value: float | Sequence[float] | None) -> list[float]:
    if value is None:
        return []
    if isinstance(value, (int, float)):
        return [float(value)]
    return [float(v) for v in value]


def _near(p: float, figures: Sequence[float]) -> bool:
    return any(abs(p - f) <= 0.1 + 1e-9 for f in figures)


def pool_sizing_findings(
    text: str,
    *,
    modeled_basis: str,
    other_founders_pct: float | Sequence[float] | None,
    increase_founders_pct: float | Sequence[float] | None = None,
    target_pct: float | None = None,
    known_figures: Sequence[float] | None = None,
) -> list[dict[str, Any]]:
    """The problems found in `text`, each `{start, end, segment, reason}` over `text`; empty means the pool-sizing
    claims are grounded.

    `modeled_basis` is the term-sheet basis the scenario was solved on (`post_money` / `pre_money`);
    `other_founders_pct` is the computed founders percentage on the other sizing -- one figure, or one per
    scenario when several were computed (a citation must match one of them) -- or None when none was.
    """
    other = "pre_money" if modeled_basis == "post_money" else "post_money"
    allowed = _figures(other_founders_pct)
    increase = _figures(increase_founders_pct)
    problems: list[dict[str, Any]] = []

    def _add(span: tuple[int, int, str], reason: str) -> None:
        problems.append({"start": span[0], "end": span[1], "segment": span[2], "reason": reason})

    for span in _segment_spans(text):
        raw = span[2]
        if _WRONG_MECHANISM.search(raw):
            _add(span, "wrong mechanism")
            continue
        if not _SIZING_CONTEXT.search(raw):
            continue
        # Percentages in the sentence other than the target itself ("the 10% counts ...").
        figures = [float(p) for p in _PCT.findall(raw)]
        stated = [p for p in figures if target_pct is None or abs(p - target_pct) > 1e-9]
        if known_figures is not None and _FOUNDERS.search(raw):
            unknown = [p for p in stated if not _near(p, list(known_figures))]
            if unknown:
                _add(span, f"a founders figure the run did not compute ({unknown})")
                continue
        # A sentence that cites only the comparison's figure beside the words for the comparison's sizing is about
        # that comparison, even when it mentions the new options in passing ("that is different from a term sheet
        # that sizes only the new options"); it is judged below as one.
        about_comparison = (
            bool(allowed)
            and any(_near(p, allowed) for p in stated)
            and not any(_near(p, increase) for p in stated)
            and bool(_other_sizing_mentions(raw, other))
        )
        if _INCREASE_READING.search(raw) and not increase and not about_comparison:
            # None computed: the reading is not the commentary's to raise, with a figure or without one.
            _add(span, "the new-options-only reading, none computed")
            continue
        if _INCREASE_READING.search(raw) and stated and not about_comparison:
            if not any(_near(p, increase) for p in stated):
                _add(span, "new-options-only reading without its computed founders figure")
                continue
            # The comparison's figure may sit in the same sentence only beside the words for ITS sizing; with no
            # such words it reads as a second figure for this reading.
            if allowed and any(_near(p, allowed) for p in stated) and not _other_sizing_mentions(raw, other):
                _add(span, "the pre-money comparison's figure attached to the new-options reading")
                continue
            # A grounded statement of this reading. Naming the comparison beside it ("separately from the pre-money
            # comparison, ...") is not advice about the comparison, so the comparison's rules below do not apply --
            # except that a sentence may still not recommend the other sizing.
            if _recommends_other(raw, other):
                _add(span, "recommends the other sizing")
            continue
        if _recommends_other(raw, other):
            _add(span, "recommends the other sizing")
            continue
        seg = _drop_negated(raw, other)
        if not _CONDITIONAL.search(seg) and _states_this_deal_is_other(seg, other):
            _add(span, "states this deal's pool on the other sizing")
            continue
        if not _other_sizing_mentions(seg, other):
            continue
        if not allowed:
            _add(span, "other-sizing advice with no computed figure to cite")
            continue
        cited = [float(p) for p in _PCT.findall(seg)]
        if not any(abs(p - a) <= 0.1 + 1e-9 for p in cited for a in allowed):
            listed = ", ".join(f"{a:.1f}%" for a in allowed)
            _add(span, f"other-sizing advice does not cite a computed founders figure ({listed})")
    return problems


def pool_sizing_problems(
    text: str,
    *,
    modeled_basis: str,
    other_founders_pct: float | Sequence[float] | None,
    increase_founders_pct: float | Sequence[float] | None = None,
    target_pct: float | None = None,
    known_figures: Sequence[float] | None = None,
) -> list[str]:
    """`pool_sizing_findings` as one line each; empty means the pool-sizing claims are grounded."""
    return [
        f"{f['reason']}: {f['segment'][:160]!r}"
        for f in pool_sizing_findings(
            text,
            modeled_basis=modeled_basis,
            other_founders_pct=other_founders_pct,
            increase_founders_pct=increase_founders_pct,
            target_pct=target_pct,
            known_figures=known_figures,
        )
    ]


def judge_arguments(scenarios_doc: dict[str, Any]) -> dict[str, Any]:
    """The run's computed figures, as the judge takes them: every other-sizing and new-options founders figure
    (percent, one decimal) across the scenarios, and the pool target when every scenario shares one. The paid
    lanes and the in-pipeline backstop both derive their arguments here."""
    other: list[float] = []
    increase: list[float] = []
    targets: set[float] = set()
    for scenario in scenarios_doc.get("scenarios") or []:
        co = (scenario or {}).get("computed_outputs") or {}
        target = ((scenario or {}).get("parameters") or {}).get("target_pool_percent")
        if isinstance(target, (int, float)) and target:
            targets.add(round(float(target) * 100, 6))
        for key, block, out in (
            ("other_value", "pool_sizing_counterfactual", other),
            ("increase_value", "pool_increase_reading", increase),
        ):
            b = co.get(block) or {}
            value = (b.get("founders") or {}).get(key)
            if b.get("status") == "computed" and isinstance(value, (int, float)):
                out.append(round(float(value) * 100, 1))
    return {
        "other_founders_pct": other or None,
        "increase_founders_pct": increase or None,
        "target_pct": next(iter(targets)) if len(targets) == 1 else None,
    }


REPORT_LINE_LEAD = "**Option pool on the other sizing:**"


def counterfactual_lever_problems(scenarios: dict[str, Any], report_md: str) -> list[str]:
    """What stops a green judgement from meaning anything: the lever must have ENGAGED.

    A run whose model produced no computed counterfactual judges the coach against `None`, and a report
    without the line means the founder never saw the figure the coach may cite. Either way the judge
    above can pass while the fix did nothing.
    """
    problems: list[str] = []
    blocks = [
        ((s or {}).get("computed_outputs") or {}).get("pool_sizing_counterfactual")
        for s in (scenarios.get("scenarios") or [])
    ]
    computed = [b for b in blocks if isinstance(b, dict) and b.get("status") == "computed"]
    if not computed:
        statuses = [b.get("status") if isinstance(b, dict) else None for b in blocks]
        problems.append(f"no scenario carries a computed pool-sizing counterfactual (statuses: {statuses})")
    if REPORT_LINE_LEAD not in report_md:
        problems.append("report.md carries no line for the pool's other sizing")
    return problems


INCREASE_LINE_LEAD = "**If your term sheet sizes only the new options:**"
READING_DISCLOSURE = "W_POOL_BASIS_READING_NOT_CONFIRMED"


def increase_reading_lever_problems(scenarios: dict[str, Any], report_md: str) -> list[str]:
    """The new-options-only lane's lever: the disclosure fired, the reading was computed, and report.md carries
    its line. Without all three, a green judgement of the coach says nothing about the figure."""
    problems: list[str] = []
    rows = [((s or {}).get("computed_outputs") or {}) for s in (scenarios.get("scenarios") or [])]
    disclosed = [
        co
        for co in rows
        if any(isinstance(w, dict) and w.get("code") == READING_DISCLOSURE for w in co.get("warnings") or [])
    ]
    if not disclosed:
        problems.append("no scenario carries the pool-reading disclosure")
    blocks = [co.get("pool_increase_reading") for co in disclosed]
    if not any(isinstance(b, dict) and b.get("status") == "computed" for b in blocks):
        statuses = [b.get("status") if isinstance(b, dict) else None for b in blocks]
        problems.append(f"no disclosed scenario carries a computed new-options-only reading (statuses: {statuses})")
    if INCREASE_LINE_LEAD not in report_md:
        problems.append("report.md carries no line for the new-options-only reading")
    return problems
