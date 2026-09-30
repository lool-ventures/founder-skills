"""Resolve a sizing input from WHERE it comes from into the value the math consumes.

A sizing hand-off does not carry numbers. Each input names its origin:

    {"assumption": "<validation.json assumption name>"}      a researched figure
    {"founder_stated": "arpu"}                                the founder's own figure
    {"derived": {"op": "multiply"|"divide"|"to_percent"|"to_fraction", "factors": [<ref>, ...]}}
    {"estimate": <n>, "unit": "<unit>", "why": "<one sentence>"}

and this module produces the value, its unit, how it was normalised (period, currency, rounding),
its grade, and which record entries it depends on. There is one copy of every figure, in the
record, so there is no second copy to disagree with, and nothing to join by name later.

ONE OWNER: `market_sizing.py` resolves with it at pipe time, and compose / visualize re-resolve with
it to see whether the record has moved since.

Every refusal carries a `remedy_kind`. No remedy is "change the thing being checked": a unit that
does not fit is fixed by deriving the figure it should have been, never by relabelling the record.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

import _params as P

# Remedy kinds. A remedy may re-run a producer, re-dispatch a sub-agent, ask the founder, record
# research the record lacks, or restore a baseline; it may never alter the value under test.
REMEDY_KINDS: frozenset[str] = frozenset(
    {"producer_rerun", "redispatch", "founder_question", "record_research", "restore_to_baseline", "disclose"}
)

CATEGORIES: frozenset[str] = frozenset({"sourced", "derived", "agent_estimate"})
FOUNDER_STATED = "founder_stated"

# The one sizing input that is a fact about the founder's own business. Every other input is a
# figure about the market, which a deck CLAIMS; claims are tested, not fixed.
FOUNDER_FACT_PARAMS: frozenset[str] = frozenset({"arpu"})

_UNIT_WORDS: dict[str, str] = {
    P.MONEY_TOTAL: "money per year for the whole market",
    P.MONEY_PER_CUSTOMER: "money per customer",
    P.COUNT: "a count (people, accounts or seats)",
    P.FRACTION: "a fraction between 0 and 1",
    P.RATIO: "a ratio",
    P.PERCENT_POINTS: "a percentage (35 means 35%)",
    P.PERCENT_CHANGE: "a growth rate",
    P.YEARS: "a number of years",
    P.FX_RATE: "an exchange rate",
}

_ALGEBRA_RULES = (
    "multiply: count x price per customer -> money per year; count x ratio/fraction -> count; "
    "count x percentage -> count; money x ratio/fraction/percentage -> money; ratio/fraction x "
    "ratio/fraction -> ratio; percentage x percentage/ratio/fraction -> percentage. divide (exactly "
    "two factors): count / count -> ratio; money per year / count -> price per customer; like / like "
    "-> ratio; anything / ratio -> itself. to_percent: ratio/fraction -> percentage. to_fraction: "
    "percentage -> fraction"
)


class _Refused(Exception):
    def __init__(self, code: str, message: str, remedy_kind: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.remedy_kind = remedy_kind


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _assumptions(validation: Any) -> list[dict[str, Any]]:
    v = _as_dict(validation)
    if v.get("skipped"):
        return []
    return [a for a in _as_list(v.get("assumptions")) if isinstance(a, dict)]


def _source_listed(entry: dict[str, Any], validation: Any) -> bool:
    """True when the entry names one of the record's `sources[]`. A record listing none names nothing."""
    title = str(entry.get("source_title") or "").strip()
    url = str(entry.get("source_url") or "").strip()
    if not title and not url:
        return False
    for s in (s for s in _as_list(_as_dict(validation).get("sources")) if isinstance(s, dict)):
        if (title and title == str(s.get("title") or "").strip()) or (url and url == str(s.get("url") or "").strip()):
            return True
    return False


def entry_grade(entry: dict[str, Any], validation: Any) -> str:
    """The grade a research record entry has EARNED, which every surface shows.

    Absence never upgrades: an unknown category, or "sourced" naming no source the record lists, is an
    estimate. The sizing's inputs and the pages' lists of research both grade through this one rule.
    """
    declared = str(entry.get("category") or "")
    if declared not in CATEGORIES:
        return "agent_estimate"
    if declared == "sourced" and not _source_listed(entry, validation):
        return "agent_estimate"
    return declared


