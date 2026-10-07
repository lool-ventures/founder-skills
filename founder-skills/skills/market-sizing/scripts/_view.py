"""The one owner of every founder-visible market-sizing figure and the facts derived from them.

compose_report.py (report.md, report.json, the verdict the hand-over prints, the coaching payload)
and visualize.py (report.html) both render from this module. Before it existed, visualize carried
its own copies of these functions, held equal only by a test that compared their bodies, and two
of them had already drifted: its deck-claim currency comparison was a separate implementation, and
it printed an unknown currency as "$".

Moved here unchanged from compose_report.py, which re-exports every name, so both renderers and
the tests that reach through compose keep their spelling.
"""

from __future__ import annotations

import contextlib
import json as _json
import math
import os
import os as _os
import re
import sys
from collections.abc import Iterator
from typing import Any, TypeGuard

import _params
import _provenance
from _quote_match import quote_in_doc
from _redteam_text import humanize_claim as _humanize_claim
from _redteam_text import humanize_param as _humanize_param

# Sentinel for corrupt (unparseable) artifact files
_CORRUPT: dict[str, Any] = {"__corrupt__": True}


# Quantitative params that should appear in sensitivity analysis if agent_estimate
QUANTITATIVE_PARAMS = {
    "customer_count",
    "arpu",
    "serviceable_pct",
    "target_pct",
    "industry_total",
    "segment_pct",
    "share_pct",
}


def _is_stub(data: dict[str, Any] | None) -> bool:
    """Check if artifact is a stub (intentionally skipped)."""
    return isinstance(data, dict) and data.get("skipped") is True


def _usable(data: dict[str, Any] | None) -> TypeGuard[dict[str, Any]]:
    """Check if artifact is loaded, not corrupt, and not a stub."""
    return data is not None and data is not _CORRUPT and not _is_stub(data)


def _as_list(value: Any) -> list[Any]:
    """Coerce to list — returns [] if not a list."""
    return value if isinstance(value, list) else []


def _as_dict(value: Any) -> dict[str, Any]:
    """Coerce to dict — returns {} if not a dict."""
    return value if isinstance(value, dict) else {}


# The currency label money is formatted in during ONE render, set from the artifacts by
# _set_currency(). A bare "$" on a non-USD analysis is a wrong UNIT on the headline number. Callers
# may pass currency_code explicitly; this is only the default, so the ~30 _fmt_usd call sites
# (each inside a section renderer with no business knowing about currency) need not thread it.
#
# It is module state shared by BOTH renderers, and it is only safe because every entry point runs
# inside render_scope(), which puts it back to "USD" when the render ends, however it ends. "These
# are single-shot CLIs" was true in production and false in a test session, where one process runs
# every render: a render in shekels changed how the next test formatted dollars.
_CURRENCY: str = "USD"


@contextlib.contextmanager
def render_scope() -> Iterator[None]:
    """Run one render; the currency default is "USD" again afterwards, even if the render raises."""
    global _CURRENCY
    _CURRENCY = "USD"
    try:
        yield
    finally:
        _CURRENCY = "USD"


def _resolve_currency(*artifacts: dict[str, Any] | None) -> str:
    """Return the analysis currency code from the first artifact carrying one.

    Checked in the order passed by the caller; falls back to "USD" (the
    back-compat default) when none carry a currency field.
    """
    for artifact in artifacts:
        if isinstance(artifact, dict):
            currency = artifact.get("currency")
            if isinstance(currency, str) and currency.strip():
                return currency.strip().upper()
    return "USD"


def _set_currency(code: str) -> None:
    """Set the process-wide default currency label for _fmt_usd."""
    global _CURRENCY
    _CURRENCY = code.strip().upper() if isinstance(code, str) and code.strip() else "USD"


def _fmt_usd(value: float | int, currency_code: str | None = None) -> str:
    """Format a number as a compact currency string, scaled with K/M/B suffixes.

    Defaults to the process-wide currency (``_set_currency``), itself defaulting
    to "USD" and rendering a bare "$" prefix. Any other ISO code is tagged as a
    suffix instead (e.g. "1.5M ILS") — a bare "$" would misrepresent a
    non-USD-denominated analysis.

    Passing "" means NO currency marker at all, for the one case where the currency is
    genuinely unknown: a founder-stated figure whose currency was never declared. Falling
    back to USD there stamps "$" on a figure we are simultaneously saying we cannot place,
    and stamping the analysis currency asserts the very thing the comparison was refused for.
    """
    return _params.fmt_money(value, _CURRENCY if currency_code is None else currency_code)