class _Resolver:
    def __init__(self, validation: Any, inputs: Any, currency: str) -> None:
        self.validation = validation
        self.inputs = _as_dict(inputs)
        self.currency = (currency or "USD").strip().upper()
        self.entries = _assumptions(validation)

    # -- lookups ----------------------------------------------------------------------------------

    def _entry(self, name: str) -> dict[str, Any]:
        found = [a for a in self.entries if a.get("name") == name]
        if not found:
            raise _Refused(
                "E_REF_UNKNOWN",
                f"No recorded figure is named {name!r}. Reference a figure the research recorded, derive one "
                f"from recorded figures, or state an estimate with its reason.",
                "redispatch",
            )
        if len(found) > 1:
            raise _Refused(
                "E_REF_AMBIGUOUS",
                f"{len(found)} recorded figures are named {name!r}, so a reference to it cannot say which one "
                f"the sizing used. Give each recorded figure its own name.",
                "record_research",
            )
        return found[0]

    def _grade(self, entry: dict[str, Any]) -> tuple[str, str | None]:
        declared = str(entry.get("category") or "")
        grade = entry_grade(entry, self.validation)
        return grade, (declared or None) if grade != declared else None

    def _fx(self, src: str) -> tuple[float, dict[str, Any]]:
        pairs = [
            a
            for a in self.entries
            if a.get("unit") == P.FX_RATE
            and str(a.get("from") or "").strip().upper() == src
            and str(a.get("to") or "").strip().upper() == self.currency
        ]
        if not pairs:
            raise _Refused(
                "E_FX_RATE_MISSING",
                f"A figure is in {src}, the analysis is in {self.currency}, and the research records no "
                f"{src} to {self.currency} rate. Look the rate up and record it with its source and date; a "
                f"rate is never inverted from the other direction, and never taken from memory.",
                "record_research",
            )
        if len(pairs) > 1:
            raise _Refused(
                "E_REF_AMBIGUOUS",
                f"The research records {len(pairs)} {src} to {self.currency} rates; keep one.",
                "record_research",
            )
        rate_entry = pairs[0]
        rate = _num(rate_entry.get("value"))
        if (
            rate is None
            or rate <= 0
            or rate_entry.get("category") != "sourced"
            or not _source_listed(rate_entry, self.validation)
        ):
            raise _Refused(
                "E_FX_NOT_RESEARCHED",
                f"The {src} to {self.currency} rate is not recorded as a sourced figure with its source, so "
                f"it could have come from memory. Record the rate you looked up, with its source and date.",
                "record_research",
            )
        return rate, rate_entry

    # -- quantities -------------------------------------------------------------------------------

    def _leaf(
        self,
        *,
        value: float,
        unit: str,
        currency: Any,
        period: Any,
        category: str,
        entries: set[str],
        origin: str,
        who_fixes_period: str,
    ) -> dict[str, Any]:
        q: dict[str, Any] = {
            "value": value,
            "unit": unit,
            "category": category,
            "entries": set(entries),
            "normalisation": [],
        }
        if unit == P.FRACTION and not 0 <= value <= 1:
            raise _Refused(
                "E_VALUE_RANGE",
                f"{origin} is recorded as a fraction but is {value:g}; a fraction is between 0 and 1. If it is a "
                f"percentage, it is a percentage.",
                "record_research",
            )
        if unit in P.MONEY_UNITS:
            ccy = str(currency or "").strip().upper()
            if not ccy:
                raise _Refused(
                    "E_CURRENCY_MISSING",
                    f"{origin} is money but records no currency. Record the currency its source states.",
                    "record_research",
                )
            if unit == P.MONEY_PER_CUSTOMER:
                per = str(period or "").strip().lower()
                factor = P.PERIOD_TO_YEAR.get(per)
                if factor is None:
                    raise _Refused(
                        "E_PERIOD_MISSING",
                        f"{origin} is a price per customer but does not say per what period "
                        f"({', '.join(sorted(P.PERIOD_TO_YEAR))}). It is not assumed to be annual.",
                        who_fixes_period,
                    )
                if factor != 1.0:
                    q["value"] = q["value"] * factor
                    q["normalisation"].append({"step": "period", "from": per, "factor": factor})
            if ccy != self.currency:
                rate, rate_entry = self._fx(ccy)
                before = q["value"]
                q["value"] = q["value"] * rate
                q["entries"].add(str(rate_entry.get("name")))
                q["normalisation"].append(
                    {
                        "step": "fx",
                        "pair": f"{ccy}:{self.currency}",
                        "rate": rate,
                        "before": before,
                        "entry": rate_entry.get("name"),
                        "as_of": rate_entry.get("as_of"),
                        "source": rate_entry.get("source_url") or rate_entry.get("source_title"),
                    }
                )
        return q

    def _quantity(self, ref: Any, depth: int = 0) -> dict[str, Any]:
        if depth > 8:
            raise _Refused("E_REF_SHAPE", "A derived figure is nested more than eight levels deep.", "redispatch")
        if not isinstance(ref, dict) or len(ref) == 0:
            raise _Refused(
                "E_REF_SHAPE",
                'A sizing input must name where its value comes from ({"assumption": ...}, '
                '{"founder_stated": ...}, {"derived": ...} or {"estimate": ...}), not carry a bare number.',
                "redispatch",
            )
        if "assumption" in ref:
            name = str(ref.get("assumption") or "")
            entry = self._entry(name)
            value = _num(entry.get("value"))
            unit = entry.get("unit")
            if value is None:
                raise _Refused("E_REF_SHAPE", f"Recorded figure {name!r} has no numeric value.", "record_research")
            if unit not in P.UNITS or unit == P.FX_RATE:
                raise _Refused(
                    "E_UNIT_MISSING",
                    f"Recorded figure {name!r} does not say what it measures (its unit). Record the unit its "
                    f"source measures.",
                    "record_research",
                )
            category, declared = self._grade(entry)
            q = self._leaf(
                value=value,
                unit=str(unit),
                currency=entry.get("currency"),
                period=entry.get("period"),
                category=category,
                entries={name},
                origin=f"Recorded figure {name!r}",
                who_fixes_period="record_research",
            )
            q["out"] = {
                "kind": "assumption",
                "name": name,
                "category_declared": declared,
                "value_as_recorded": value,
                "currency_as_recorded": entry.get("currency"),
                "period_as_recorded": entry.get("period"),
                "source_title": entry.get("source_title"),
                "source_url": entry.get("source_url"),
            }
            return q
        if "founder_stated" in ref:
            key = str(ref.get("founder_stated") or "")
            if key not in FOUNDER_FACT_PARAMS:
                raise _Refused(
                    "E_FOUNDER_NOT_FACT",
                    f"Only a fact about the founder's own business ({', '.join(sorted(FOUNDER_FACT_PARAMS))}) can "
                    f"come from what the founder stated; {key!r} is a figure about the market, which their "
                    f"materials claim and the analysis tests.",
                    "redispatch",
                )
            stated = _as_dict(self.inputs.get("founder_stated_inputs"))
            value = _num(stated.get(key))
            if value is None:
                raise _Refused(
                    "E_FOUNDER_UNKNOWN",
                    f"The founder stated no {key!r}. Reference a recorded figure or state an estimate.",
                    "redispatch",
                )
            period = _as_dict(self.inputs.get("founder_stated_inputs_period")).get(key)
            q = self._leaf(
                value=value,
                unit=P.PARAM_UNITS[key],
                currency=self.inputs.get("founder_stated_inputs_currency") or self.currency,
                period=period,
                category=FOUNDER_STATED,
                entries={f"founder:{key}"},
                origin=f"The founder's {key}",
                who_fixes_period="founder_question",
            )
            q["out"] = {
                "kind": "founder_stated",
                "name": key,
                "value_as_recorded": value,
                "period_as_recorded": period,
                "currency_as_recorded": self.inputs.get("founder_stated_inputs_currency"),
                # Which recorded figures ARE this one, so no page tells the founder the figure their
                # own sizing rests on is "not used in the sizing". A separate field from `entries` on
                # purpose: see same_figure_entries.
                "same_figure_entries": _same_figure_entries(
                    self.validation,
                    key,
                    value,
                    period,
                    self.inputs.get("founder_stated_inputs_currency") or self.currency,
                ),
            }
            return q
        if "estimate" in ref:
            value = _num(ref.get("estimate"))
            unit = ref.get("unit")
            why = str(ref.get("why") or "").strip()
            if unit == P.FX_RATE:
                raise _Refused(
                    "E_FX_NOT_RESEARCHED",
                    "An exchange rate cannot be an estimate: it has to be looked up and recorded with its source.",
                    "record_research",
                )
            if value is None or unit not in P.UNITS or not why:
                raise _Refused(
                    "E_REF_SHAPE",
                    "An estimate carries its number, its unit, and one sentence saying why no recorded figure was "
                    "used.",
                    "redispatch",
                )
            q = self._leaf(
                value=value,
                unit=str(unit),
                currency=ref.get("currency") or self.currency,
                period=ref.get("period"),
                category="agent_estimate",
                entries=set(),
                origin="The estimate",
                who_fixes_period="redispatch",
            )
            q["out"] = {
                "kind": "estimate",
                "why": why,
                "value_as_recorded": value,
                # A recorded figure typed in as an estimate is still a figure the sizing used. A separate
                # field from `entries` on purpose: see _same_figure_entries.
                "same_figure_entries": _estimate_same_figure_entries(
                    self.validation, value, str(unit), ref.get("period"), ref.get("currency") or self.currency
                ),
            }
            return q
        if "derived" in ref:
            spec = _as_dict(ref.get("derived"))
            op = spec.get("op")
            factors = _as_list(spec.get("factors"))
            if op not in ("multiply", "divide", "to_percent", "to_fraction") or not factors:
                raise _Refused(
                    "E_REF_SHAPE",
                    "A derived figure names its op (multiply, divide, to_percent, to_fraction) and its factors.",
                    "redispatch",
                )
            parts = [self._quantity(f, depth + 1) for f in factors]
            q = _combine(str(op), parts)
            q["out"] = {"kind": "derived", "op": op, "factors": [_public(p) for p in parts]}
            return q
        raise _Refused(
            "E_REF_SHAPE",
            f"Unrecognised reference {sorted(ref)}; use assumption, founder_stated, derived or estimate.",
            "redispatch",
        )


def _category_of(parts: list[dict[str, Any]]) -> str:
    cats = {p["category"] for p in parts}
    if "agent_estimate" in cats:
        return "agent_estimate"
    return "derived"


def _mul(a: str, b: str) -> tuple[str, float] | None:
    pair = {a, b}
    if a == b:
        same = {P.FRACTION: (P.FRACTION, 1.0), P.RATIO: (P.RATIO, 1.0), P.PERCENT_POINTS: (P.PERCENT_POINTS, 0.01)}
        return same.get(a)
    table: list[tuple[set[str], tuple[str, float]]] = [
        ({P.COUNT, P.MONEY_PER_CUSTOMER}, (P.MONEY_TOTAL, 1.0)),
        ({P.COUNT, P.RATIO}, (P.COUNT, 1.0)),
        ({P.COUNT, P.FRACTION}, (P.COUNT, 1.0)),
        ({P.COUNT, P.PERCENT_POINTS}, (P.COUNT, 0.01)),
        ({P.MONEY_TOTAL, P.FRACTION}, (P.MONEY_TOTAL, 1.0)),
        ({P.MONEY_TOTAL, P.RATIO}, (P.MONEY_TOTAL, 1.0)),
        ({P.MONEY_TOTAL, P.PERCENT_POINTS}, (P.MONEY_TOTAL, 0.01)),
        ({P.MONEY_PER_CUSTOMER, P.FRACTION}, (P.MONEY_PER_CUSTOMER, 1.0)),
        ({P.MONEY_PER_CUSTOMER, P.RATIO}, (P.MONEY_PER_CUSTOMER, 1.0)),
        ({P.MONEY_PER_CUSTOMER, P.PERCENT_POINTS}, (P.MONEY_PER_CUSTOMER, 0.01)),
        ({P.FRACTION, P.RATIO}, (P.RATIO, 1.0)),
        ({P.FRACTION, P.PERCENT_POINTS}, (P.PERCENT_POINTS, 1.0)),
        ({P.RATIO, P.PERCENT_POINTS}, (P.PERCENT_POINTS, 1.0)),
    ]
    for units, result in table:
        if pair == units:
            return result
    return None