def _fx_conversions(sizing: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    """Map money-field name -> its conversion record from `sizing.fx`. Empty when no FX ran."""
    fx = _as_dict(_as_dict(sizing).get("fx"))
    out: dict[str, dict[str, Any]] = {}
    for entry in _as_list(fx.get("conversions")):
        rec = _as_dict(entry)
        field = rec.get("field")
        if isinstance(field, str):
            out[field] = rec
    return out


def _to_analysis_currency(
    stated: float,
    declared: Any,
    target: Any,
    conversions: list[dict[str, Any]],
) -> tuple[float | None, str | None]:
    """Express a founder-stated / deck-claimed figure in the analysis currency.

    Returns (value, reason_it_cannot_be_compared). Exactly one is non-None.

    Only meaningful once FX exists: before it, every figure on the page was in one currency by
    construction and this returned the input unchanged. The undeclared-currency case is
    genuinely undecidable — the founder of an ILS company may state ILS while the researched
    source was USD, so guessing either way manufactures a false positive of the FX rate's
    magnitude. Say so instead.
    """
    # A declared currency is honoured FIRST, before the was-this-field-converted question. The
    # declaration is object-level (one code for all of founder_stated_inputs), so a run that
    # converted `industry_total` but sourced `arpu` domestically has no conversion record for
    # `arpu` — and short-circuiting on `conversion is None` here would compare a declared-USD
    # figure against an ILS one and report the founder's own number as overridden.
    dec = str(declared).upper() if _valid_ccy(declared) else None
    tgt = str(target).upper() if _valid_ccy(target) else None

    if dec is not None and tgt is not None and dec == tgt:
        return stated, None  # already in the analysis currency, converted field or not

    if not conversions:
        # Nothing was converted anywhere: every figure is in one currency by construction, which
        # is the pre-FX world and the overwhelmingly common case.
        return stated, None

    if dec is None:
        _froms = sorted({str(c.get("from")) for c in conversions if c.get("from")})
        return None, (
            f"the calculation converted its input from {' and '.join(_froms) or 'another currency'} "
            f"to {tgt or 'the analysis currency'}, and no currency was stated for the figure being "
            f"compared"
        )

    # Match by CURRENCY PAIR, not by field. A run can convert two fields from two different
    # source currencies, and the deck-claim check has no single field to key on — picking the
    # first record would refuse a comparison that is fully computable from the second. Rates come
    # from one pair-keyed map upstream, so every record sharing a pair shares its rate.
    for rec in conversions:
        if str(rec.get("from", "")).upper() == dec and (tgt is None or str(rec.get("to", "")).upper() == tgt):
            try:
                return float(stated) * float(rec["rate"]), None
            except (TypeError, ValueError, KeyError):
                return None, "the recorded conversion rate is unusable"

    return None, (
        f"the figure is in {dec}, and this run supplied no rate from {dec} to {tgt or 'the analysis currency'}"
    )


def _valid_ccy(value: Any) -> bool:
    """ISO-4217 shape check, mirrored from market_sizing.py."""
    return isinstance(value, str) and len(value) == 3 and value.isalpha()


# Below this |delta| vs a founder-stated figure, agreement carries no evidentiary weight: it can
# mean both analyses read the same source, or that our input came from their materials. Measured
# across a 3-deck corpus every close agreement was the top-down TAM and none was flagged.
# Above it, DECK_CLAIM_MISMATCH fires -- but NOT immediately above: see DECK_MISMATCH_PCT for the
# (25, 50] band where neither speaks. visualize.py carries the same constant.
CLOSE_AGREEMENT_PCT = 25.0


# DECK_CLAIM_MISMATCH's threshold. Deliberately NOT lowered to meet CLOSE_AGREEMENT_PCT, which would
# have closed the (25, 50] band where neither the footnote nor a warning speaks. Measured: lowering
# it also fires on a bottom-up figure against a claim the deck only stated for its top-down TAM
# (-32.5% on the shared fixture). That was originally read as noise; it is not. `existing_claims` is
# keyed by METRIC with no approach dimension, so comparing one claim against both approaches is
# established, deliberate behaviour -- it already fires today (deck-01 bottom-up TAM at -95.9%, one
# of the pilot's best catches) and the note renderer below has purpose-built per-approach wording for
# it. The only real gap is that this block's message omits the approach label that renderer already
# carries. So the band is a KNOWN GAP, not a design: a deck-01 SOM sits at -43.2% with no warning.
# Closing it = add the approach label here, then lower this to CLOSE_AGREEMENT_PCT.
DECK_MISMATCH_PCT = 50.0


def _horizon_mismatch(inputs: dict[str, Any] | None, metric: str) -> tuple[int, int] | None:
    """(claim_months, ours_months) when both are stated for SOM and differ; else None.

    SOM ONLY, and the scoping is load-bearing. `capture_horizon_months` describes the period
    `share_pct` / `target_pct` represent, which is a SOM concept. Read for TAM or SAM it would let
    an analyst who records a stated SAM horizon blank the SAM comparison -- which on the run that
    motivated this check is the one deck finding that is real.
    """
    if metric != "som" or not isinstance(inputs, dict):
        return None
    claim = _as_dict(inputs.get("existing_claims_horizon_months")).get(metric)
    ours = inputs.get("capture_horizon_months")
    if not isinstance(claim, int) or isinstance(claim, bool):
        return None
    if not isinstance(ours, int) or isinstance(ours, bool):
        return None
    return (claim, ours) if claim != ours else None


def _compute_delta(calculated: float, deck_claim: Any) -> float | None:
    """Returns signed percentage delta, or None if claim is invalid."""
    try:
        claim = float(deck_claim)
    except (TypeError, ValueError):
        return None
    if claim <= 0:
        return None
    return round((calculated - claim) / claim * 100, 1)


def _claim_high(inputs: dict[str, Any] | None, metric: str) -> float | None:
    """The upper bound of a figure the founder stated as a RANGE, or None.

    `existing_claims` holds the low end; `existing_claims_high` the high end. An upper bound with no
    numeric low end for the same metric, or one not above it, is IGNORED (and reported under
    EXISTING_CLAIMS_SHAPE): a range needs both ends, and supplying the missing one would invent a
    figure the founder did not state.
    """
    if not isinstance(inputs, dict):
        return None
    low = _as_dict(inputs.get("existing_claims")).get(metric)
    high = _as_dict(inputs.get("existing_claims_high")).get(metric)
    if not isinstance(low, (int, float)) or isinstance(low, bool):
        return None
    if not isinstance(high, (int, float)) or isinstance(high, bool):
        return None
    return float(high) if float(high) > float(low) > 0 else None


def _range_delta(calculated: float, low: float, high: float | None) -> tuple[float | None, bool]:
    """(signed % delta, inside the range). Inside a stated range there is no disagreement; outside
    it the delta is measured to the NEAREST bound, not to the low end."""
    if high is None:
        return _compute_delta(calculated, low), False
    if low <= calculated <= high:
        return 0.0, True
    return _compute_delta(calculated, low if calculated < low else high), False


def claim_display(low: float, high: float | None = None, currency_code: str | None = None) -> str:
    """How a stated figure is printed on every surface: one number, or the range the founder gave."""
    if high is None:
        return _fmt_usd(low, currency_code)
    return f"{_fmt_usd(low, currency_code)}–{_fmt_usd(high, currency_code)}"


def claim_disagreements(inputs: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Other figures the founder's materials state for a metric, that disagree with the one compared.

    `existing_claims_alternatives` = {metric: [{value, slide, label}]}. An alternative inside the
    stated figure (within 1%, or inside a stated range) restates it and is not a disagreement. One for a
    metric with no stated figure is ignored here and reported under EXISTING_CLAIMS_SHAPE.
    """
    if not isinstance(inputs, dict):
        return []
    claims = _as_dict(inputs.get("existing_claims"))
    alts = _as_dict(inputs.get("existing_claims_alternatives"))
    ccy = inputs.get("existing_claims_currency") if isinstance(inputs.get("existing_claims_currency"), str) else None
    out: list[dict[str, Any]] = []
    for metric in ("tam", "sam", "som"):
        low = claims.get(metric)
        if not isinstance(low, (int, float)) or isinstance(low, bool) or low <= 0:
            continue
        high = _claim_high(inputs, metric)
        others = []
        for alt in _as_list(alts.get(metric)):
            v = _as_dict(alt).get("value")
            if not isinstance(v, (int, float)) or isinstance(v, bool) or v <= 0:
                continue
            lo, hi = float(low) * 0.99, (high if high is not None else float(low)) * 1.01
            if lo <= v <= hi:
                continue
            others.append({"value": float(v), "slide": _as_dict(alt).get("slide"), "label": _as_dict(alt).get("label")})
        if others:
            out.append({"metric": metric, "stated": claim_display(float(low), high, ccy), "others": others, "ccy": ccy})
    return out


def disagreement_sentence(item: dict[str, Any]) -> str:
    """The one wording, used by the report's warning and the page's note."""
    parts = []
    for o in item["others"]:
        where = f"slide {o['slide']}" if o.get("slide") not in (None, "") else "elsewhere in your materials"
        label = f', "{o["label"]}"' if o.get("label") else ""
        parts.append(f"{_fmt_usd(o['value'], item.get('ccy'))} ({where}{label})")
    return (
        f"Your materials state {item['metric'].upper()} as {item['stated']} and also as {', '.join(parts)}. "
        f"This analysis compares against {item['stated']}; say which figure you stand behind."
    )


def _comparable_claim(claim: Any, sizing: dict[str, Any], inputs: dict[str, Any] | None) -> tuple[float | None, bool]:
    """Express a deck claim in the analysis currency. Returns (value, blocked).

    Delegates to _to_analysis_currency -- the SAME function the DECK_CLAIM_MISMATCH block uses --
    rather than re-implementing a subset of it. An earlier version of this checked only for an
    UNDECLARED claim currency, which missed three of that function's refusal conditions and, worse,
    left the declared-and-convertible case comparing a RAW claim here against a CONVERTED one in the
    warning. Measured, that shipped a single report saying "+11.1% *" in the table and
    "differs from deck claim by -72.2%" in the warnings, about one figure.

    Non-FX runs are unaffected: with no conversions recorded, _to_analysis_currency returns the
    claim unchanged and never blocks.
    """
    if not isinstance(claim, (int, float)) or isinstance(claim, bool):
        return None, False
    value, reason = _to_analysis_currency(
        float(claim),
        (inputs or {}).get("existing_claims_currency"),
        sizing.get("currency"),
        list(_fx_conversions(sizing).values()),
    )
    return value, reason is not None


def _compute_provenance(
    sizing: dict[str, Any],
    validation: dict[str, Any] | None,
    inputs: dict[str, Any] | None,
) -> tuple[dict[str, dict[str, Any]], list[tuple[str, str]]]:
    """Compute provenance classification for each TAM/SAM/SOM figure.

    Cross-references validation.json assumptions with sizing.json inputs
    and inputs.json existing_claims.
    """
    # Grades come only from what the calculator stamped as consumed (stamped_provenance). The
    # research record is not consulted: joining it by name graded a figure by whatever shared its name.
    stamped = stamped_provenance(sizing)

    # Get deck claims from inputs
    existing_claims: dict[str, Any] = {}
    if inputs is not None and not _is_stub(inputs):
        existing_claims = _as_dict(inputs.get("existing_claims"))

    provenance: dict[str, dict[str, Any]] = {}
    unresolved: list[tuple[str, str]] = []  # (param, metric) pairs

    for approach_key in ("top_down", "bottom_up"):
        approach_data = sizing.get(approach_key)
        if approach_data is None:
            continue
        approach_prov: dict[str, Any] = {}
        for metric in ("tam", "sam", "som"):
            m = _as_dict(approach_data.get(metric))
            figure_inputs = _as_dict(m.get("inputs"))
            # Filter to quantitative params only (skip intermediates like tam, sam, etc.)
            relevant_inputs = {k: v for k, v in figure_inputs.items() if k in QUANTITATIVE_PARAMS}

            # Look up each input's category
            input_provenances: dict[str, str] = {}
            for param_name in relevant_inputs:
                if stamped is not None:
                    # A stamped sizing says what each input WAS, recorded by the producer that consumed
                    # it.
                    grade = _stamped_grade(stamped.get(param_name))
                    if grade is None:
                        unresolved.append((param_name, metric.upper()))
                    else:
                        input_provenances[param_name] = grade
                else:
                    # An unstamped sizing says nothing about where its inputs came from, and a
                    # record entry that shares an input's name is not evidence that it is the figure
                    # the sizing used.
                    unresolved.append((param_name, metric.upper()))

            # Classify the figure
            if not input_provenances:
                classification = "unknown"
            else:
                categories = set(input_provenances.values())
                if "agent_estimate" in categories:
                    classification = "agent_estimate"
                elif categories == {"sourced"}:
                    classification = "sourced"
                else:
                    classification = "derived"

            # Confidence breakdown
            breakdown: dict[str, int] = {"sourced": 0, "derived": 0, "agent_estimate": 0}
            for cat in input_provenances.values():
                if cat in breakdown:
                    breakdown[cat] += 1

            # Deck claim and delta
            deck_claim = existing_claims.get(metric)
            # A non-numeric figure has no delta; it must not crash the page (visualize's copy was the
            # defensive one before the two were merged).
            value_num = _as_number(m.get("value", 0))
            # Compare like with like: when the claim converts, the delta (and the figure the table
            # prints) must be the CONVERTED claim, matching the warning block.
            comparable, blocked = _comparable_claim(deck_claim, sizing, inputs)
            claim_high = _claim_high(inputs, metric)
            high_comparable, _ = (
                _comparable_claim(claim_high, sizing, inputs) if claim_high is not None else (None, False)
            )
            # A BLOCKED comparison has no delta -- not a delta computed from the wrong operand.
            # Falling back to the raw claim here is what produced "+11.1%" in the table beside a
            # warning saying the figure could not be cross-checked at all: the number was the
            # exchange rate's magnitude, not a disagreement. Killing it at the producer means no
            # renderer has to remember the guard.
            delta, within = (
                _range_delta(value_num, comparable, high_comparable)
                if value_num is not None and deck_claim is not None and comparable is not None
                else (None, False)
            )

            # A horizon mismatch kills the delta exactly as a blocked currency comparison does --
            # same shape, so neither renderer has to learn a second guard to avoid asserting
            # closeness across an incomparable pair.
            horizon = _horizon_mismatch(inputs, metric)
            if horizon is not None:
                delta = None
                comparable = None
                high_comparable = None
                within = False

            approach_prov[metric] = {
                "classification": classification,
                "confidence_breakdown": breakdown,
                "deck_claim": deck_claim,
                "delta_vs_deck_pct": delta,
                "deck_claim_comparable": comparable,
                "deck_claim_high": claim_high,
                "deck_claim_high_comparable": high_comparable,
                "within_claim_range": within,
                "comparison_blocked": blocked,
                "horizon_mismatch": ({"claim_months": horizon[0], "ours_months": horizon[1]} if horizon else None),
                "input_provenances": input_provenances,
            }
        provenance[approach_key] = approach_prov

    return provenance, unresolved


def _contested_rows(
    sizing: dict[str, Any] | None, inputs: dict[str, Any] | None, redteam: dict[str, Any] | None
) -> set[tuple[str, str]]:
    """(approach, metric) pairs built on a founder-stated input that a HIGH red-team finding names.

    A mark, not a re-basing: the red team may not propose a replacement figure, and the live
    finding that motivated this quoted a monthly rate against an annual ARPU -- a number field
    would have laundered that unit mismatch into a warning. What the founder needs is to see which
    rows rest on the contested figure. A metric consumes a parameter if that parameter appears in
    its own `inputs` or in any block above it in the same approach (SAM is built on TAM).
    """
    if not isinstance(sizing, dict) or not _usable(redteam):
        return set()
    stated = _as_dict(_as_dict(inputs).get("founder_stated_inputs"))
    contested = {
        str(f.get("parameter"))
        for f in _as_list(_as_dict(redteam).get("findings"))
        if isinstance(f, dict) and f.get("severity") == "high" and isinstance(f.get("parameter"), str)
    }
    contested &= set(stated.keys())
    if not contested:
        return set()
    rows: set[tuple[str, str]] = set()
    for approach in ("top_down", "bottom_up"):
        consumed: set[str] = set()
        for metric in ("tam", "sam", "som"):
            block = _as_dict(_as_dict(sizing.get(approach)).get(metric))
            consumed |= set(_as_dict(block.get("inputs")).keys())
            if consumed & contested:
                rows.add((approach, metric))
    return rows


def _source_class(url: str) -> str:
    """Where a red-team finding's sentence came from: `published` (a web address), `internal`
    (`internal:analysis`) or `document` (the founder's own page). The validator accepts exactly
    these three forms, so the counts always sum to the findings."""
    u = url.strip()
    if u == _INTERNAL_PROVENANCE:
        return "internal"
    if u.startswith("document:"):
        return "document"
    return "published"


_SOURCE_CLASS_LABEL = {
    "published": "from published sources",
    "internal": "from this analysis's own output",
    "document": "from your own documents",
}


def _adversarial_outcome(redteam: dict[str, Any] | None, skip_reason: str | None) -> str:
    """The ONE sentence for what the outside review found, said the same way everywhere it appears.

    By state, then by source class. It used to say "found N published sources" for every accepted
    finding; on a live run both findings were the analysis's own output, the sentence was false at
    the top of the report, and the model's chat paragraph partly consisted of correcting it.
    """
    if not _usable(redteam):
        if isinstance(skip_reason, str) and skip_reason in _RED_TEAM_SKIP_REASONS:
            return _RED_TEAM_SKIP_REASONS[skip_reason]
        return "No outside review ran; the report says why."
    findings = [f for f in _as_list(redteam.get("findings")) if isinstance(f, dict)]
    rejected = int(_as_dict(redteam.get("summary")).get("rejected") or 0)
    if not findings:
        if rejected:
            noun = "challenge" if rejected == 1 else "challenges"
            text = f"An outside review raised {rejected} {noun} but could evidence none of them."
        else:
            text = "An outside review ran against this analysis and found nothing it could evidence."
    else:
        counts: dict[str, int] = {}
        for f in findings:
            cls = _source_class(str(f.get("source_url") or ""))
            counts[cls] = counts.get(cls, 0) + 1
        n = len(findings)
        noun = "challenge" if n == 1 else "challenges"
        parts = [
            f"{counts[c]} {_SOURCE_CLASS_LABEL[c]}" for c in ("published", "internal", "document") if counts.get(c)
        ]
        text = f"An outside review raised {n} {noun}: {', '.join(parts)}."
    unread = [str(x) for x in _as_list(redteam.get("sources_unread")) if str(x).strip()]
    if unread:
        text += f" It did not open {', '.join(unread)}."
    return text


# A sentence ends at ". " before a capital. Splitting on ". " alone cut a live verdict at "i.e." and
# printed "... -- i.e (from deck.pdf, page 2)".
# A closing quote or bracket may follow the stop: "…rate yet.' The bottom-up…" is two sentences, and
# reading it as one carried an attribution from the first onto a multiple in the second.
_SENTENCE_END_RE = re.compile(r"\.[\"')\]\u2019\u201d]*\s+(?=[A-Z])")
_STOP_BEFORE_CLOSERS_RE = re.compile(r"\.+([\"')\]\u2019\u201d]*)$")


def _top_challenge(redteam: dict[str, Any] | None, sizing: Any = None, inputs: Any = None) -> str:
    """The most serious accepted finding, as one sentence with its provenance class."""
    if not _usable(redteam):
        return ""
    findings = [f for f in _as_list(redteam.get("findings")) if isinstance(f, dict)]
    for sev in ("high", "medium"):
        for f in findings:
            if f.get("severity") != sev:
                continue
            truth = str(f.get("what_is_true") or "").strip()
            end = _SENTENCE_END_RE.search(truth)
            # Cut after the stop and any quote it closes, then drop only the stop: splitting on the
            # break took the closing quote with it ("the 'blended average rate (from ...").
            first = _STOP_BEFORE_CLOSERS_RE.sub(r"\1", (truth[: end.end()] if end else truth).rstrip())
            first = checked_multiples(first, sizing, inputs)
            url = str(f.get("source_url") or "")
            cls = _source_class(url)
            where = _document_cite(url) if cls == "document" else _SOURCE_CLASS_LABEL[cls]
            where = f"from {where}" if cls == "document" else where
            claim = _humanize_claim(str(f.get("claim_attacked") or "").strip())
            return f"The most serious: {claim} — {first} ({where})."
    return ""


def _holds_up(claim: float, found: list[float], high: float | None = None) -> str:
    """Whether a stated figure holds up against what each build found, in the words the founder asked.

    Close is within CLOSE_AGREEMENT_PCT (of the nearest bound, or inside a stated range); the
    direction is named only when every build agrees on it.
    """
    close = [abs(d) <= CLOSE_AGREEMENT_PCT for d in (_range_delta(v, claim, high)[0] or 0.0 for v in found)]
    one = len(found) == 1
    if all(close):
        return "holds up against this analysis" if one else "holds up against both builds"
    if any(close):
        return "holds up against one build but not the other"
    if all(v < claim for v in found):
        return "does not hold up — " + ("this analysis comes in below it" if one else "both builds come in below it")
    if all(v > (high if high is not None else claim) for v in found):
        return "does not hold up — " + ("this analysis comes in above it" if one else "both builds come in above it")
    return "does not hold up — neither build comes close to it"


def _summary_verdict(
    sizing: dict[str, Any],
    provenance: dict[str, dict[str, Any]] | None,
    checklist: dict[str, Any] | None,
    redteam: dict[str, Any] | None,
    skip_reason: str | None,
    marks: dict[tuple[str, str], str],
    inputs: dict[str, Any] | None,
) -> tuple[str, set[str]]:
    """The paragraph a reader wants first, from fields only. Returns (text, metrics it stated).

    Measured on 2 of 2 hostloop runs: the model wrote this paragraph in chat -- what the deck
    claims against what each build found, how far the builds disagree, the sharpest challenge --
    with ratios it rounded itself. Nothing on the page carried it, so it had to. Every figure
    here is the table's figure with the table's mark; every delta is the producer's.
    """
    sentences: list[str] = []
    stated: set[str] = set()
    # The founder's question is "do my numbers hold up?". On 3/3 live runs the printed hand-over gave the
    # figures but no answer in that form, and the model wrote its own in chat first -- with reasons, and
    # twice a figure the analysis never produced. So the answer leads, from the comparison below.
    answers: list[str] = []
    approaches = [a for a in ("top_down", "bottom_up") if _as_dict(sizing.get(a))]
    label = {"top_down": "top-down", "bottom_up": "bottom-up"}
    claim_ccy = _as_dict(inputs).get("existing_claims_currency") if isinstance(inputs, dict) else None
    for metric in ("tam", "sam", "som"):
        claim_text = None
        for a in approaches:
            prov = _as_dict(_as_dict(_as_dict(provenance).get(a)).get(metric))
            raw = prov.get("deck_claim")
            comparable = prov.get("deck_claim_comparable")
            if raw is None:
                continue
            if _as_dict(prov.get("horizon_mismatch")):
                claim_text = (
                    f"You stated {metric.upper()} {claim_display(float(raw), _as_number(prov.get('deck_claim_high')))} "
                    f"for a different period than "
                    f"this analysis covers, so the two are not compared."
                )
                stated.add(metric)
                break
            comp = _as_number(comparable)
            raw_n = _as_number(raw)
            if comp is None or comp <= 0 or raw_n is None:
                break  # blocked (currency not stated) or not a comparable figure: the table says so
            high_n = _as_number(prov.get("deck_claim_high_comparable"))
            shown = claim_display(comp, high_n)
            if comp != raw_n and isinstance(claim_ccy, str) and claim_ccy:
                shown += f" (converted from {raw_n:,.0f} {claim_ccy})"
            values = [(x, _as_number(_as_dict(_as_dict(sizing.get(x)).get(metric)).get("value"))) for x in approaches]
            found = " and ".join(
                f"{_fmt_usd(v)}{marks.get((x, metric), '')} ({label[x]})" for x, v in values if v is not None
            )
            if not found:
                break
            claim_text = f"You stated {metric.upper()} {shown}; this analysis finds {found}."
            stated.add(metric)
            answers.append(
                f"the {metric.upper()} you stated ({claim_display(comp, high_n)}) "
                + _holds_up(comp, [v for _, v in values if v is not None], high_n)
            )
            break
        if claim_text:
            sentences.append(claim_text)
    comparison = _as_dict(sizing.get("comparison"))
    if len(approaches) == 2 and comparison:
        gaps = []
        for metric in ("tam", "sam", "som"):
            delta = _as_number(comparison.get(f"{metric}_delta_pct"))
            if delta is not None and delta > 30:
                factor = _params.gap_factor(comparison.get(f"top_down_{metric}"), comparison.get(f"bottom_up_{metric}"))
                gaps.append(f"{factor or _params.fmt_delta(delta)} on {metric.upper()}")
        if gaps:
            sentences.append(f"The two builds differ by {' and '.join(gaps)} — one approach likely has a flawed input.")
    sentences.append(_adversarial_outcome(redteam, skip_reason))
    top = _top_challenge(redteam, sizing, inputs)
    if top:
        sentences.append(top)
    if _usable(checklist):
        sentences.append(_self_check_line(checklist))
    if answers:
        sentences.insert(0, "Short answer: " + "; ".join(answers) + ".")
    return " ".join(sentences), stated


def _self_check_line(checklist: dict[str, Any]) -> str:
    """The one line a founder reads for the score, rendered ONCE and copied everywhere else.

    "<score>% (<pass>/<applicable> pass, ...)" -- NOT a bare "pass/total" fraction (e.g. "100/22"),
    which reads as a malformed ratio rather than 100% across 22 items. The closing message copies
    this string rather than re-deriving it, so the chat and the report cannot disagree.
    """
    summary = _as_dict(checklist.get("summary"))
    pass_ct = summary.get("pass", 0)
    fail_ct = summary.get("fail", 0)
    na_ct = summary.get("not_applicable", 0)
    total_ct = summary.get("total", pass_ct + fail_ct + na_ct)
    applicable_ct = total_ct - na_ct
    score_pct = summary.get("score_pct")
    if isinstance(score_pct, (int, float)):
        score_str = f"{int(score_pct)}" if float(score_pct) == int(score_pct) else f"{score_pct:.1f}"
        return f"Self-check: {score_str}% ({pass_ct}/{applicable_ct} pass, {fail_ct} fail, {na_ct} N/A)"
    return f"Self-check: {pass_ct} pass, {fail_ct} fail, {na_ct} N/A"


def _as_number(value: Any) -> float | None:
    """The value as a float when it is a real number, else None.

    `bool` is excluded deliberately: it is an int subclass, so a stray `True` would compare equal
    to 1 and could manufacture an identity out of nothing.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _factor_chain(assumption: dict[str, Any]) -> list[dict[str, Any]] | None:
    """The assumption's `factors` list if it is well-formed and has TWO OR MORE entries, else None.

    Well-formed: a list of objects each carrying a str `factor_id`, a finite numeric `value` (bool
    excluded, as everywhere else here), a str `source_id`, and an optional `role`. Anything else
    is "no chain" -- a malformed chain must read as UNSTRUCTURED, never crash compose, and never
    be graded as reconciling, because a chain we cannot parse is exactly as uncheckable as one
    that is absent.

    Two or more. A one-element list is the value under another name: on a live run that is exactly
    what arrived (`segment_pct` <- one factor of 0.3732), it reconciled trivially, and the report
    called the figure itemized.

    `role` defaults to `"multiplicand"`; the only other accepted value is `"divisor"`, which lets
    a derived figure be itemized as a RATIO (numerator multiplicands over denominator divisors --
    e.g. 15,000,000 / 52,800,000) rather than only as a chain of narrowing multiplicands. An
    additive decomposition was mis-encoded here once and caught only by the product check; an
    unrecognized `role` string is malformed the same way a missing `factor_id` is.
    """
    raw = assumption.get("factors")
    if not isinstance(raw, list) or len(raw) < 2:
        return None
    out: list[dict[str, Any]] = []
    for f in raw:
        if not isinstance(f, dict):
            return None
        fid, src = f.get("factor_id"), f.get("source_id")
        if not isinstance(fid, str) or not isinstance(src, str):
            return None
        val = _as_number(f.get("value"))
        if val is None or not math.isfinite(val):
            return None
        role = f.get("role", "multiplicand")
        if role not in ("multiplicand", "divisor"):
            return None
        out.append({"factor_id": fid, "value": val, "source_id": src, "role": role})
    return out


_PAIRED_SLOTS: tuple[tuple[str, str, str, str], ...] = (
    # metric, top-down input key, bottom-up input key, sizing block carrying them
    ("sam", "segment_pct", "serviceable_pct", "sam"),
    ("som", "share_pct", "target_pct", "som"),
)


def _shared_input_values(
    sizing: dict[str, Any] | None, validation: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    """Inputs the two builds share BY VALUE. Empty unless both approaches are present.

    Each item carries a founder-facing `detail` sentence and NO raw field name: these items reach
    `coaching_payload`, and a raw id in that payload is a defect the fleet has already fixed once.

    Tolerance is 1e-6 relative. This is an IDENTITY check, not a closeness one: an honest
    near-agreement of even 0.5% must not trip it -- that case is what the comparison caveat is for.
    """
    if not isinstance(sizing, dict):
        return []
    td = _as_dict(sizing.get("top_down"))
    bu = _as_dict(sizing.get("bottom_up"))
    if not td or not bu:
        return []
    found: list[dict[str, Any]] = []

    it = _as_number(_as_dict(_as_dict(td.get("tam")).get("inputs")).get("industry_total"))
    bu_tam_in = _as_dict(_as_dict(bu.get("tam")).get("inputs"))
    cc = _as_number(bu_tam_in.get("customer_count"))
    arpu = _as_number(bu_tam_in.get("arpu"))
    if it and cc is not None and arpu is not None and math.isclose(it, cc * arpu, rel_tol=1e-6):
        found.append(
            {
                "metric": "tam",
                "kind": "identity",
                "code": "SHARED_TAM_IDENTITY",
                "detail": (
                    f"Your {_humanize_param('industry_total')} equals "
                    f"{_humanize_param('customer_count')} \u00d7 {_humanize_param('arpu')} exactly, "
                    "so the two TAM figures are one computation, shown two ways."
                ),
            }
        )

    for metric, td_key, bu_key, block in _PAIRED_SLOTS:
        a = _as_number(_as_dict(_as_dict(td.get(block)).get("inputs")).get(td_key))
        b = _as_number(_as_dict(_as_dict(bu.get(block)).get("inputs")).get(bu_key))
        if a and b is not None and math.isclose(a, b, rel_tol=1e-6):
            found.append(
                {
                    "metric": metric,
                    "kind": "equal_value",
                    "code": "PAIRED_SLOT_SAME_VALUE",
                    "detail": (
                        f"{_humanize_param(td_key)} and {_humanize_param(bu_key)} carry the same "
                        f"value ({a:g}), so the two {metric.upper()} figures narrow by one "
                        "number, not two."
                    ),
                }
            )

    # Factor-level overlap. Value identity on the slot (above) could not see the motivating run:
    # 10.0 and 9.1 are different numbers whose chains share three of four factors. A factor counts
    # as shared when its `factor_id` matches, OR its (source_id, value) pair matches -- the same
    # figure under two names is still the same figure, while two coincidentally-equal fractions
    # from different sources are not. Reported as a list, never a threshold: one shared factor is
    # one shared factor, and the reader decides what it means.
    if isinstance(validation, dict):
        by_name = {a2.get("name"): a2 for a2 in _as_list(validation.get("assumptions")) if isinstance(a2, dict)}
        for metric, td_key, bu_key, _block in _PAIRED_SLOTS:
            # The chain of the research figure each input RESOLVED to, never of whatever shares the
            # input's name. An unstamped sizing has no such figure and contributes no chain.
            td_chain = _factor_chain(by_name.get(_ref_name(sizing, td_key)) or {})
            bu_chain = _factor_chain(by_name.get(_ref_name(sizing, bu_key)) or {})
            if not td_chain or not bu_chain:
                continue
            bu_ids = {f["factor_id"] for f in bu_chain}
            bu_pairs = {(f["source_id"], round(f["value"], 6)) for f in bu_chain}
            shared_ids = [
                f["factor_id"]
                for f in td_chain
                if f["factor_id"] in bu_ids or (f["source_id"], round(f["value"], 6)) in bu_pairs
            ]
            if not shared_ids:
                continue
            mass = 1.0
            for f in td_chain:
                if f["factor_id"] in shared_ids:
                    mass *= f["value"]
            found.append(
                {
                    "metric": metric,
                    "kind": "shared_factor",
                    "code": "SHARED_FACTOR_OVERLAP",
                    "shared": shared_ids,
                    "shared_mass": round(mass, 6),
                    "detail": (
                        f"The two {metric.upper()} builds share {len(shared_ids)} of the "
                        f"{len(td_chain)} figures they narrow by "
                        f"({', '.join(sid.replace('_', ' ') for sid in shared_ids)}), so they "
                        "differ only where the remaining figures do."
                    ),
                }
            )
    return found


# The ONLY reasons an adversarial review may be absent, and the sentence each one puts in front of
# the founder. A CLOSED ENUM, not free text, for four reasons -- the last is the one that decides it:
#   1. Free text lets the agent write a rationalization that READS like a reason ("not needed for
#      this analysis"), which is the exact move the gate exists to stop.
#   2. An enum is countable. "How often is the red team skipped, and why" is answerable across runs;
#      a corpus of prose is not.
#   3. An unknown value fails loudly here instead of passing through as plausible prose.
#   4. This text reaches a FOUNDER. An open reason is an un-reviewed founder-facing string written
#      by a sub-agent. Each value below maps to a sentence we wrote and can stand behind.
#
# DELIBERATELY ABSENT: any value meaning "it did not seem necessary". There is no market sizing
# whose figures are not worth attacking, so such a value would be the escape hatch this gate was
# built to close. Do not add one.
#
# `founder_declined` is a DECISION; the other two are FAILURES. They read differently on purpose --
# "you asked us not to" and "we tried and could not" are not the same disclosure.
_RED_TEAM_SKIP_REASONS: dict[str, str] = {
    "founder_declined": (
        "No adversarial review ran, because you asked us not to run one. Nothing in this report "
        "has been checked against an outside source that was trying to contradict it."
    ),
    "dispatch_failed": (
        "An adversarial review was attempted and did not complete, so nothing in this report has "
        "been checked against an outside source. This is a gap in the process, not a finding "
        "about your figures — it is worth re-running."
    ),
    "no_network_available": (
        "No adversarial review ran, because this run had no access to outside sources. Nothing "
        "here has been checked against published figures that might contradict it."
    ),
    "no_subagent_dispatch": (
        "No adversarial review ran, because this environment runs the whole analysis as a single "
        "agent and cannot dispatch a separate reviewer. Nothing here has been checked against an "
        "outside source that was trying to contradict it — running the same analysis in Claude "
        "Cowork or Claude Code can do that."
    ),
}


# Mirrors red_team.py's INTERNAL_PROVENANCE: a finding grounded in this run's own output.
_INTERNAL_PROVENANCE = "internal:analysis"


def _document_cite(url: str) -> str:
    """`document:<file>#page=<n>` -> "<file>, page <n>"; `document:<file>` -> "<file>"."""
    m = re.match(r"^document:([^#]+)(?:#page=(\d+))?$", url)
    if not m:
        return url[len("document:") :]
    return f"{m.group(1)}, page {m.group(2)}" if m.group(2) else m.group(1)


# Human-readable labels for the declared sizing_basis convention — see
# references/tam-sam-som-methodology.md §5.
_SIZING_BASIS_LABELS: dict[str, str] = {
    "current_year": "Current-year market size",
    "forecast_year": "Forecast-year market size",
    "mixed": "Mixed (current- and forecast-year figures)",
}


def _sizing_basis_label(value: Any) -> str:
    """Human-readable label for sizing_basis.

    Anything outside the three known tokens — including absence — renders as
    "Not declared" rather than defaulting to "current_year". An artifact
    produced before this field existed (or a run that never set it) has a
    genuinely undeclared basis; silently stamping "current_year" on it would
    assert a convention that was not actually in force when the figures were
    sourced.
    """
    if isinstance(value, str) and value in _SIZING_BASIS_LABELS:
        return _SIZING_BASIS_LABELS[value]
    return "Not declared"


def _resolve_sizing_basis(
    sizing: dict[str, Any] | None,
    inputs: dict[str, Any] | None,
) -> str | None:
    """Resolve the raw sizing_basis token.

    sizing.json is the artifact the figures actually came out of and is
    authoritative for which convention was used; inputs.json only carries the
    field at intake (Steps 2-3), so it is the fallback rather than the
    primary source.
    """
    if _usable(sizing):
        val = sizing.get("sizing_basis")
        if isinstance(val, str) and val:
            return val
    if _usable(inputs):
        val = inputs.get("sizing_basis")
        if isinstance(val, str) and val:
            return val
    return None


# --- inputs by reference: what the sizing consumed, re-checked -----------------------------------------


# How each integrity code may be answered. None of them is "edit the sizing or the record until the
# comparison agrees": a check whose remedy changes the thing it checks trains the edit.
INTEGRITY_REMEDY: dict[str, str] = {
    "SIZING_STALE": "producer_rerun",
    "SIZING_UNRESOLVABLE": "restore_to_baseline",
    "SIZING_ALTERED": "disclose",
    "RECORD_CHANGED_AFTER_REVIEW": "restore_to_baseline",
    "UNIT_CHANGED_AFTER_REJECTION": "disclose",
    # Re-piping the sensitivity is legitimate: its ranges are relative to the base, and the base now
    # comes from the sizing itself, so nothing about the answer is chosen by the one re-running it.
    "SENSITIVITY_STALE": "producer_rerun",
    # A self-check is judgement and cannot be recomputed; medium and disclosed, so there is nothing to
    # gain by forging the stamp rather than re-grading.
    "CHECKLIST_STALE": "redispatch",
    "SIZING_NOT_CHECKED": "redispatch",
    "INPUTS_USER_PROVIDED": "disclose",
    # A fact about the reviews, computed from their copies: the analysis changed after the first one.
    # Nothing clears it but restoring what the first review saw, which makes the first review the one
    # of the analysis as delivered again.
    "ANALYSIS_CHANGED_BETWEEN_REVIEWS": "disclose",
}


def stamped_provenance(sizing: Any) -> dict[str, Any] | None:
    """The producer's per-input provenance, or None for a sizing from before it was stamped."""
    if not isinstance(sizing, dict) or sizing.get("provenance_version") != 1:
        return None
    prov = sizing.get("input_provenance")
    return prov if isinstance(prov, dict) else None


def _stamped_grade(entry: Any) -> str | None:
    """The grade a stamped input lends its figure. The founder's own figure counts as sourced."""
    if not isinstance(entry, dict) or entry.get("kind") in (None, "not_checked"):
        return None
    cat = entry.get("category")
    if cat == _provenance.FOUNDER_STATED:
        return "sourced"
    return cat if cat in _provenance.CATEGORIES else None


def _same(a: Any, b: Any) -> bool:
    x, y = _as_number(a), _as_number(b)
    if x is None or y is None:
        return bool(a == b)
    return math.isclose(x, y, rel_tol=1e-9, abs_tol=1e-9)


def _recompute(sizing: dict[str, Any], stamped: dict[str, Any]) -> dict[str, Any] | None:
    """The figures the producer's own math gives from the values it recorded consuming."""
    import market_sizing  # the calculator itself: never a second copy of its formulas

    def consumed(name: str) -> Any:
        return _as_dict(stamped.get(name)).get("value_consumed")

    proj = _as_dict(sizing.get("projection_inputs"))
    growth, years = proj.get("growth_rate"), int(proj.get("years") or 0)
    out: dict[str, Any] = {}
    try:
        if isinstance(sizing.get("top_down"), dict):
            it, sp, sh = (consumed(n) for n in _params.TOP_DOWN_PARAMS)
            out["top_down"] = market_sizing.top_down(float(it), float(sp), float(sh), growth, years)
        if isinstance(sizing.get("bottom_up"), dict):
            cc, ar, sv, tg = (consumed(n) for n in _params.BOTTOM_UP_PARAMS)
            out["bottom_up"] = market_sizing.bottom_up(int(cc), float(ar), float(sv), float(tg), growth, years)
    except (TypeError, ValueError):
        return None
    if "top_down" in out and "bottom_up" in out and isinstance(sizing.get("comparison"), dict):
        out["comparison"] = market_sizing.compare(out["top_down"], out["bottom_up"])
    return out


def _figures_differ(sizing: dict[str, Any], recomputed: dict[str, Any]) -> bool:
    for approach, figures in recomputed.items():
        if approach == "comparison":
            continue
        have = _as_dict(sizing.get(approach))
        for metric in ("tam", "sam", "som"):
            if not _same(_as_dict(have.get(metric)).get("value"), _as_dict(figures.get(metric)).get("value")):
                return True
    return False


def _unit_rejections(analysis_dir: str, run_id: str | None) -> list[dict[str, Any]]:
    if not run_id:
        return []
    path = _os.path.join(analysis_dir, "handoff", run_id, "unit_rejections.json")
    try:
        with open(path, encoding="utf-8") as fh:
            rows = _json.load(fh)
    except (OSError, ValueError):
        return []
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


def _label(name: str, validation: Any) -> str:
    for a in _as_list(_as_dict(validation).get("assumptions")):
        if isinstance(a, dict) and a.get("name") == name and isinstance(a.get("label"), str) and a["label"].strip():
            return str(a["label"]).strip()
    return _humanize_param(name)


_AFTER_REVIEW = (
    "The analysis changed after the outside review in a way the review did not see ({what}). Either it goes "
    "back to what the review saw, or the founder decides on the change at Step 6d and it is reviewed once more."
)


def _review_saw_references(review_facts: dict[str, Any] | None) -> bool:
    """True when the review the founder is shown was taken of a sizing built from research references."""
    shown = _as_dict(_as_dict(review_facts).get("reviewed_shown"))
    return any(_as_dict(v).get("ref") for v in _as_dict(shown.get("sizing")).values())


def sizing_integrity(
    analysis_dir: str,
    run_id: str | None,
    sizing: Any,
    validation: Any,
    inputs: Any,
    *,
    reviewed: bool,
    review_facts: dict[str, Any] | None = None,
    methodology: Any = None,
) -> tuple[dict[str, Any] | None, list[tuple[str, str]]]:
    """Re-check a stamped sizing against the record and against its own math.

    Returns (the sizing to render, or None to render it as it is; [(code, founder-facing message)]).
    `reviewed` is True once an outside review exists: a change after it is reported as such, and
    re-running the sizing is then NOT offered, because it would adopt a change the review never saw.
    """
    stamped = stamped_provenance(sizing)
    if stamped is None:
        if reviewed and _review_saw_references(review_facts):
            return None, [
                (
                    "RECORD_CHANGED_AFTER_REVIEW",
                    _AFTER_REVIEW.format(what="the market figures are no longer taken from the research it reviewed"),
                )
            ]
        return None, []
    assert isinstance(sizing, dict)
    codes: list[tuple[str, str]] = []
    render: dict[str, Any] | None = None

    recomputed = _recompute(sizing, stamped)
    if recomputed is not None and _figures_differ(sizing, recomputed):
        render = {**sizing, **recomputed}
        codes.append(
            (
                "SIZING_ALTERED",
                "The market figures in the saved calculation were changed after it was calculated. This "
                "report shows the figures recalculated from the inputs it recorded using, not the changed "
                "ones. Nothing needs fixing to deliver it; it is disclosed because the saved file no longer "
                "matches its own inputs.",
            )
        )

    after_review: list[str] = []
    refs = sizing.get("input_refs")
    if isinstance(refs, dict) and refs:
        resolved, refusals = _provenance.resolve(
            refs, validation=validation, inputs=inputs, currency=str(sizing.get("currency") or "USD")
        )
        gone = sorted({str(r.get("param")) for r in refusals})
        if gone:
            names = ", ".join(_humanize_param(p) for p in gone)
            codes.append(
                (
                    "SIZING_UNRESOLVABLE",
                    f"{names}: the research figure the sizing was built from is no longer in the research "
                    f"record in a form that can be checked, so where the number came from can no longer be "
                    f"shown. "
                    + (
                        "It was reviewed as it was; the record should be put back as the review saw it."
                        if reviewed
                        else "Restore the figure the sizing named, or re-run the sizing step against the "
                        "research as it now stands."
                    ),
                )
            )
        moved = sorted(
            p
            for p, now in resolved.items()
            if not _same(now.get("value_consumed"), _as_dict(stamped.get(p)).get("value_consumed"))
        )
        # A grade moves without a value: listing a source raises one. The pages grade the research as it
        # stands, so a sizing graded otherwise would have the report contradict itself.
        regraded = sorted(
            p
            for p, now in resolved.items()
            if p not in moved and now.get("category") != _as_dict(stamped.get(p)).get("category")
        )
        if moved or regraded:
            ccy = str(sizing.get("currency") or "USD")

            def _shown(p: str, value: Any) -> str:
                return _params.format_value(_params.PARAM_UNITS[p], value, ccy)

            detail = "; ".join(
                [
                    f"{_humanize_param(p)} was {_shown(p, _as_dict(stamped.get(p)).get('value_consumed'))} "
                    f"and the research now gives {_shown(p, resolved[p].get('value_consumed'))}"
                    for p in moved
                ]
                + [f"how well {_humanize_param(p)} is sourced has changed" for p in regraded]
            )
            if reviewed:
                after_review.append(detail)
            else:
                codes.append(
                    (
                        "SIZING_STALE",
                        f"A research figure changed after the sizing was calculated ({detail}), so the market "
                        f"figures below were calculated from the earlier value. Re-run the sizing step so it "
                        f"uses the research as it now stands.",
                    )
                )

    if reviewed and review_facts:
        after_review.extend(_review_drift(sizing, validation, inputs, review_facts))
        between = review_changes(review_facts, validation, str(sizing.get("currency") or "USD"))
        if between:
            codes.append(
                (
                    "ANALYSIS_CHANGED_BETWEEN_REVIEWS",
                    "The analysis changed after the first outside review, and the review shown is of the "
                    f"changed analysis: {'; '.join(between)}.",
                )
            )
    if after_review:
        codes.append(("RECORD_CHANGED_AFTER_REVIEW", _AFTER_REVIEW.format(what="; ".join(dict.fromkeys(after_review)))))

    used = set()
    for entry in stamped.values():
        if isinstance(entry, dict):
            used |= set(_as_list(entry.get("entries")))
    current = {a.get("name"): a for a in _as_list(_as_dict(validation).get("assumptions")) if isinstance(a, dict)}
    flagged: set[str] = set()
    # Matched on the VALUE, not the name: the refused figure renamed as well as relabelled is still the
    # refused figure. A figure derived properly (count x price) uses the count as a count, so no match.
    for row in _unit_rejections(analysis_dir, run_id):
        if _as_number(row.get("value")) is None:
            continue
        for name in sorted(used):
            now = current.get(name)
            if name in flagged or not isinstance(now, dict):
                continue
            if not (_same(now.get("value"), row.get("value")) and now.get("unit") != row.get("unit")):
                continue
            flagged.add(name)
            was_unit = str(row.get("unit"))
            now_unit = str(now.get("unit"))
            codes.append(
                (
                    "UNIT_CHANGED_AFTER_REJECTION",
                    f"{_label(name, validation)}: the calculator refused this figure "
                    f"({_params.format_value(was_unit, row.get('value'))}) "
                    f"because it measured {_provenance._UNIT_WORDS.get(was_unit, was_unit)}, not what the "
                    f"sizing needed. It was then relabelled as {_provenance._UNIT_WORDS.get(now_unit, now_unit)} "
                    f"with the same value, and the sizing uses it. A number does not change what it measures "
                    f"when it is relabelled; check this figure before relying on the result.",
                )
            )
    return render, codes


def _now_state(sizing: dict[str, Any], validation: Any, inputs: Any) -> dict[str, Any]:
    refs = _as_dict(sizing.get("input_refs"))
    out: dict[str, Any] = {"sizing": {}, "record": _provenance.record_snapshot(validation, inputs)}
    for param, entry in _as_dict(stamped_provenance(sizing)).items():
        e = _as_dict(entry)
        out["sizing"][param] = {
            "ref": refs.get(param),
            "value_consumed": e.get("value_consumed"),
            "entries": list(e.get("entries") or []),
        }
    return out


# A reference's prose is not what it computes. A live run's founder chose to deliver; the founder-text
# check then flagged a file name inside an estimate's `why`, and rewording it fired
# RECORD_CHANGED_AFTER_REVIEW because the whole reference was compared. That check's remedies were to put
# the file name back or to re-review, which the founder had declined -- and the model wrote the founder's
# approval itself. Two checks whose remedies conflict leave only a forgery. One owner for the stripping:
# _provenance, which the sizing fingerprint uses too.
_computed = _provenance._without_prose


def _state_changes(before: Any, after: Any) -> list[tuple[str, str]]:
    """[(kind, name)] that differ between two review snapshots: "param" or "entry"."""
    b, a = _as_dict(before), _as_dict(after)
    changed: list[tuple[str, str]] = []
    bs, as_ = _as_dict(b.get("sizing")), _as_dict(a.get("sizing"))
    for param in sorted(set(bs) | set(as_)):
        x, y = _as_dict(bs.get(param)), _as_dict(as_.get(param))
        if _computed(x.get("ref")) != _computed(y.get("ref")) or not _same(
            x.get("value_consumed"), y.get("value_consumed")
        ):
            changed.append(("param", param))
    used = {e for s in (bs, as_) for v in s.values() for e in _as_list(_as_dict(v).get("entries"))}
    br, ar = _as_dict(b.get("record")), _as_dict(a.get("record"))
    for name in sorted(used):
        if _as_dict(br.get(name)) != _as_dict(ar.get(name)):
            changed.append(("entry", name))
    return changed


def _describe(change: tuple[str, str], validation: Any) -> str:
    kind, name = change
    if kind == "param":
        return _humanize_param(name)
    if name.startswith("founder:"):
        return f"your {_humanize_param(name.split(':', 1)[1])}"
    return _label(name, validation)


def _review_drift(sizing: dict[str, Any], validation: Any, inputs: Any, facts: dict[str, Any]) -> list[str]:
    """What changed after the review the founder is shown."""
    shown = facts.get("reviewed_shown")
    out: list[str] = []
    if isinstance(shown, dict):
        for change in _state_changes(shown, _now_state(sizing, validation, inputs)):
            out.append(f"{_describe(change, validation)} is not what the review saw")
    return out


def review_matcher(sizing: Any, validation: Any, inputs: Any) -> Any:
    """`inputs_reviewed` -> whether that review was taken of the analysis as it now stands."""
    now = _now_state(_as_dict(sizing), validation, inputs)

    def same(reviewed: Any) -> bool:
        return isinstance(reviewed, dict) and not _state_changes(reviewed, now)

    return same


def _exact(param: str, value: Any, currency: str) -> str:
    """A changed input, precisely enough that a small edit is visible: "$1,884 a year", "37%"."""
    unit = _params.PARAM_UNITS.get(param)
    v = _as_number(value)
    if v is None:
        return "—"
    if unit in _params.MONEY_UNITS:
        symbol = "$" if currency == "USD" else f"{currency} "
        shown = f"{symbol}{v:,.2f}".rstrip("0").rstrip(".")
        return shown + (" a year" if unit == _params.MONEY_PER_CUSTOMER else "")
    return _params.format_value(unit, v, currency)


def review_changes(facts: dict[str, Any], validation: Any, currency: str) -> list[str]:
    """What differs between the first review and the one shown, from the two copies alone."""
    first, shown = facts.get("reviewed_first"), facts.get("reviewed_shown")
    if (facts.get("round_shown") or 0) <= 1 or not isinstance(first, dict) or not isinstance(shown, dict):
        return []
    changes = _state_changes(first, shown)
    fs, ss = _as_dict(first.get("sizing")), _as_dict(shown.get("sizing"))
    covered = {e for kind, name in changes if kind == "param" for e in _as_list(_as_dict(ss.get(name)).get("entries"))}
    lines = []
    for kind, name in changes:
        if kind == "param":
            was = _as_dict(fs.get(name)).get("value_consumed")
            now = _as_dict(ss.get(name)).get("value_consumed")
            if _same(was, now):
                lines.append(f"{_humanize_param(name)}: now built from a different figure, same value")
            else:
                lines.append(
                    f"{_humanize_param(name)}: {_exact(name, was, currency)} \u2192 {_exact(name, now, currency)}"
                )
        elif name not in covered:
            lines.append(f"{_describe((kind, name), validation)}: revised")
    return lines


def review_note(facts: dict[str, Any]) -> str | None:
    """The one line about the reviews, each clause computed from the copies. None for a single review."""
    rounds = int(facts.get("rounds") or 0)
    if rounds <= 1 or facts.get("round_shown") is None:
        return None
    later = facts.get("later") or []
    if not facts.get("matched"):
        return (
            f"The outside review ran {rounds} times, and none of them was of the analysis as delivered; "
            "the latest is shown."
        )
    if facts.get("all_match"):
        return f"The outside review ran {rounds} times on the analysis as delivered; the first is shown" + (
            ", and the later ones are listed after it." if later else "."
        )
    if (facts.get("round_shown") or 0) > 1:
        return (
            f"The outside review ran {rounds} times. The analysis changed after the first review, and the "
            "review below is the first of the analysis as delivered."
            + (" Later reviews of it are listed after it." if later else "")
        )
    return (
        f"The outside review ran {rounds} times; the one below is of the analysis as delivered, and a later "
        "review was of a version of it that was not delivered."
    )


def _built_from(names: set[str], validation: dict[str, Any]) -> set[str]:
    """`names` plus every record entry they are built from, through `factors[].factor_id`, transitively.

    A live report labelled a population and a rate "research context; not used in the sizing" while
    their product was the customer count the sizing consumed: the sizing named the derived figure,
    and nothing followed its factors. Followed by `factor_id` alone, not by `_factor_chain`, whose
    stricter shape that run's factors failed -- a malformed chain must not bring the label back.
    """
    factors: dict[str, list[str]] = {}
    for a in _as_list(validation.get("assumptions")):
        if isinstance(a, dict) and isinstance(a.get("name"), str):
            factors[a["name"]] = [
                str(f["factor_id"])
                for f in _as_list(a.get("factors"))
                if isinstance(f, dict) and isinstance(f.get("factor_id"), str)
            ]
    out, todo = set(names), list(names)
    while todo:
        for child in factors.get(todo.pop(), []):
            if child not in out:
                out.add(child)
                todo.append(child)
    return out


def _founder_text_policy() -> Any:
    """The fleet's shared founder-text policy, imported parent-relative from `founder-skills/scripts/`.

    Same contract as compose's copy: None when unavailable, because a missing policy module must never
    block a report.
    """
    try:
        shared = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "scripts"))
        if shared not in sys.path:
            sys.path.insert(0, shared)
        import _founder_text  # type: ignore[import-not-found]

        return _founder_text
    except ImportError:
        return None


def _founder_prose(text: str) -> str:
    """Sub-agent-authored prose, with our own vocabulary taken out of it.

    compose substitutes the whole markdown document through the policy; visualize never referenced it,
    so a record identifier a sub-agent wrote into an estimate's reason was repaired on report.md and
    shipped raw in report.html -- the same sentence reading two ways on two delivered pages. Applied
    here, at the one owner both renderers read these rows from, rather than as a second policy copy in
    the renderer. Idempotent, so compose's later document-wide pass is unaffected.
    """
    ft = _founder_text_policy()
    if ft is None:
        return text
    try:
        return str(ft.substitute(text))
    except Exception:
        return text


def assumption_rows(validation: Any, sizing: Any) -> list[dict[str, Any]]:
    """Every figure the pages list as research or estimate, each with the grade it earned.

    report.md's Assumptions section and report.html's confidence chart both render these rows, so the
    two pages cannot grade one figure two ways. A record entry is graded by what it earned
    (`_provenance.entry_grade`), never by the category it claims. For a stamped sizing, `used` says
    whether the sizing consumed the entry, and each estimate the sizing used in place of research is a
    row of its own.
    """
    v = _as_dict(validation)
    if not v or _is_stub(v):
        return []
    stamped = stamped_provenance(sizing)
    used: set[str] = set()
    for entry in (stamped or {}).values():
        used |= {str(x) for x in _as_list(_as_dict(entry).get("entries"))}
    used = _built_from(used, v)
    # A figure the FOUNDER stated is stamped with a synthetic `founder:<key>` entry, so a record entry
    # holding that same figure is in no `entries` list and the factor walk cannot reach it -- it has no
    # factors. A live report told a founder the per-customer price their whole bottom-up build rested on
    # was "not used in the sizing". The producer decides which entries ARE that figure, by comparing the
    # figure and not the name (`_provenance._same_figure_entries`); this only reads the answer, and only
    # for this label -- widening `entries` would make an edit to a merely-equal entry read as a change
    # to the reviewed analysis, and would silence FOUNDER_VALUE_OVERRIDDEN.
    # An estimate inside a derivation can carry a recorded figure too, so the answer is read at every
    # depth, not only where the sizing names a parameter.
    todo = list((stamped or {}).values())
    while todo:
        node = _as_dict(todo.pop())
        used |= {str(x) for x in _as_list(node.get("same_figure_entries"))}
        todo.extend(_as_list(node.get("factors")))
    rows: list[dict[str, Any]] = [
        {
            "kind": "record",
            "entry": a,
            "grade": _provenance.entry_grade(a, v),
            "used": (a.get("name") in used) if stamped is not None else None,
        }
        for a in _as_list(v.get("assumptions"))
        if isinstance(a, dict)
    ]
    for param, entry in sorted((stamped or {}).items()):
        e = _as_dict(entry)
        if e.get("kind") != "estimate":
            continue
        unit = _params.PARAM_UNITS.get(param)
        note = str(e.get("why") or "").strip()
        if e.get("research_value") is not None:
            research = _params.format_value(unit, e.get("research_value"), _CURRENCY)
            note += f" The research recorded {research}; the sizing used this estimate instead."
        rows.append(
            {
                "kind": "estimate",
                "param": param,
                "label": _humanize_param(param),
                "shown": _params.format_value(unit, e.get("value_consumed"), _CURRENCY),
                "grade": "agent_estimate",
                "note": _founder_prose(note),
            }
        )
    return rows


def downstream_staleness(sizing: Any, sensitivity: Any, checklist: Any, inputs: Any = None) -> list[tuple[str, str]]:
    """The steps built on the sizing must say which sizing they were built on, and it must be this one.

    Only for a stamped sizing. A missing stamp is not "current": absence never upgrades. A checklist also
    stamped with the inputs it read (`checklist.py --inputs`) is stale when they have changed since.
    """
    codes: list[tuple[str, str]] = _inputs_staleness(checklist, inputs)
    current = _provenance.sizing_fingerprint(sizing)
    if current is None:
        return codes

    def built_on(doc: Any) -> Any:
        return _as_dict(_as_dict(doc).get("graded_against")).get("sizing.json")

    if isinstance(sensitivity, dict) and not _is_stub(sensitivity) and built_on(sensitivity) != current:
        codes.append(
            (
                "SENSITIVITY_STALE",
                "The sensitivity table was calculated for a different version of the sizing than the one "
                "this report shows, so its ranges may not match the figures above. Re-run the sensitivity "
                "step on the current sizing.",
            )
        )
    if (
        isinstance(checklist, dict)
        and not _is_stub(checklist)
        and built_on(checklist) != current
        and not any(c == "CHECKLIST_STALE" for c, _ in codes)
    ):
        codes.append(
            (
                "CHECKLIST_STALE",
                "This self-check was graded against a different version of the sizing than the one this report shows.",
            )
        )
    return codes


def _inputs_staleness(checklist: Any, inputs: Any) -> list[tuple[str, str]]:
    stamped = _as_dict(_as_dict(checklist).get("graded_against")).get("inputs.json")
    if not isinstance(checklist, dict) or _is_stub(checklist) or not stamped or not isinstance(inputs, dict):
        return []
    if stamped == _provenance.inputs_fingerprint(inputs):
        return []
    return [("CHECKLIST_STALE", "This self-check was graded against an earlier version of your inputs.")]


def _ref_name(sizing: Any, param: str) -> str | None:
    """The research record entry a stamped input resolved to directly, or None."""
    entry = _as_dict(_as_dict(stamped_provenance(sizing)).get(param))
    return str(entry["name"]) if entry.get("kind") == "assumption" and entry.get("name") else None


def input_grades(sizing: Any, validation: Any) -> dict[str, dict[str, Any]]:
    """{input: {"category", "confidence"}} from what the sizing stamped, never from a name match.

    `confidence` is the record entry's own, for an input that references one directly.
    """
    by_name = {a.get("name"): a for a in _as_list(_as_dict(validation).get("assumptions")) if isinstance(a, dict)}
    out: dict[str, dict[str, Any]] = {}
    for param, entry in _as_dict(stamped_provenance(sizing)).items():
        grade = _stamped_grade(entry)
        if grade is None:
            continue
        name = _ref_name(sizing, param)
        out[param] = {"category": grade, "confidence": _as_dict(by_name.get(name)).get("confidence") if name else None}
    return out


def _numbers_in(value: Any) -> list[float]:
    if isinstance(value, bool):
        return []
    if isinstance(value, (int, float)):
        return [float(value)]
    if isinstance(value, dict):
        return [x for v in value.values() for x in _numbers_in(v)]
    if isinstance(value, list):
        return [x for v in value for x in _numbers_in(v)]
    return []


def unchecked_sizing(
    sizing: Any, validation: Any, inputs: Any, *, review_facts: dict[str, Any] | None = None
) -> list[tuple[str, str]]:
    """A sizing whose inputs were typed in rather than resolved from the research record.

    With a real research record, that is SIZING_NOT_CHECKED (high): nothing ties the figures to their
    sources, and skipping the references would otherwise be the cheapest way past every check above.
    With no research (a stub record, pure calculation) and every figure the founder's own, it is an
    honest disclosure, INPUTS_USER_PROVIDED (medium). A stub with any figure that is NOT the founder's
    is an unchecked sizing like any other.

    After a review taken of references, typed numbers are a change the review never saw; that is
    `sizing_integrity`'s RECORD_CHANGED_AFTER_REVIEW, and re-running the sizing is not its remedy.
    """
    if not isinstance(sizing, dict) or _is_stub(sizing) or _review_saw_references(review_facts):
        return []
    stamped = stamped_provenance(sizing)
    kinds = {_as_dict(v).get("kind") for v in (stamped or {}).values()}
    if stamped is not None and "not_checked" not in kinds and kinds:
        return []
    v = _as_dict(validation)
    no_research = not v or bool(v.get("skipped"))
    if no_research:
        stated = _numbers_in(_as_dict(inputs).get("founder_stated_inputs"))
        stated += _numbers_in(_as_dict(inputs).get("existing_claims"))
        stated += _numbers_in(_as_dict(inputs).get("existing_claims_detail"))
        consumed = [_as_number(_as_dict(e).get("value_consumed")) for e in (stamped or {}).values()]
        if consumed and all(c is not None and any(_same(c, x) for x in stated) for c in consumed):
            return [
                (
                    "INPUTS_USER_PROVIDED",
                    "These figures are the ones you gave; no outside research was done, so nothing here "
                    "checked them against a source.",
                )
            ]
    return [
        (
            "SIZING_NOT_CHECKED",
            "The market figures were calculated from numbers entered directly rather than from the "
            "research this analysis recorded, so nothing links them to their sources. Re-run the "
            "sizing step so it takes each figure from the research.",
        )
    ]


def _fmt_param_value(name: str, value: Any) -> str:
    """Unit-aware formatting for a sensitivity parameter's input value.

    The Value column holds the parameter itself, not a market-size figure, so its unit varies:
    percentages (``*_pct``), counts (``*_count``), and currency (everything else, e.g. ``arpu``,
    ``industry_total``). Formatting all three the same way (the old behavior — USD for low/high,
    raw number for base) renders percents and counts as dollars and leaves base inconsistent.
    """
    if not isinstance(value, (int, float)):
        return "—"
    if _params.unit_of(name) is not None:
        return _params.format_value(_params.unit_of(name), value, _CURRENCY)
    # A parameter the sizing does not define: its unit can only be guessed from its name.
    lname = name.lower()
    if lname.endswith("_pct") or "pct" in lname or "percent" in lname or "share" in lname or "rate" in lname:
        return _params.fmt_percent(value)
    if (
        "count" in lname
        or "customers" in lname
        or "users" in lname
        or "establishments" in lname
        or lname.startswith("num_")
        or lname.endswith("_num")
    ):
        return _params.fmt_number(int(value) if float(value).is_integer() else value)
    return _fmt_usd(float(value))


# A founder's figure names the page it came from only when its own words are on that page. The
# labels are the model's: a live run labelled two deck figures "chat", and the report told the
# founder they had typed them. Nothing a script can read shows what the founder typed, so a chat
# label names nothing; a document label names its page only when its words are found there.
_DOC_CITE_RE = re.compile(r"^document:([^#/\\]+)(?:#page=([1-9]\d*))?$")
# The red team's floor for a document quote: a three-word "quote" matches almost any page.
_MIN_DOC_QUOTE_WORDS = 6
# red_team.py's floor for a usable text layer; _page_text below is its copy and reads it.
_TEXT_LAYER_FLOOR = 100


def _page_text(uploads_dir: str | None, ocr_dir: str | None, filename: str, page: int) -> str | None:
    """Text of one page: the text layer if it has one, else the OCR sidecar, else None."""
    if not uploads_dir:
        return None
    path = os.path.join(uploads_dir, filename)
    if filename.lower().endswith((".md", ".txt")):
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                return fh.read()
        except OSError:
            return None
    try:
        import pdfplumber  # optional at runtime; absent means "no text layer here"

        with pdfplumber.open(path) as pdf:
            if 1 <= page <= len(pdf.pages):
                text = pdf.pages[page - 1].extract_text() or ""
                if len(text.strip()) >= _TEXT_LAYER_FLOOR:
                    return text
    except Exception:  # noqa: BLE001 -- any failure here means "no text layer", never a crash
        pass
    if ocr_dir:
        sidecar = os.path.join(ocr_dir, f"{filename}.p{page}.txt")
        if os.path.isfile(sidecar):
            try:
                with open(sidecar, encoding="utf-8", errors="replace") as fh:
                    return fh.read()
            except OSError:
                return None
    return None


def _handoff_page_dirs(analysis_dir: str | None) -> list[tuple[str, str]]:
    """(docs, ocr) pairs under the analysis's hand-off dirs: where Step 6c mirrors the founder's
    documents and writes their OCR. Round 2 reuses round 1's, so any run's pair is a candidate.

    On the cloud lane the mirrored name can carry the upload prefix; a label that names the
    display name then finds no page and renders unnamed, which is the safe failure.
    """
    if not analysis_dir:
        return []
    root = os.path.join(analysis_dir, "handoff")
    if not os.path.isdir(root):
        return []
    return [
        (os.path.join(root, run, "docs"), os.path.join(root, run, "ocr"))
        for run in sorted(os.listdir(root))
        if os.path.isdir(os.path.join(root, run, "docs")) or os.path.isdir(os.path.join(root, run, "ocr"))
    ]


def _quote_on_page(analysis_dir: str | None, filename: str, page: int, quote: str) -> bool:
    if len(quote.split()) < _MIN_DOC_QUOTE_WORDS:
        return False
    for docs, ocr in _handoff_page_dirs(analysis_dir):
        text = _page_text(docs, ocr, filename, page)
        if text is not None and quote_in_doc(quote, text)[0]:
            return True
    return False


def _stated_figure(
    field: str, value: Any, period: Any, source: Any, label: Any = None, analysis_dir: str | None = None
) -> str:
    """ "ARPU $261.00 per month (from deck.pdf, page 2: <its words>)" -- one founder figure.

    The page is named only when `label`, the document's own words, is found on it. Otherwise a
    document figure is "in your materials", and a figure labelled chat carries no source at all.
    """
    amount = _fmt_param_value(field, value)
    per = f" per {period}" if isinstance(period, str) and period.strip() else ""
    src = str(source or "").strip()
    words = str(label).strip() if isinstance(label, str) else ""
    note = f": {words}" if words else ""
    doc = _DOC_CITE_RE.match(src)
    if doc and words and _quote_on_page(analysis_dir, doc.group(1), int(doc.group(2) or 1), words):
        tail = f" (from {_document_cite(src)}{note})"
    elif src and src != "chat":
        tail = f" (in your materials{note})"
    else:
        tail = f" ({words})" if words else ""
    return f"{_humanize_param(field)} {amount}{per}{tail}"


def _stated_alternatives(
    inputs: dict[str, Any] | None, analysis_dir: str | None = None, gate_view: dict[str, Any] | None = None
) -> list[str]:
    """One line per founder-stated figure the analysis did NOT use, beside the one it did.

    A founder whose materials state two figures for one input (a recurring rate in chat, a blended
    rate in the deck) is asked which the sizing uses; the other is kept and shown, never dropped.
    """
    i = _as_dict(inputs)
    stated = _as_dict(i.get("founder_stated_inputs"))
    periods = _as_dict(i.get("founder_stated_inputs_period"))
    sources = _as_dict(i.get("founder_stated_inputs_source"))
    # A choice is claimed only when the founder's answer is recorded. Measured: the question was
    # skipped and the report still said "the one you chose". A source alone is not a choice -- the
    # analysis knows where a figure came from whether or not anyone asked.
    chosen = _as_dict(i.get("founder_stated_choice"))
    lines: list[str] = []
    for field, alts in _as_dict(i.get("founder_stated_alternatives")).items():
        for alt in _as_list(alts):
            if not isinstance(alt, dict) or not isinstance(alt.get("value"), (int, float)):
                continue
            other = _stated_figure(
                field, alt["value"], alt.get("period"), alt.get("source"), alt.get("label"), analysis_dir
            )
            if field in stated:
                used = _stated_figure(field, stated[field], periods.get(field), sources.get(field), None, analysis_dir)
                rec = _as_dict((gate_view or {}).get(f"ms_two_figures.{field}")) if gate_view is not None else None
                if rec is not None and rec.get("by_request"):
                    lines.append(
                        f"You also gave {other}; this analysis uses {used}, the one the request that started "
                        "this analysis named."
                    )
                elif (rec is not None and rec.get("resolution") == "answered") or (
                    gate_view is None and str(chosen.get(field) or "").strip()
                ):
                    lines.append(f"You also gave {other}; this analysis uses {used}, the one you chose.")
                else:
                    lines.append(
                        f"You also gave {other}; this analysis used {used}, and you were not asked which to use."
                    )
            else:
                lines.append(f"You also gave {other}.")
    return lines


# How "Your Answers" names a question the run's ledger shows was not put to the founder.
_GATE_NAMES = {
    "ms_methodology": "the sizing approach",
    "ms_pct_scale": "whether a share was meant as a percent",
    "ms_revision": "whether to revise the challenged inputs",
    "ms_fx_rate": "the exchange rate",
    "ms_upload_path": "where your documents are",
}


def _gate_name(key: str, rec: dict[str, Any]) -> str:
    return _GATE_NAMES.get(key.partition(".")[0]) or str(rec.get("form_label") or "a question").lower()


def _ledger_answer_lines(gate_view: dict[str, Any]) -> list[str]:
    """With a run ledger: the questions the request answered (its instruction, never the founder's
    confirmation) and those not asked because the founder asked not to be asked. The two-figures question
    is stated beside its figures instead."""
    asked_for: list[str] = []
    defaults: list[str] = []
    for key in sorted(gate_view):
        rec = _as_dict(gate_view[key])
        if key.startswith("ms_two_figures."):
            continue
        if rec.get("by_request"):
            if key == "ms_methodology":
                asked_for.append(
                    "The sizing approach was not put to you as a question: the request that started this "
                    "analysis accepted it."
                )
            elif key == "ms_revision" and rec.get("answer_id") == "deliver":
                asked_for.append(
                    "The request that started this analysis chose to deliver it with the outside review's "
                    "challenges shown, instead of a revision round."
                )
            else:
                asked_for.append(f"The request that started this analysis answered {_gate_name(key, rec)} for you.")
        elif rec.get("resolution") == "default_taken" and rec.get("default_reason") == "asked_not_to_be_asked":
            defaults.append(_gate_name(key, rec))
    if defaults:
        asked_for.append(f"No question was asked for these; the default was taken: {', '.join(defaults)}.")
    return asked_for


def _your_answers_lines(
    methodology: dict[str, Any] | None,
    inputs: dict[str, Any] | None,
    analysis_dir: str | None = None,
    gate_view: dict[str, Any] | None = None,
) -> list[str]:
    """The "Your Answers" lines, for report.md and report.html alike.

    The disclosure that the founder was not asked which figure to use lived only in report.md; the
    HTML page, a second renderer nobody reads, said nothing. One owner, two renderers.
    """
    m = _as_dict(methodology)
    notes = [str(n).strip() for n in _as_list(m.get("founder_notes")) if str(n).strip()]
    # `gate_defaults` is string[]. A live run wrote objects, and str() printed their repr, internal
    # ids included, to the founder; an entry that is not a phrase is counted, never printed.
    raw_defaults = _as_list(m.get("gate_defaults"))
    defaults = [g.strip() for g in raw_defaults if isinstance(g, str) and g.strip()]
    unnamed = sum(1 for g in raw_defaults if not isinstance(g, str))
    if gate_view is not None:
        # The run's ledger is the record of what was asked: `gate_defaults` and `founder_stated_choice`, which
        # the model writes, are not read.
        return _stated_alternatives(inputs, analysis_dir, gate_view) + notes + _ledger_answer_lines(gate_view)
    lines = _stated_alternatives(inputs, analysis_dir) + notes
    if defaults or unnamed:
        named = ", ".join(defaults)
        if unnamed:
            other = (
                f"{unnamed} other question{'s' if unnamed != 1 else ''}"
                if defaults
                else (f"{unnamed} question{'s' if unnamed != 1 else ''}")
            )
            named = f"{named} and {other}" if named else other
        lines.append(f"You asked not to be asked questions, so the default was taken for: {named}.")
    return lines


# --- a multiple the red team attributes to the analysis --------------------------------------------
#
# A live round-2 review wrote that "the analysis's own bottom-up build separately estimates … at
# roughly 5x this figure", and the coaching repeated it to the founder as a fact about their build.
# The bottom-up TAM was 0.51x the top-down. `what_is_true` is free prose, checked nowhere.
#
# Calibrated before it was written, over the 15 kept red-team outputs (52 findings, 7 multiples): the
# check fires on exactly one, the defect. It looks only at a multiple in a sentence that attributes it
# to the analysis's own build, and compares like with like -- one metric across the two builds, a
# figure against the founder's claim for it, a figure the sentence quotes against the analysis's. All
# pairs of all figures would match almost any N (run 1's bottom-up TAM/SAM is exactly 5.0).

_MULTIPLE_CAVEAT = (
    "(This multiple is the reviewer's own arithmetic: none of this analysis's figures, or the figures "
    "quoted here, stand in that ratio.)"
)
_MULTIPLE_RE = re.compile(r"(?<![\w.$€£₹])~?(\d[\d,]*(?:\.\d+)?)\s?[x×](?![\w\d])")
_QUOTED_RE = re.compile(r"(?<![\w.])[$€£₹]\s?(\d[\d,]*(?:\.\d+)?)\s*([KMB]|bn|mn)?\b")
_SCALE = {None: 1.0, "K": 1e3, "M": 1e6, "B": 1e9, "bn": 1e9, "mn": 1e6}
_ATTRIBUTED_RE = re.compile(
    r"\b(?:analysis'?s own|your own (?:bottom-up|top-down)|the (?:analysis'?s? )?(?:bottom-up|top-down) build)\b",
    re.IGNORECASE,
)
_MULTIPLE_TOLERANCE = 1.25  # "roughly 5x" is 4x to 6.25x


def _supported_ratios(sentence: str, sizing: Any, inputs: Any) -> list[float]:
    s, claims = _as_dict(sizing), _as_dict(_as_dict(inputs).get("existing_claims"))
    by_metric: dict[str, list[float]] = {}
    for metric in ("tam", "sam", "som"):
        for approach in ("top_down", "bottom_up"):
            v = _as_number(_as_dict(_as_dict(s.get(approach)).get(metric)).get("value"))
            if v and v > 0:
                by_metric.setdefault(metric, []).append(v)
        c = _as_number(claims.get(metric))
        if c and c > 0:
            by_metric.setdefault(metric, []).append(c)
    quoted = [
        float(m.group(1).replace(",", "")) * _SCALE[m.group(2)]
        for m in _QUOTED_RE.finditer(sentence)
        if float(m.group(1).replace(",", "")) > 0
    ]
    everything = [v for vs in by_metric.values() for v in vs]
    pairs = [(a, b) for vs in by_metric.values() for a in vs for b in vs if a is not b]
    pairs += [(q, v) for q in quoted for v in everything + quoted if q != v]
    return [max(a, b) / min(a, b) for a, b in pairs]


def checked_multiples(text: str, sizing: Any, inputs: Any = None) -> str:
    """`text` with _MULTIPLE_CAVEAT after any sentence that attributes to the analysis a multiple none of
    its figures stand in. Unchanged otherwise, and unchanged when there is no sizing to check against."""
    if not text or not _as_dict(sizing):
        return text
    out, start = [], 0
    for sentence_end in [m.start() + 1 for m in _SENTENCE_END_RE.finditer(text)] + [len(text)]:
        sentence = text[start:sentence_end]
        out.append(sentence)
        if _ATTRIBUTED_RE.search(sentence):
            ratios = _supported_ratios(sentence, sizing, inputs)
            for m in _MULTIPLE_RE.finditer(sentence):
                n = float(m.group(1).replace(",", ""))
                if n > 1 and not any(max(n, r) / min(n, r) <= _MULTIPLE_TOLERANCE for r in ratios):
                    out.append(" " + _MULTIPLE_CAVEAT)
                    break
        start = sentence_end
    return "".join(out)