def _div(a: str, b: str) -> str | None:
    if b == P.RATIO and a in (P.COUNT, P.MONEY_TOTAL, P.MONEY_PER_CUSTOMER, P.RATIO, P.PERCENT_POINTS):
        return a
    if a == b and a in (P.COUNT, P.MONEY_TOTAL, P.MONEY_PER_CUSTOMER, P.PERCENT_POINTS, P.FRACTION):
        return P.RATIO
    if (a, b) == (P.MONEY_TOTAL, P.COUNT):
        return P.MONEY_PER_CUSTOMER
    return None


def _combine(op: str, parts: list[dict[str, Any]]) -> dict[str, Any]:
    entries: set[str] = set()
    for p in parts:
        entries |= p["entries"]
    refused = _Refused(
        "E_ALGEBRA", f"These factors do not combine into a figure. The rules: {_ALGEBRA_RULES}.", "redispatch"
    )
    if op == "multiply":
        if len(parts) < 2:
            raise refused
        unit, value = parts[0]["unit"], parts[0]["value"]
        for p in parts[1:]:
            rule = _mul(unit, p["unit"])
            if rule is None:
                raise refused
            unit, value = rule[0], value * p["value"] * rule[1]
    elif op == "divide":
        if len(parts) != 2:
            raise refused
        result = _div(parts[0]["unit"], parts[1]["unit"])
        if result is None or parts[1]["value"] == 0:
            raise refused
        unit, value = result, parts[0]["value"] / parts[1]["value"]
    else:
        if len(parts) != 1:
            raise refused
        src = parts[0]
        if op == "to_percent" and src["unit"] in (P.FRACTION, P.RATIO):
            unit, value = P.PERCENT_POINTS, src["value"] * 100
        elif op == "to_fraction" and src["unit"] == P.PERCENT_POINTS:
            unit, value = P.FRACTION, src["value"] / 100
        elif op == "to_fraction" and src["unit"] == P.RATIO and 0 <= src["value"] <= 1:
            unit, value = P.FRACTION, src["value"]
        else:
            raise refused
    return {"value": value, "unit": unit, "category": _category_of(parts), "entries": entries, "normalisation": []}


def _public(q: dict[str, Any]) -> dict[str, Any]:
    """The JSON-safe view of a resolved quantity, for the artifact."""
    out = dict(q.get("out") or {})
    out.update(
        {
            "unit": q["unit"],
            "category": q["category"],
            "value_consumed": q["value"],
            "normalisation": list(q["normalisation"]),
            "entries": sorted(q["entries"]),
        }
    )
    return out


def resolve(
    input_refs: dict[str, Any],
    *,
    validation: Any,
    inputs: Any,
    currency: str,
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    """Resolve every sizing input. Returns ({param: provenance}, [refusal, ...])."""
    r = _Resolver(validation, inputs, currency)
    resolved: dict[str, dict[str, Any]] = {}
    errors: list[dict[str, Any]] = []
    for param, ref in input_refs.items():
        want = P.PARAM_UNITS.get(param)
        if want is None:
            continue
        try:
            q = r._quantity(ref)
            if q["unit"] != want:
                raise _Refused(
                    "E_UNIT_MISMATCH",
                    f"{param} must be {_UNIT_WORDS[want]}, and what it references is {_UNIT_WORDS[q['unit']]}. "
                    f"Reference it as a derived figure from recorded figures that combine into "
                    f"{_UNIT_WORDS[want]} (a count times a price per customer is money per year; a ratio "
                    f"becomes a percentage through to_percent), or re-dispatch the sizing step.",
                    "redispatch",
                )
            if param == "customer_count" and not float(q["value"]).is_integer():
                rounded = round(q["value"])
                q["normalisation"].append({"step": "round", "from": q["value"]})
                q["value"] = int(rounded)
            elif param == "customer_count":
                q["value"] = int(q["value"])
            out = _public(q)
            if out.get("kind") == "estimate":
                research = [a for a in r.entries if a.get("name") == param and _num(a.get("value")) is not None]
                if len(research) == 1:
                    out["research_value"] = research[0]["value"]
            resolved[param] = out
        except _Refused as exc:
            errors.append({"code": exc.code, "param": param, "message": exc.message, "remedy_kind": exc.remedy_kind})
    return resolved, errors


def _fingerprint(data: Any) -> str:
    """Order-insensitive sha256 of a JSON value."""
    encoded = json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _estimate_same_figure_entries(validation: Any, value: float, unit: str, period: Any, currency: Any) -> list[str]:
    """Record entries that provably hold the figure an estimate carries, for the "not used" label only.

    A live sizing wrote a sourced percentage into a derivation as an estimate fraction, and the report
    told the reader that percentage was "not used in the sizing". Same contract as `_same_figure_entries`: the figure
    is compared, never the name or the estimate's reason, and a match needs the unit, the value, the
    period for a per-customer price and the currency for money. The one conversion allowed is between a
    fraction and a percentage, compared as `percentage / 100 == fraction` -- a division of a recorded
    number, not an accumulated product, so exact equality still holds for a percentage typed as its fraction.
    """
    names: set[str] = set()
    for entry in _assumptions(validation):
        name = entry.get("name")
        recorded = _num(entry.get("value"))
        if not isinstance(name, str) or recorded is None:
            continue
        other = entry.get("unit")
        if other == unit:
            same = recorded == value
        elif (other, unit) == (P.PERCENT_POINTS, P.FRACTION):
            same = recorded / 100 == value
        elif (other, unit) == (P.FRACTION, P.PERCENT_POINTS):
            same = value / 100 == recorded
        else:
            continue
        if not same:
            continue
        if unit == P.MONEY_PER_CUSTOMER and entry.get("period") != period:
            continue
        if unit in P.MONEY_UNITS and (entry.get("currency") or currency) != currency:
            continue
        names.add(name)
    return sorted(names)


def _same_figure_entries(validation: Any, key: str, value: float, period: Any, currency: Any) -> list[str]:
    """Record entries that provably hold the SAME figure the founder stated for `key`.

    Not a name join. A record entry named like the parameter proves nothing -- joining the record to the
    sizing by name without comparing values is the false-provenance defect in reverse -- and the model
    writes both the names and the labels, so neither can decide this. An entry matches only when every
    part of the figure agrees: the unit the parameter's slot requires, the value, the period for a
    per-customer price, and the currency for money.

    VALUE EQUALITY IS EXACT, on the numbers as recorded. Both sides are the same kind of typed JSON
    input -- `founder_stated_inputs[key]` and the entry's own `value` -- never the product of any
    arithmetic, so there is no accumulated float error for a tolerance to absorb. A tolerance would be
    strictly worse than none here: it would let a figure that merely rounds to the founder's claim
    borrow their provenance. So `==` is the comparison, and 157 against 157.5 stays a different figure.

    Compared as RECORDED, not as consumed: a monthly price is annualised on the way into the sizing
    while the record still holds the monthly number, so comparing against the consumed value would
    never match.

    Its one use is deciding whether a row may tell the founder a figure is "not used in the sizing". It
    is deliberately NOT folded into `entries`, which means "the sizing depends on this" and is what the
    review diff and the override check read.
    """
    unit = P.PARAM_UNITS.get(key)
    if unit is None:
        return []
    names: set[str] = set()
    for entry in _assumptions(validation):
        name = entry.get("name")
        if not isinstance(name, str) or entry.get("unit") != unit:
            continue
        if _num(entry.get("value")) != value:
            continue
        if unit == P.MONEY_PER_CUSTOMER and entry.get("period") != period:
            continue
        if unit in P.MONEY_UNITS and (entry.get("currency") or currency) != currency:
            continue
        names.add(name)
    return sorted(names)


def record_snapshot(validation: Any, inputs: Any) -> dict[str, dict[str, Any]]:
    """Every quantitative record entry, by name, as it stands: what a review is taken against.

    The grade an entry earned is part of it: listing a source raises a grade without touching a value.
    """
    snap: dict[str, dict[str, Any]] = {}
    for a in _assumptions(validation):
        if a.get("unit") in P.UNITS and isinstance(a.get("name"), str):
            snap[a["name"]] = {k: a.get(k) for k in ("value", "unit", "currency", "period", "from", "to")}
            snap[a["name"]]["grade"] = entry_grade(a, validation)
    stated = _as_dict(_as_dict(inputs).get("founder_stated_inputs"))
    periods = _as_dict(_as_dict(inputs).get("founder_stated_inputs_period"))
    for key in sorted(FOUNDER_FACT_PARAMS):
        if key in stated:
            snap[f"founder:{key}"] = {"value": stated.get(key), "period": periods.get(key)}
    return snap


def fx_steps(prov: dict[str, Any]) -> list[dict[str, Any]]:
    """Every currency conversion one resolved input went through, its factors' included."""
    steps = [st for st in _as_list(prov.get("normalisation")) if isinstance(st, dict) and st.get("step") == "fx"]
    for factor in _as_list(prov.get("factors")):
        if isinstance(factor, dict):
            steps.extend(fx_steps(factor))
    return steps


def sizing_fingerprint(sizing: Any) -> str | None:
    """What a downstream producer was graded against: the sizing's references and consumed values.

    Formatting, figures and metadata are left out, so re-running the same sizing is not a change;
    a different reference or a different consumed value is. None for a sizing without provenance.
    """
    s = _as_dict(sizing)
    if s.get("provenance_version") != 1 or not isinstance(s.get("input_provenance"), dict):
        return None
    consumed = {p: _as_dict(v).get("value_consumed") for p, v in sorted(_as_dict(s.get("input_provenance")).items())}
    return _fingerprint({"refs": _without_prose(_as_dict(s.get("input_refs"))), "consumed": consumed})


# A reference's prose (the `why` beside an estimate) says why, not what. Hashing it made rewording a
# leaked file name out of a `why` read as a new sizing, and every table graded against the old one stale.
_REF_PROSE_KEYS = frozenset({"why", "label", "note"})


def _without_prose(ref: Any) -> Any:
    if isinstance(ref, dict):
        return {k: _without_prose(v) for k, v in ref.items() if k not in _REF_PROSE_KEYS}
    if isinstance(ref, list):
        return [_without_prose(v) for v in ref]
    return ref


def load_stamped_sizing(path: str) -> tuple[dict[str, Any] | None, str | None]:
    """Load and validate a v1-stamped sizing.json for ``--sizing``.

    Returns ``(sizing, None)`` on success or ``(None, error)`` where ``error`` starts with
    ``E_SIZING_NOT_STAMPED:`` — unreadable, not JSON, not an object, or missing the
    ``provenance_version == 1`` / dict ``input_provenance`` stamp a sizing written by the
    references path always carries. A legacy (numeric-path, unstamped) sizing.json is refused
    here rather than silently falling back to the hand-off's own ``base``.
    """
    try:
        with open(path, encoding="utf-8") as f:
            raw = f.read()
    except OSError as e:
        return None, f"E_SIZING_NOT_STAMPED: could not read {path!r}: {e}"
    try:
        sizing = json.loads(raw)
    except json.JSONDecodeError as e:
        return None, f"E_SIZING_NOT_STAMPED: {path!r} is not valid JSON: {e}"
    if not isinstance(sizing, dict):
        return None, f"E_SIZING_NOT_STAMPED: {path!r} must be a JSON object (got {type(sizing).__name__})"
    if sizing.get("provenance_version") != 1 or not isinstance(sizing.get("input_provenance"), dict):
        return None, (
            f"E_SIZING_NOT_STAMPED: {path!r} carries no provenance (provenance_version == 1 with an "
            f"input_provenance object) — it looks like a legacy or numeric-path sizing.json. Re-run "
            f"market_sizing.py on the references path, or drop --sizing."
        )
    return sizing, None
