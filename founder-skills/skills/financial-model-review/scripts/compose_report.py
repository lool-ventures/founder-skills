#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
Compose financial model review report from structured JSON artifacts.

Reads all JSON artifacts from a directory, validates completeness and
cross-artifact consistency, assembles a markdown report.

Usage:
    python compose_report.py --dir ./fmr-testco/ --pretty

Output: JSON to stdout with report_markdown and validation results.
        Human-readable validation summary to stderr.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import uuid
from typing import Any, TypeGuard

# Sentinel for corrupt (unparseable) artifact files
_CORRUPT: dict[str, Any] = {"__corrupt__": True}

# Canonical warning severity map -- stable API, tested for completeness
WARNING_SEVERITY: dict[str, str] = {
    # "low" deliberately, NOT medium: by the time this fires the text has ALREADY been corrected by
    # substitute(), so the report the founder reads is clean. What remains is an AUTHORING task (a
    # producer that should stop emitting the token, or a filename that must be dropped rather than
    # renamed), and ic-sim / market-sizing / deck-review all block strict mode on medium — which would
    # abort a founder's run over a cosmetic issue that was already fixed. The fleet ratchet in
    # test_compose_invariants.py is the real gate; this is the runtime breadcrumb.
    "FOUNDER_TEXT_TOKEN": "low",
    # High severity -- agent must fix before presenting report
    "CORRUPT_ARTIFACT": "high",
    "MISSING_ARTIFACT": "high",
    "STALE_ARTIFACT": "high",
    # Low severity -- informational
    "MISSING_OPTIONAL_ARTIFACT": "low",
    # Medium severity -- include in Warnings section of report
    # Checklist failures are review findings, not data errors — present, don't block
    "CHECKLIST_FAILURES": "medium",
    "CHECKLIST_INCOMPLETE": "medium",
    "RUNWAY_INCONSISTENCY": "medium",
    "METRICS_GAPS": "medium",
    "METRIC_SELF_CONTRADICTION": "medium",
    # v0.4.2 Mitigation 2 — informational only (uuid is per-run, won't collide)
    "MARKER_COLLISION": "low",
}

REQUIRED_ARTIFACTS = ["inputs.json", "checklist.json", "unit_economics.json", "runway.json"]
OPTIONAL_ARTIFACTS = ["model_data.json", "extraction_corrections.json"]

# Founder-facing description per artifact, for warning messages that reach report.md. A filename is
# our name for the file — the founder cannot act on "model_data.json is missing", but can act on
# "the figures extracted from your spreadsheet were not available".
ARTIFACT_DESCRIPTIONS: dict[str, str] = {
    "model_data.json": "the figures extracted from your spreadsheet",
    "extraction_corrections.json": "your corrections to the extracted figures",
}


def _artifact_desc(name: str) -> str:
    """Founder-facing description, falling back to the raw name so a new artifact is never silent."""
    return ARTIFACT_DESCRIPTIONS.get(name, name)


# Human-readable warning code labels
WARNING_LABELS: dict[str, str] = {
    "FOUNDER_TEXT_TOKEN": "Internal Token In Report",
    "CORRUPT_ARTIFACT": "Corrupt Artifact",
    "MISSING_ARTIFACT": "Missing Artifact",
    "STALE_ARTIFACT": "Stale Artifact",
    "CHECKLIST_FAILURES": "Checklist Failures",
    "MISSING_OPTIONAL_ARTIFACT": "Missing Optional Artifact",
    "CHECKLIST_INCOMPLETE": "Checklist Incomplete",
    "RUNWAY_INCONSISTENCY": "Runway Inconsistency",
    "METRICS_GAPS": "Metrics Gaps",
    "METRIC_SELF_CONTRADICTION": "Contradictory Metric Figures",
    "MARKER_COLLISION": "Marker Collision",
}

# Rating display labels
RATING_LABELS: dict[str, str] = {
    "strong": "Strong",
    "acceptable": "Acceptable",
    "warning": "Warning",
    "fail": "Fail",
    "not_rated": "Not Rated",
    "contextual": "Contextual",
    "not_applicable": "N/A",
}


def _humanize_warning(code: str) -> str:
    """Convert a warning code to human-readable label."""
    return WARNING_LABELS.get(code, code.replace("_", " ").title())


def _fmt_number(value: Any) -> str:
    """Format a numeric value for display (with commas, no unnecessary decimals)."""
    if isinstance(value, float):
        if value == int(value):
            return f"{int(value):,}"
        return f"{value:,.2f}"
    if isinstance(value, int):
        return f"{value:,}"
    return str(value)


def _fmt_usd(value: float | int, currency_code: str = "USD") -> str:
    """Format a number as a currency string, scaled with K/M/B suffixes.

    `currency_code` defaults to "USD" (the back-compat behavior for absent/
    "USD" inputs), using a bare "$" prefix. Any other ISO code is tagged as a
    suffix instead (e.g. "1.5M INR") — a bare "$" would misrepresent a
    non-USD-denominated model.
    """
    if value < 0:
        return "-" + _fmt_usd(-value, currency_code)
    prefix = "$" if currency_code == "USD" else ""
    suffix = "" if currency_code == "USD" else f" {currency_code}"
    if value >= 1_000_000_000:
        return f"{prefix}{value / 1_000_000_000:,.1f}B{suffix}"
    if value >= 1_000_000:
        return f"{prefix}{value / 1_000_000:,.1f}M{suffix}"
    if value >= 1_000:
        return f"{prefix}{value / 1_000:,.1f}K{suffix}"
    return f"{prefix}{value:,.2f}{suffix}"


def _fmt_pct(value: float | int) -> str:
    """Format a value as a percentage string."""
    if isinstance(value, float) and value <= 1.0:
        return f"{value * 100:.1f}%"
    return f"{value}%"


def _resolve_currency(*artifacts: dict[str, Any] | None) -> str:
    """Return the model's native currency code from the first artifact carrying one.

    Checked in the order passed by the caller; falls back to "USD" (the
    back-compat default) when none carry a currency field. inputs.json is the
    original source of the field; unit_economics.json / runway.json now echo
    it too, so this works whichever artifacts happen to be usable.
    """
    for artifact in artifacts:
        if isinstance(artifact, dict):
            currency = artifact.get("currency")
            if isinstance(currency, str) and currency.strip():
                return currency.strip().upper()
    return "USD"


def _md_safe(text: str | None) -> str:
    """Escape text for safe markdown table cell interpolation."""
    if not text:
        return ""
    return text.replace("|", "\\|").replace("\n", " ")


def _write_output(data: str, output_path: str | None, *, summary: dict[str, Any] | None = None) -> None:
    """Write JSON string to file or stdout."""
    if output_path:
        abs_path = os.path.abspath(output_path)
        parent = os.path.dirname(abs_path)
        if parent == "/":
            print(f"Error: output path resolves to root directory: {output_path}", file=sys.stderr)
            sys.exit(1)
        os.makedirs(parent, exist_ok=True)
        with open(abs_path, "w", encoding="utf-8") as f:
            f.write(data)
        receipt: dict[str, Any] = {"ok": True, "path": abs_path, "bytes": len(data.encode("utf-8"))}
        if summary:
            receipt.update(summary)
        sys.stdout.write(json.dumps(receipt, separators=(",", ":")) + "\n")
    else:
        sys.stdout.write(data)


def _load_artifact(dir_path: str, name: str) -> dict[str, Any] | None:
    """Load a JSON artifact. Returns None if missing, _CORRUPT if unparseable."""
    path = os.path.join(dir_path, name)
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)  # type: ignore[no-any-return]
    except (json.JSONDecodeError, OSError):
        return _CORRUPT


def _is_stub(data: dict[str, Any] | None) -> bool:
    """Check if artifact is a stub (intentionally skipped)."""
    return isinstance(data, dict) and data.get("skipped") is True


def _format_runway_months(months: Any, breakeven_month: int | None = None) -> str:
    """Format runway months, handling None (infinite/profitable) gracefully.

    When months is None (default-alive scenario) and breakeven_month is derivable
    from the scenario projections, appends the projected breakeven month.
    """
    if months is None:
        if breakeven_month is not None:
            return f"Infinite — projected breakeven ~month {breakeven_month}"
        return "Infinite (reaches profitability)"
    return f"{months} months"


def _usable(data: dict[str, Any] | None) -> TypeGuard[dict[str, Any]]:
    """Check if artifact is loaded, not corrupt, and not a stub."""
    return data is not None and data is not _CORRUPT and not _is_stub(data)


def _as_list(value: Any) -> list[Any]:
    """Coerce to list -- returns [] if not a list."""
    return value if isinstance(value, list) else []


def _as_dict(value: Any) -> dict[str, Any]:
    """Coerce to dict -- returns {} if not a dict."""
    return value if isinstance(value, dict) else {}


def _founder_text_policy() -> Any:
    """Import the fleet's shared founder-text policy from `founder-skills/scripts/`.

    Parent-relative rather than duplicated: this file lives at
    `skills/<skill>/scripts/compose_report.py`, so `parents[2]/scripts` is the shared dir. Returns
    None if unavailable — a missing policy module must never block a report, since the scan is a
    warning and not a gate.
    """
    try:
        shared = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "scripts"))
        if shared not in sys.path:
            sys.path.insert(0, shared)
        import _founder_text  # type: ignore[import-not-found]

        return _founder_text
    except ImportError:
        return None


def _warn(code: str, message: str, founder_message: str | None = None) -> dict[str, str]:
    """Create a warning dict with code, message, and severity from canonical map.

    `message` is the agent-facing text and MUST keep naming the authoritative
    artifact -- it flows unchanged into report.json. `founder_message` is an
    OPTIONAL additive key: when a warning has a founder-visible consequence,
    it states that consequence in plain words (no artifact filename, no raw
    enum token, no instruction addressed to the model) and is what report.md
    renders instead of `message`. Warnings with no founder-facing problem
    pass no `founder_message` and are unaffected.
    """
    w = {
        "code": code,
        "message": message,
        "severity": WARNING_SEVERITY.get(code, "medium"),
    }
    if founder_message is not None:
        w["founder_message"] = founder_message
    return w


# ---------------------------------------------------------------------------
# One figure, one source
#
# A deliverable that states two different values for the same metric is worse
# than one that states a wrong value: the founder cannot tell which number to
# take to an investor, and it discredits the figures that ARE right. The known
# instance was a burn multiple computed as 4.5x by unit_economics.py while the
# checklist sub-agent independently derived ~7x in its evidence prose.
#
# The upstream ambiguity that caused it is fixed at the source, so this is a
# BACKSTOP for the whole class — any component restating a computed ratio in
# prose gets caught, not just the one we found.
#
# Scope is deliberately narrow to keep the precision high enough to act on:
# ratio metrics only, where a bare multiple is unambiguous. Percent- and
# currency-denominated metrics are excluded because "0.75" / "75%" / "$75K"
# render the same value three ways and the resulting false positives would
# train the reader to ignore the warning.
# ---------------------------------------------------------------------------

# Ratio metrics -> the prose labels a component might restate them under.
_RATIO_METRIC_LABELS: dict[str, tuple[str, ...]] = {
    "burn_multiple": ("burn multiple", "burn_multiple"),
    "ltv_cac_ratio": ("ltv/cac", "ltv:cac", "ltv to cac", "ltv_cac_ratio", "ltv/cac ratio"),
    "magic_number": ("magic number", "magic_number"),
    "cac_payback": ("cac payback", "cac_payback", "payback period"),
}

# A number within this many characters AFTER a metric label is treated as a
# claim about that metric. Wide enough for "burn multiple of roughly 7x".
_CLAIM_WINDOW_CHARS = 40

_NUMBER_RE = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)\s*x?")


def _numeric(value: Any) -> float | None:
    """Coerce to float, rejecting bools and non-numerics."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _close(a: float, b: float, tolerance: float = 0.05) -> bool:
    """Relative closeness, so prose rounding (4.53 -> "4.5x") is not a conflict."""
    denom = abs(b) if b else 1.0
    return abs(a - b) / denom <= tolerance


def _metric_claims_in_text(text: str, labels: tuple[str, ...]) -> list[float]:
    """The value each mention of `labels` in `text` asserts for that metric.

    Only the FIRST number after a label is taken. A restatement puts its figure
    there ("burn multiple of 7x"), while every number AFTER it is something the
    metric is being compared to — a benchmark ("4.5x exceeds the 2.0x target") or
    an adjacent metric ("4.5x and an LTV/CAC of 3.2"). Reading past the first
    number produced exactly those two false positives, and a check that fires on
    normal, well-written evidence prose trains the reader to ignore it.
    """
    found: list[float] = []
    lowered = text.lower()
    for label in labels:
        start = 0
        while True:
            at = lowered.find(label, start)
            if at < 0:
                break
            start = at + len(label)
            window = text[start : start + _CLAIM_WINDOW_CHARS]
            match = _NUMBER_RE.search(window)
            if match is None:
                continue
            try:
                found.append(float(match.group(1)))
            except ValueError:
                continue
    return found


def _check_metric_self_contradiction(
    unit_economics: dict[str, Any] | None,
    checklist: dict[str, Any] | None,
) -> list[dict[str, str]]:
    """Flag a checklist evidence figure that contradicts the computed metric."""
    warnings: list[dict[str, str]] = []
    if not _usable(unit_economics) or not _usable(checklist):
        return warnings
    assert unit_economics is not None and checklist is not None

    # Canonical computed values, plus the benchmark thresholds each metric is
    # legitimately compared AGAINST (so "above the 2.0x benchmark" is not a
    # contradiction of a 4.5x actual).
    canonical: dict[str, float] = {}
    permitted: dict[str, list[float]] = {}
    for metric in _as_list(unit_economics.get("metrics")):
        if not isinstance(metric, dict):
            continue
        name = metric.get("id") or metric.get("name")
        if not isinstance(name, str) or name not in _RATIO_METRIC_LABELS:
            continue
        value = _numeric(metric.get("value"))
        if value is None or value == 0:
            continue
        canonical[name] = value
        allowed = [value]
        bench = _as_dict(metric.get("benchmark"))
        for key in ("target", "strong", "acceptable", "warning"):
            bench_value = _numeric(bench.get(key))
            if bench_value is not None:
                allowed.append(bench_value)
        reference = _as_dict(metric.get("benchmark_reference"))
        for key in ("target", "strong", "acceptable", "warning"):
            ref_value = _numeric(reference.get(key))
            if ref_value is not None:
                allowed.append(ref_value)
        permitted[name] = allowed

    if not canonical:
        return warnings

    # Walk every evidence string the checklist carries, at whatever nesting.
    texts: list[tuple[str, str]] = []

    def _harvest(node: Any, label: str) -> None:
        if isinstance(node, dict):
            evidence = node.get("evidence")
            if isinstance(evidence, str) and evidence.strip():
                criterion = node.get("id") or node.get("criterion") or node.get("name") or label
                texts.append((str(criterion), evidence))
            for key, child in node.items():
                if key != "evidence":
                    _harvest(child, label)
        elif isinstance(node, list):
            for child in node:
                _harvest(child, label)

    _harvest(checklist, "checklist")

    seen: set[tuple[str, float]] = set()
    for criterion, text in texts:
        for name, value in canonical.items():
            for claim in _metric_claims_in_text(text, _RATIO_METRIC_LABELS[name]):
                if any(_close(claim, allowed) for allowed in permitted[name]):
                    continue
                dedup_key = (name, round(claim, 3))
                if dedup_key in seen:
                    continue
                seen.add(dedup_key)
                label = _RATIO_METRIC_LABELS[name][0]
                warnings.append(
                    _warn(
                        "METRIC_SELF_CONTRADICTION",
                        (
                            f"{name} is computed as {value:,.10g} in unit_economics.json, but "
                            f"checklist criterion '{criterion}' states {claim:,.10g} for the same metric. "
                            "One figure, one source: the computed value is authoritative — correct the "
                            "evidence text rather than leaving the founder two numbers to choose between. "
                            "If the two are measuring genuinely different things, say which in the evidence."
                        ),
                        founder_message=(
                            f"This report shows two different numbers for the {label}: "
                            f"{value:,.10g} and {claim:,.10g}. Use {value:,.10g} — it's the correct "
                            "one — and don't quote the other figure to investors until this is "
                            "reconciled."
                        ),
                    )
                )
    return warnings


def validate_artifacts(artifacts: dict[str, dict[str, Any] | None]) -> list[dict[str, str]]:
    """Run validation checks across artifacts. Returns list of warnings."""
    warnings: list[dict[str, str]] = []

    checklist = artifacts.get("checklist.json")
    unit_economics = artifacts.get("unit_economics.json")
    runway = artifacts.get("runway.json")
    inputs = artifacts.get("inputs.json")

    # 0. METRIC_SELF_CONTRADICTION -- two different values for one metric.
    warnings.extend(_check_metric_self_contradiction(unit_economics, checklist))

    # 1. CORRUPT_ARTIFACT / MISSING_ARTIFACT -- required artifacts
    for name in REQUIRED_ARTIFACTS:
        data = artifacts.get(name)
        if data is _CORRUPT:
            warnings.append(_warn("CORRUPT_ARTIFACT", f"Artifact has invalid JSON: {name}"))
        elif data is None:
            warnings.append(_warn("MISSING_ARTIFACT", f"Required artifact missing: {name}"))

    # 1b. STALE_ARTIFACT -- run_id mismatch across artifacts
    run_ids: dict[str, str] = {}
    for name in REQUIRED_ARTIFACTS + OPTIONAL_ARTIFACTS:
        data = artifacts.get(name)
        if _usable(data):
            assert data is not None  # for type narrowing
            rid = _as_dict(data.get("metadata")).get("run_id")
            if isinstance(rid, str) and rid:
                run_ids[name] = rid
    if len(run_ids) >= 2:
        unique_ids = set(run_ids.values())
        if len(unique_ids) > 1:
            mismatched = [f"{n} ({rid})" for n, rid in run_ids.items()]
            warnings.append(
                _warn(
                    "STALE_ARTIFACT",
                    f"Run ID mismatch across artifacts — possible stale data: {', '.join(mismatched)}",
                )
            )

    # 2. CORRUPT_ARTIFACT / MISSING_OPTIONAL_ARTIFACT -- optional artifacts
    for name in OPTIONAL_ARTIFACTS:
        data = artifacts.get(name)
        if data is _CORRUPT:
            warnings.append(_warn("CORRUPT_ARTIFACT", f"could not be read: {_artifact_desc(name)}"))
        elif data is None:
            warnings.append(_warn("MISSING_OPTIONAL_ARTIFACT", f"not available: {_artifact_desc(name)}"))

    # 3. CHECKLIST_FAILURES -- checklist overall_status indicates failure
    if _usable(checklist):
        summary = _as_dict(checklist.get("summary"))
        if summary.get("overall_status") == "major_revision":
            failed = _as_list(summary.get("failed_items"))
            failed_ids = [f.get("id", "?") for f in failed]
            warnings.append(
                _warn(
                    "CHECKLIST_FAILURES",
                    f"Checklist has {len(failed)} failures: {failed_ids}",
                )
            )

    # 4. CHECKLIST_INCOMPLETE -- unexpected item count
    if _usable(checklist):
        items = _as_list(checklist.get("items"))
        if len(items) != 46:
            warnings.append(
                _warn(
                    "CHECKLIST_INCOMPLETE",
                    f"Checklist has {len(items)} items (expected 46)",
                )
            )

    # 5. RUNWAY_INCONSISTENCY -- runway cash doesn't match inputs cash
    if _usable(runway) and _usable(inputs):
        baseline = _as_dict(runway.get("baseline"))
        cash_data = _as_dict(inputs.get("cash"))
        runway_cash = baseline.get("net_cash")
        raw_balance = cash_data.get("current_balance")
        raw_debt = cash_data.get("debt")
        inputs_cash = (raw_balance if isinstance(raw_balance, (int, float)) else 0) - (
            raw_debt if isinstance(raw_debt, (int, float)) else 0
        )
        if (
            runway_cash is not None
            and isinstance(runway_cash, (int, float))
            and isinstance(raw_balance, (int, float))
            and abs(inputs_cash) >= 1000
        ):
            delta_pct = abs(runway_cash - inputs_cash) / abs(inputs_cash) * 100
            if delta_pct > 10:
                currency_code = _resolve_currency(inputs, runway)
                warnings.append(
                    _warn(
                        "RUNWAY_INCONSISTENCY",
                        f"Runway net_cash ({_fmt_usd(runway_cash, currency_code)}) differs from inputs "
                        f"net cash ({_fmt_usd(inputs_cash, currency_code)}) by {delta_pct:.0f}%",
                    )
                )

    # 6. CHECKLIST_RUNWAY_CONTRADICTION -- CASH_* failures + default_alive: true
    if _usable(checklist) and _usable(runway):
        items = _as_list(checklist.get("items"))
        cash_fails = [
            i
            for i in items
            if isinstance(i, dict) and str(i.get("id", "")).startswith("CASH_") and i.get("status") == "fail"
        ]
        scenarios = _as_list(runway.get("scenarios"))
        base_scenario = next((s for s in scenarios if s.get("name") == "base"), None)
        if cash_fails and base_scenario and base_scenario.get("default_alive") is True:
            fail_ids = [str(f.get("id", "?")) for f in cash_fails]
            warnings.append(
                _warn(
                    "RUNWAY_INCONSISTENCY",
                    f"Checklist items {fail_ids} failed (cash/burn issues) but runway "
                    f"base scenario shows default_alive: true — review inputs for consistency",
                )
            )
        # Also flag cash direction warnings from runway scenarios
        for s in scenarios:
            cdw = s.get("cash_direction_warning")
            if cdw:
                warnings.append(
                    _warn(
                        "RUNWAY_INCONSISTENCY",
                        f"Scenario '{s.get('name', '?')}': {cdw}",
                    )
                )

    # 7. METRICS_GAPS -- unit economics has few computed metrics
    if _usable(unit_economics):
        ue_summary = _as_dict(unit_economics.get("summary"))
        computed = ue_summary.get("computed", 0)
        if isinstance(computed, int) and computed < 2:
            warnings.append(
                _warn(
                    "METRICS_GAPS",
                    f"Unit economics computed only {computed} metrics (recommend 2+)",
                )
            )

    return warnings


def _section_title(inputs: dict[str, Any] | None) -> str:
    """Title section with company name."""
    if inputs is None:
        return "# Financial Model Review\n\n*No inputs artifact found.*\n"
    company = _as_dict(inputs.get("company"))
    company_name = company.get("company_name", "Unknown Company")
    return f"# Financial Model Review: {company_name}\n"


def _section_executive_summary(
    inputs: dict[str, Any] | None,
    checklist: dict[str, Any] | None,
    unit_economics: dict[str, Any] | None,
    runway: dict[str, Any] | None,
) -> str:
    """Executive summary with stage, overall status, and key metrics."""
    lines = ["## Executive Summary\n"]
    data_confidence = "exact"  # safe default; overwritten if inputs present

    if inputs is not None and not _is_stub(inputs):
        company = _as_dict(inputs.get("company"))
        stage = company.get("stage", "unknown")
        sector = company.get("sector", "unknown")
        data_confidence = company.get("data_confidence", "exact")
        model_format = company.get("model_format", "spreadsheet")
        lines.append(f"**Stage:** {stage}  ")
        lines.append(f"**Sector:** {sector}  ")
        if data_confidence != "exact":
            dq_label = "Mixed" if data_confidence == "mixed" else "Estimated"
            lines.append(f"**Data Quality:** {dq_label} — review based on {model_format}, not audited financials  ")

    if checklist is not None and not _is_stub(checklist):
        summary = _as_dict(checklist.get("summary"))
        status = summary.get("overall_status", "unknown")
        score = summary.get("score_pct", 0)
        model_maturity = summary.get("model_maturity_pct")
        if model_maturity is None and data_confidence != "exact":
            bq_score = summary.get("business_quality_pct")
            if bq_score is not None:
                lines.append(
                    f"**Deck Financial Readiness:** {status} ({bq_score:.0f}%) "
                    f"(business quality only — no spreadsheet model)  "
                )
            else:
                # all business items gated N/A — deck-readiness score not computable;
                # fall back to the overall score with an honest label
                lines.append(f"**Model Quality:** {status} ({score:.0f}%)  ")
        else:
            lines.append(f"**Model Quality:** {status} ({score:.0f}%)  ")

    if unit_economics is not None and not _is_stub(unit_economics):
        metrics = _as_list(unit_economics.get("metrics"))
        key_names = {"cac", "ltv", "gross_margin", "ltv_cac_ratio", "burn_multiple"}
        key_metrics = [m for m in metrics if m.get("name") in key_names and m.get("value") is not None]
        if key_metrics:
            parts = []
            for m in key_metrics:
                name = m["name"].upper().replace("_", " ")
                val = m["value"]
                rating = m.get("rating", "")
                if isinstance(val, float) and val < 10:
                    parts.append(f"{name}: {val:.2f} ({rating})")
                else:
                    parts.append(f"{name}: {_fmt_number(val)} ({rating})")
            lines.append(f"**Key Metrics:** {', '.join(parts)}  ")

    if runway is not None and not _is_stub(runway):
        scenarios = _as_list(runway.get("scenarios"))
        base = next((s for s in scenarios if s.get("name") == "base"), None)
        if base:
            months_raw = base.get("runway_months")
            alive = base.get("default_alive", None)
            alive_str = "Yes" if alive else "No" if alive is not None else "Unknown"
            # Derive breakeven month when base scenario is default-alive (months_raw is None)
            be_month_exec: int | None = None
            if months_raw is None:
                projs_exec = _as_list(base.get("monthly_projections"))
                be_month_exec = next(
                    (p["month"] for p in projs_exec if isinstance(p, dict) and p.get("net_burn", 1) <= 0),
                    None,
                )
            lines.append(
                f"**Base Runway:** {_format_runway_months(months_raw, be_month_exec)} (Default Alive: {alive_str})  "
            )
            # A default-alive headline of "Infinite" hides the founder's actual cash
            # position: the projection holds burn flat while revenue compounds, an
            # assumption a seed company hiring plan almost never survives. Pair the
            # optimistic headline with the static (today's-burn) floor so the two
            # never travel apart — see runway.py's static_runway_months + risk_assessment.
            if months_raw is None:
                static_months = base.get("static_runway_months")
                if static_months is not None:
                    lines.append(
                        f"**At Today's Burn (flat, no growth):** {static_months:g} months — "
                        'the "Infinite" figure above assumes burn stays flat while revenue grows; '
                        "treat this static figure as the planning number  "
                    )

    return "\n".join(lines) + "\n"


def _section_checklist(checklist: dict[str, Any] | None) -> str:
    """Checklist results section."""
    if checklist is None:
        return "## Checklist Results\n\n*No checklist data available.*\n"
    if _is_stub(checklist):
        return f"## Checklist Results\n\n*Checklist not performed -- {checklist.get('reason', 'unknown reason')}*\n"

    summary = _as_dict(checklist.get("summary"))
    lines = ["## Checklist Results\n"]

    score = summary.get("score_pct", 0)
    total = summary.get("total", 0)
    pass_ct = summary.get("pass", 0)
    fail_ct = summary.get("fail", 0)
    warn_ct = summary.get("warn", 0)
    na_ct = summary.get("not_applicable", 0)
    status = summary.get("overall_status", "unknown")

    lines.append(f"**Overall:** {status} ({score:.0f}%)  ")
    lines.append(f"**Breakdown:** {pass_ct} pass, {fail_ct} fail, {warn_ct} warn, {na_ct} N/A out of {total} items\n")

    # Failed items
    failed_items = _as_list(summary.get("failed_items"))
    if failed_items:
        lines.append("### Failed Items\n")
        for item in failed_items:
            item_id = item.get("id", "?")
            label = item.get("label", item_id)
            evidence = item.get("evidence", "")
            lines.append(f"- **{item_id}** ({label}): {_md_safe(evidence)}")
        lines.append("")

    # Warned items
    warned_items = _as_list(summary.get("warned_items"))
    if warned_items:
        lines.append("### Warned Items\n")
        for item in warned_items:
            item_id = item.get("id", "?")
            label = item.get("label", item_id)
            evidence = item.get("evidence", "")
            lines.append(f"- **{item_id}** ({label}): {_md_safe(evidence)}")
        lines.append("")

    # By category summary
    by_category = _as_dict(summary.get("by_category"))
    if by_category:
        lines.append("### By Category\n")
        lines.append("| Category | Pass | Fail | Warn | N/A |")
        lines.append("|----------|------|------|------|-----|")
        for cat_name, cat_data in by_category.items():
            cd = _as_dict(cat_data)
            lines.append(
                f"| {_md_safe(cat_name)} | {cd.get('pass', 0)} | {cd.get('fail', 0)} "
                f"| {cd.get('warn', 0)} | {cd.get('not_applicable', 0)} |"
            )
        lines.append("")

    return "\n".join(lines) + "\n"


def _section_unit_economics(unit_economics: dict[str, Any] | None) -> str:
    """Unit economics section with metrics table."""
    if unit_economics is None:
        return "## Unit Economics\n\n*No unit economics data available.*\n"
    if _is_stub(unit_economics):
        return (
            f"## Unit Economics\n\n*Unit economics not computed -- {unit_economics.get('reason', 'unknown reason')}*\n"
        )

    metrics = _as_list(unit_economics.get("metrics"))
    if not metrics:
        return "## Unit Economics\n\n*No metrics computed.*\n"

    currency_code = _resolve_currency(unit_economics)
    lines = ["## Unit Economics\n"]

    # Check if metrics are based on estimated inputs
    if metrics:
        has_estimated = any(m.get("confidence") in ("estimated", "mixed") for m in metrics)
        if has_estimated:
            lines.append("\n*Metrics below are based on estimated inputs.*\n")

    # Non-USD reviews otherwise render a page of numbers with no assessment: with the
    # USD-denominated absolute floors correctly suppressed, LTV/CAC, burn multiple and
    # Rule of 40 all land `contextual` at once. The dimensionless thresholds DID compare
    # exactly (a 1.5x ratio is 1.5x in any currency), and that grade is preserved on the
    # metric as `benchmark_reference_rating`. Lead with it, clearly marked as a reference
    # rather than a verdict — an unqualified "Contextual" tells the founder nothing, and
    # the audience most likely to file in a local currency is the one most in need of the
    # feedback.
    has_reference_grades = any(m.get("benchmark_reference_rating") for m in metrics if isinstance(m, dict))
    if has_reference_grades:
        lines.append(
            "\n*Some metrics show a **reference grade** rather than a rating. Those ratios were "
            "compared against dimensionless stage benchmarks — exact in any currency, no FX conversion "
            "involved — but the benchmark set is calibrated on USD-market companies, so the grade is "
            "shown for reference and withheld from the rating. Absolute thresholds (ARR materiality "
            "floors, ACV tiers) need an FX rate and stay uncompared.*\n"
        )

    lines.append("| Metric | Value | Rating | Evidence |")
    lines.append("|--------|-------|--------|----------|")

    for m in metrics:
        name = m.get("name", "?").upper().replace("_", " ")
        val = m.get("value")
        rating = RATING_LABELS.get(m.get("rating", ""), m.get("rating", ""))
        reference_rating = m.get("benchmark_reference_rating")
        if reference_rating:
            reference_label = RATING_LABELS.get(reference_rating, reference_rating)
            rating = f"{reference_label} (reference)"
        evidence = _md_safe(m.get("evidence", ""))

        if val is None:
            val_str = "N/A"
        elif isinstance(val, float) and val <= 1.0 and m.get("name") in ("gross_margin", "nrr", "grr"):
            val_str = _fmt_pct(val)
        elif isinstance(val, (int, float)) and m.get("name") in ("cac", "ltv"):
            val_str = _fmt_usd(val, currency_code)
        elif isinstance(val, float):
            val_str = f"{val:.2f}"
        else:
            val_str = _fmt_number(val)

        lines.append(f"| {name} | {val_str} | {rating} | {evidence} |")

    # Summary
    ue_summary = _as_dict(unit_economics.get("summary"))
    if ue_summary:
        strong = ue_summary.get("strong", 0)
        acceptable = ue_summary.get("acceptable", 0)
        warning = ue_summary.get("warning", 0)
        fail = ue_summary.get("fail", 0)
        lines.append(f"\n**Summary:** {strong} strong, {acceptable} acceptable, {warning} warning, {fail} fail")

    return "\n".join(lines) + "\n"


def _section_runway(runway: dict[str, Any] | None) -> str:
    """Runway analysis section with scenarios table."""
    if runway is None:
        return "## Runway Analysis\n\n*No runway data available.*\n"
    if _is_stub(runway):
        return f"## Runway Analysis\n\n*Runway analysis not performed -- {runway.get('reason', 'unknown reason')}*\n"

    currency_code = _resolve_currency(runway)
    lines = ["## Runway Analysis\n"]

    # Baseline
    baseline = _as_dict(runway.get("baseline"))
    if baseline:
        net_cash = baseline.get("net_cash")
        burn = baseline.get("monthly_burn")
        rev = baseline.get("monthly_revenue")
        if net_cash is not None:
            lines.append(f"**Net Cash:** {_fmt_usd(net_cash, currency_code)}  ")
        if burn is not None:
            lines.append(f"**Monthly Burn:** {_fmt_usd(burn, currency_code)}  ")
        if rev is not None:
            lines.append(f"**Monthly Revenue:** {_fmt_usd(rev, currency_code)}  ")
        lines.append("")

    # Burn sensitivity table (partial analysis when cash balance unknown).
    # For a non-USD model, runway.py already skips producing this table (it is
    # a fixed USD-hypothetical grid that can't be presented as native-currency
    # values), so burn_sensitivity is empty and this section is a no-op.
    burn_sensitivity = _as_list(runway.get("burn_sensitivity"))
    if burn_sensitivity:
        lines.append("### Burn-Based Sensitivity (Cash Balance Unknown)\n")
        lines.append("| Starting Cash | Estimated Runway |")
        lines.append("|---------------|-----------------|")
        for row in burn_sensitivity:
            cash_val = row.get("starting_cash", 0)
            rw = row.get("runway_months")
            rw_str = f"{rw:.1f} months" if rw is not None else "Infinite"
            lines.append(f"| {_fmt_usd(cash_val, currency_code)} | {rw_str} |")
        lines.append("")

    # Scenarios table
    scenarios = _as_list(runway.get("scenarios"))
    if scenarios:
        lines.append("### Scenarios\n")
        lines.append(
            "| Scenario | Runway (months) | Runway at Today's Burn | Cash-Out Date | Decision Point "
            "| Default Alive | Assumptions |"
        )
        lines.append(
            "|----------|----------------|------------------------|---------------|----------------"
            "|---------------|-------------|"
        )
        for s in scenarios:
            name = s.get("name", "?")
            months_raw = s.get("runway_months")
            if months_raw is None:
                # Derive breakeven month from projections when available
                projs = _as_list(s.get("monthly_projections"))
                be_month: int | None = next(
                    (p["month"] for p in projs if isinstance(p, dict) and p.get("net_burn", 1) <= 0),
                    None,
                )
                months = _format_runway_months(None, be_month)
            else:
                months = months_raw
            # The static (today's-burn, no growth) floor, alongside the projected number for
            # EVERY scenario row — not just base — so a default-alive slow/crisis case doesn't
            # hide the same flat-burn assumption the base-case fix above addresses.
            static_months = s.get("static_runway_months")
            static_str = f"{static_months:g} months" if isinstance(static_months, (int, float)) else "—"
            cash_out = s.get("cash_out_date", "?")
            decision = s.get("decision_point", "?")
            alive = s.get("default_alive", None)
            alive_str = "Yes" if alive else "No" if alive is not None else "?"
            # Build assumptions string from scenario parameters
            assumption_parts: list[str] = []
            growth_rate = s.get("growth_rate")
            if growth_rate is not None:
                assumption_parts.append(f"growth {growth_rate * 100:.0f}%/mo")
            burn_change = s.get("burn_change")
            if burn_change is not None:
                sign = "+" if burn_change >= 0 else ""
                assumption_parts.append(f"burn {sign}{burn_change * 100:.0f}%")
            fx_adjustment = s.get("fx_adjustment")
            if fx_adjustment is not None and fx_adjustment != 0:
                sign = "+" if fx_adjustment >= 0 else ""
                assumption_parts.append(f"fx {sign}{fx_adjustment * 100:.0f}%")
            assumptions_str = _md_safe(", ".join(assumption_parts)) if assumption_parts else "—"
            lines.append(
                f"| {name} | {months} | {static_str} | {cash_out} | {decision} | {alive_str} | {assumptions_str} |"
            )
        lines.append("")

    # Post-raise
    post_raise = _as_dict(runway.get("post_raise"))
    if post_raise and post_raise.get("raise_amount"):
        lines.append("### Post-Raise Projection\n")
        lines.append(f"**Raise Amount:** {_fmt_usd(post_raise['raise_amount'], currency_code)}  ")
        lines.append(f"**New Cash:** {_fmt_usd(post_raise.get('new_cash', 0), currency_code)}  ")
        new_rw = post_raise.get("new_runway_months")
        lines.append(f"**New Runway:** {new_rw if new_rw else '∞'} months  ")
        meets = post_raise.get("meets_target")
        if meets is not None:
            lines.append(f"**Meets Target:** {'Yes' if meets else 'No'}  ")
        lines.append("")

    # Risk assessment
    risk = runway.get("risk_assessment")
    if risk:
        lines.append(f"**Risk Assessment:** {risk}\n")

    return "\n".join(lines) + "\n"


_MODEL_PREREQS: dict[str, str] = {
    "Structure & Presentation": "A dedicated spreadsheet model with separate tabs",
    "Expenses, Cash & Runway": "Detailed expense breakdown, headcount plan, and cash flow projections",
}


def _section_model_completeness(
    inputs: dict[str, Any] | None,
    checklist: dict[str, Any] | None,
) -> str:
    """Model completeness section for non-spreadsheet reviews."""
    if inputs is None:
        return ""
    model_format = _as_dict(inputs.get("company")).get("model_format", "spreadsheet")
    if model_format == "spreadsheet":
        return ""

    lines = ["## Model Completeness\n"]
    lines.append(f"*This review was based on a {model_format} — not a full spreadsheet model.*\n")

    if _usable(checklist):
        items = _as_list(checklist.get("items"))
        na_items = [i for i in items if isinstance(i, dict) and i.get("status") == "not_applicable"]
        by_cat: dict[str, list[str]] = {}
        for item in na_items:
            cat = str(item.get("category", "Other"))
            by_cat.setdefault(cat, []).append(str(item.get("label", item.get("id", "?"))))

        if by_cat:
            lines.append("### Items Not Evaluated\n")
            for cat, labels in by_cat.items():
                prereq = _MODEL_PREREQS.get(cat, "Additional financial data")
                lines.append(f"**{cat}** ({len(labels)} items) — requires: {prereq}")
                for label in labels[:5]:
                    lines.append(f"  - {_md_safe(label)}")
                if len(labels) > 5:
                    lines.append(f"  - ...and {len(labels) - 5} more")
                lines.append("")

        lines.append("### What to Build Next\n")
        lines.append("1. **Start with a basic 3-tab model:** Assumptions, P&L, Cash Flow")
        lines.append("2. **Add headcount-driven expenses:** Map team growth to burn rate")
        lines.append("3. **Include scenario toggles:** Base, optimistic, and downside cases")
        lines.append("4. **Model runway explicitly:** Monthly cash balance projections to cash-out date")
        lines.append("")

    return "\n".join(lines) + "\n"


def _section_agent_supplied(inputs: dict[str, Any] | None) -> str:
    """Disclose which computation-feeding values the agent defaulted.

    The declaration exists so a defaulted value is not indistinguishable from a
    founder-stated one downstream. Confirming it in the live chat turn does not
    achieve that: the report is what gets saved and forwarded, and a reader of
    the file was not in the conversation.
    """
    if inputs is None:
        return ""
    declared = inputs.get("agent_supplied")
    if not isinstance(declared, list) or not declared:
        return ""

    lines = ["## Agent-Supplied Values\n"]
    lines.append(
        "These were defaulted during extraction, not stated by the founder. They feed the "
        "figures above, so confirm them before relying on any number derived from them:\n"
    )
    for path in declared:
        if isinstance(path, str) and path.strip():
            lines.append(f"- `{_md_safe(path.strip())}`")
    return "\n".join(lines) + "\n"


def _section_overrides(inputs: dict[str, Any] | None) -> str:
    """Warning overrides section for audit transparency."""
    if inputs is None:
        return ""
    overrides = _as_list(_as_dict(inputs.get("metadata")).get("warning_overrides"))
    if not overrides:
        return ""

    # Separate agent vs founder overrides.
    # Dedupe by code alone (legacy overrides lack 'field'), so a code-only
    # legacy/agent override and a code+field founder override for the same
    # warning are not shown in both sections.
    agent_overrides = [o for o in overrides if isinstance(o, dict) and o.get("reviewed_by") == "agent"]
    legacy = [o for o in overrides if isinstance(o, dict) and not o.get("reviewed_by")]
    acknowledged_codes = {o.get("code") for o in agent_overrides + legacy if o.get("code")}
    founder_only = [
        o
        for o in overrides
        if isinstance(o, dict) and o.get("reviewed_by") == "founder" and o.get("code") not in acknowledged_codes
    ]

    lines: list[str] = []
    if agent_overrides or legacy:
        lines.append("## Acknowledged Warnings\n")
        lines.append("The following validation warnings were reviewed and acknowledged:\n")
        for o in agent_overrides + legacy:
            code = o.get("code", "?")
            reason = o.get("reason", "No reason provided")
            lines.append(f"- **{_humanize_warning(code)}** (`{code}`): {_md_safe(reason)}")

    if founder_only:
        lines.append("\n## Founder-Reported Context\n")
        lines.append("The following were noted by the founder during extraction review (not agent-verified):\n")
        for o in founder_only:
            code = o.get("code", "?")
            reason = o.get("reason", "No reason provided")
            lines.append(f"- **{_humanize_warning(code)}** (`{code}`): {_md_safe(reason)} *(founder-reported)*")

    return "\n".join(lines) + "\n" if lines else ""


def _section_corrections(extraction_corrections: dict[str, Any] | None) -> str:
    """Optional 'Corrections Applied' subsection from extraction_corrections.json.

    Only rendered when the artifact exists (most runs won't have it).
    Shape: {corrections: [{path, was, now}, ...], timestamp, ...}
    """
    if extraction_corrections is None or _is_stub(extraction_corrections):
        return ""

    corrections = _as_list(extraction_corrections.get("corrections"))
    if not corrections:
        return ""

    _ABSENT = object()

    def _cell(c: dict[str, Any], keys: tuple[str, ...]) -> Any:
        """Resolve a value across the producer's key aliases; _ABSENT if no key present."""
        for k in keys:
            if k in c:
                return c[k]
        return _ABSENT

    def _render(v: Any) -> str:
        if v is _ABSENT:
            return "?"
        if v is None:
            return "— not in source"
        return _md_safe(str(v))

    # Emit the Reason column only when at least one entry carries one, so the
    # founder-patch table keeps its 3-column shape.
    has_reason = any(isinstance(c, dict) and c.get("reason") for c in corrections)
    cols = ["Field", "Original", "Corrected"] + (["Reason"] if has_reason else [])

    lines = ["## Corrections Applied\n"]
    lines.append("_The following extracted values were corrected during the review._\n")
    lines.append("| " + " | ".join(cols) + " |")
    lines.append("|" + "|".join(["---"] * len(cols)) + "|")
    for c in corrections:
        field = _md_safe(str(c.get("path", c.get("field", "?"))))
        if c.get("type") == "replace_array":
            was = f"{c.get('was_length', '?')} rows"
            now = f"{c.get('now_length', '?')} rows"
        else:
            # Dispatch path: old/new/reason. Founder-patch path: was/now.
            was = _render(_cell(c, ("old", "was", "original")))
            now = _render(_cell(c, ("new", "now", "corrected")))
        row = [field, was, now]
        if has_reason:
            row.append(_md_safe(str(c.get("reason", ""))))
        lines.append("| " + " | ".join(row) + " |")

    # Timestamp if present
    ts = extraction_corrections.get("timestamp")
    if ts:
        lines.append(f"\n_Applied: {ts}_")

    return "\n".join(lines) + "\n"


def _section_warnings(warnings: list[dict[str, str]]) -> str:
    """Validation warnings section."""
    if not warnings:
        return ""

    sev_icons = {"high": "!!!", "medium": "!!", "acknowledged": "~", "low": "i", "info": "~"}
    lines = ["## Validation Warnings\n"]
    for w in warnings:
        sev = w.get("severity", "?")
        code = w.get("code", "?")
        msg = w.get("founder_message") or w.get("message", "?")
        label = _humanize_warning(code)
        icon = sev_icons.get(sev, "")
        prefix = f"[{icon}] " if icon else ""
        lines.append(f"- {prefix}**{label}:** {msg}")
    return "\n".join(lines) + "\n"


_SEVERITY_RANK: dict[str, int] = {"high": 0, "medium": 1, "low": 2}


def _truncate_actionable_items(
    failed: list[dict[str, Any]],
    warned: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], bool, int]:
    """Severity-sorted truncation for coaching_payload.

    When total failed + warned > 30, keep top-30 entries prioritizing high
    severity then medium then low. Within each severity tier, original list
    order is preserved (stable sort). Failed items are always prioritized over
    warned items at the same severity level.

    Returns (failed_out, warned_out, was_truncated, dropped_count).
    """
    total = len(failed) + len(warned)
    if total <= 30:
        return failed, warned, False, 0

    # Tag each item with its source list so we can redistribute after sorting.
    tagged_failed = [("failed", item) for item in failed]
    tagged_warned = [("warned", item) for item in warned]
    combined = tagged_failed + tagged_warned

    # Stable sort: failed-before-warned at same severity is already guaranteed
    # because tagged_failed comes first in combined (Python sort is stable).
    combined.sort(key=lambda t: _SEVERITY_RANK.get(t[1].get("severity", "low"), 2))

    kept = combined[:30]
    dropped_count = total - 30

    failed_out = [item for src, item in kept if src == "failed"]
    warned_out = [item for src, item in kept if src == "warned"]
    return failed_out, warned_out, True, dropped_count


def _emit_coaching_payload(
    inputs: dict[str, Any] | None,
    checklist: dict[str, Any] | None,
    validation_warnings: list[dict[str, str]],
    review_dir: str,
    report_path: str,
    insertion_marker: str,
    runway: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the v0.4.2 coaching_payload for financial-model-review.

    Read from existing artifacts; do not fabricate fields.
    company_name is sourced from inputs.json → company.company_name.
    runway_months is the base scenario value (may be null for default-alive companies).
    """
    summary: dict[str, Any] = {}
    if checklist is not None:
        summary = _as_dict(checklist.get("summary"))

    raw_failed: list[dict[str, Any]] = _as_list(summary.get("failed_items"))
    raw_warned: list[dict[str, Any]] = _as_list(summary.get("warned_items"))

    failed_items, warned_items, truncated, truncated_count = _truncate_actionable_items(raw_failed, raw_warned)

    company_name: str | None = None
    if inputs is not None:
        company_name = _as_dict(inputs.get("company")).get("company_name")

    runway_months_base: float | int | None = None
    # The static runway (cash / today's net burn, no growth) travels with it so the headline always has a
    # concrete number even when `runway_months` is legitimately null for a default-alive company. Without
    # it, the Main-Thread Return has a headline field it cannot render — see the SKILL.md step, which now
    # says to lead with this figure in that case.
    static_runway_base: float | int | None = None
    if isinstance(runway, dict):
        scenarios = _as_list(runway.get("scenarios"))
        base = next(
            (s for s in scenarios if isinstance(s, dict) and s.get("name") in ("base", "baseline")),
            scenarios[0] if scenarios and isinstance(scenarios[0], dict) else None,
        )
        if base is not None:
            runway_months_base = base.get("runway_months")
            static_runway_base = base.get("static_runway_months")

    # When base scenario is default-alive, runway_months is null by design.
    # Add a sibling note so consumers don't misread null as "unknown".
    runway_note: str | None = None
    if isinstance(runway, dict):
        scenarios = _as_list(runway.get("scenarios"))
        base = next(
            (s for s in scenarios if isinstance(s, dict) and s.get("name") in ("base", "baseline")),
            scenarios[0] if scenarios and isinstance(scenarios[0], dict) else None,
        )
        if base is not None and base.get("default_alive") is True and base.get("runway_months") is None:
            runway_note = (
                "default-alive: projected cash never depletes at current trajectory; runway_months is null by design"
            )

    return {
        "schema_version": "v0.4.2-financial-model-review",
        "summary": {
            "score_pct": summary.get("score_pct"),
            "overall_status": summary.get("overall_status"),
            "total": summary.get("total"),
            "pass": summary.get("pass"),
            "fail": summary.get("fail"),
            "warn": summary.get("warn"),
            "not_applicable": summary.get("not_applicable"),
        },
        "failed_items": failed_items,
        "warned_items": warned_items,
        "high_severity_warnings": [w["code"] for w in validation_warnings if w.get("severity") == "high"],
        "company_name": company_name,
        "runway_months": runway_months_base,
        "static_runway_months": static_runway_base,
        **({"base_runway_note": runway_note} if runway_note is not None else {}),
        "review_dir": review_dir,
        "report_path": report_path,
        "insertion_marker": insertion_marker,
        "truncated": truncated,
        "truncated_count": truncated_count,
    }


def compose(dir_path: str, report_path: str | None = None) -> dict[str, Any]:
    """Main composition: load artifacts, validate, assemble report."""
    # Load all artifacts
    all_names = REQUIRED_ARTIFACTS + OPTIONAL_ARTIFACTS
    artifacts: dict[str, dict[str, Any] | None] = {}
    for name in all_names:
        artifacts[name] = _load_artifact(dir_path, name)

    artifacts_found = [n for n in all_names if artifacts[n] is not None and artifacts[n] is not _CORRUPT]
    artifacts_missing = [n for n in all_names if artifacts[n] is None]

    # Run validation
    warnings = validate_artifacts(artifacts)

    # Assemble report -- treat corrupt artifacts as None for rendering
    def _render_safe(data: dict[str, Any] | None) -> dict[str, Any] | None:
        return None if data is _CORRUPT else data

    inputs = _render_safe(artifacts.get("inputs.json"))
    checklist = _render_safe(artifacts.get("checklist.json"))
    unit_economics = _render_safe(artifacts.get("unit_economics.json"))
    runway = _render_safe(artifacts.get("runway.json"))
    extraction_corrections = _render_safe(artifacts.get("extraction_corrections.json"))

    # Render every section EXCEPT the Warnings section first; the Warnings
    # section is spliced in after the marker pre-scan so MARKER_COLLISION (which
    # is itself a warning) is reflected in both the status and the report body.
    sections = [
        _section_title(inputs),
        _section_executive_summary(inputs, checklist, unit_economics, runway),
        _section_checklist(checklist),
        _section_model_completeness(inputs, checklist),
        _section_unit_economics(unit_economics),
        _section_runway(runway),
        _section_corrections(extraction_corrections),
        _section_overrides(inputs),
        _section_agent_supplied(inputs),
    ]

    body_without_warnings = "\n".join(sections)

    # v0.4.2 Mitigation 2: per-run uuid marker for Context B's Edit
    marker = f"<!-- COACHING_INSERTION_POINT_{uuid.uuid4().hex[:8]} -->"

    # Pre-scan: check assembled body BEFORE appending the marker (otherwise we
    # always find our own emission). Agent post-Edit verification uses the
    # EXACT uuid (per-run), so substring collisions with body content are
    # informational only — but worth flagging so authors can sanitize.
    if "<!-- COACHING_INSERTION_POINT_" in body_without_warnings:
        warnings.append(
            _warn(
                "MARKER_COLLISION",
                (
                    "Body content contains marker substring; agent post-Edit verification "
                    "uses the EXACT uuid (per-run) so this is informational only — "
                    "body sanitization recommended."
                ),
            )
        )

    # Determine status AFTER the MARKER_COLLISION pre-scan so status and the
    # rendered Warnings section stay consistent with validation.warnings.
    status = "clean" if not warnings else "warnings"

    # Splice the Warnings section in now that the warnings list is final.
    report_markdown = body_without_warnings + "\n" + _section_warnings(warnings)

    report_markdown += (
        f"\n\n{marker}\n\n---\n"
        "*Generated by [founder skills](https://github.com/lool-ventures/founder-skills)"
        " by [lool ventures](https://lool.vc)"
        " — Financial Model Review Agent*  \n"
        # No command line here. A founder reading this in Cowork has no shell to run it in, and a
        # script invocation with flags in a deliverable is the same plumbing leak the narration rule
        # forbids — it just happens to sit in the report instead of a chat message. Ask for the thing,
        # not the command.
        "*Want to test what-if scenarios (burn cuts, growth-rate changes)? Ask for the interactive "
        "explorer and it will be generated for you.*  \n"
        "*[Share feedback](https://github.com/lool-ventures/founder-skills/discussions/new?category=ideas-feedback)*\n"
    )

    # --- founder-text policy (shared fleet module) ------------------------------------------------
    # Runs on the FINAL assembled markdown — after the warnings section and footer — because that is
    # the exact string the founder reads, and because producer warning messages are where the
    # internal tokens actually live.
    _ft = _founder_text_policy()
    if _ft is not None:
        # Identifier keep-set derived from the DATA, not hand-listed: an id present in the artifacts
        # is an id whatever its shape, and rewriting one makes the markdown disagree with the JSON
        # about what a thing is called (cap-table's `safe_conv` is the case that proved this).
        _keep = _ft.identifier_values(artifacts)
        report_markdown = _ft.substitute(report_markdown, extra_keep=_keep)
        _found = _ft.scan(report_markdown, extra_keep=_keep)
        for _tok in _found["enums"]:
            warnings.append(
                _warn(
                    "FOUNDER_TEXT_TOKEN",
                    f"the report contains the internal token '{_tok}' — a founder cannot act on it; "
                    f"render it through the shared founder-text policy or stop emitting it",
                )
            )
        for _fn in _found["filenames"]:
            warnings.append(
                _warn(
                    "FOUNDER_TEXT_TOKEN",
                    f"the report names the internal file '{_fn}' — drop the reference rather than renaming it",
                )
            )

    # Stderr summary
    print(f"Artifacts found: {len(artifacts_found)}/{len(all_names)}", file=sys.stderr)
    if warnings:
        high = [w for w in warnings if w["severity"] == "high"]
        medium = [w for w in warnings if w["severity"] == "medium"]
        print(f"Warnings: {len(high)} high, {len(medium)} medium", file=sys.stderr)
        for w in warnings:
            print(f"  [{w['severity'].upper()}] {w['code']}: {w['message']}", file=sys.stderr)
    else:
        print("No warnings.", file=sys.stderr)

    # v0.4.2 Mitigation 2: structured coaching payload for Context B agent.
    # Use the same uuid marker generated above as the single source of truth.
    resolved_report_path = report_path or os.path.join(os.path.abspath(dir_path), "report.md")
    coaching_payload = _emit_coaching_payload(
        inputs=inputs,
        checklist=checklist,
        validation_warnings=warnings,
        review_dir=os.path.abspath(dir_path),
        report_path=resolved_report_path,
        insertion_marker=marker,
        runway=runway,
    )

    # Determine model_format for --strict context
    model_format = "spreadsheet"
    if _usable(inputs):
        model_format = _as_dict(inputs.get("company")).get("model_format", "spreadsheet")

    return {
        "report_markdown": report_markdown,
        "validation": {
            "status": status,
            "warnings": warnings,
            "artifacts_found": artifacts_found,
            "artifacts_missing": artifacts_missing,
            "model_format": model_format,
        },
        "coaching_payload": coaching_payload,
    }


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Compose financial model review report from artifacts")
    p.add_argument("-d", "--dir", required=True, help="Directory containing JSON artifacts")
    p.add_argument("--pretty", action="store_true", help="Pretty-print JSON")
    p.add_argument("-o", "--output", help="Write JSON to file instead of stdout")
    p.add_argument(
        "--strict", action="store_true", help="Exit 1 on high-severity warnings (CI mode); medium does not block"
    )
    p.add_argument(
        "--write-md",
        help="Also write the report markdown to this path (in addition to JSON output via -o)",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()

    if not os.path.isdir(args.dir):
        print(f"Error: directory not found: {args.dir}", file=sys.stderr)
        sys.exit(1)

    report_path = os.path.abspath(args.write_md) if args.write_md else None
    result = compose(args.dir, report_path=report_path)

    if args.write_md:
        report_markdown = result.get("report_markdown", "")
        md_path = os.path.abspath(args.write_md)
        parent = os.path.dirname(md_path)
        if parent:
            try:
                os.makedirs(parent, exist_ok=True)
            except OSError as e:
                print(f"Error: cannot create directory for --write-md: {e}", file=sys.stderr)
                sys.exit(2)
        try:
            with open(md_path, "w", encoding="utf-8") as f:
                f.write(report_markdown if report_markdown.endswith("\n") else report_markdown + "\n")
        except OSError as e:
            print(f"Error: cannot write --write-md file: {e}", file=sys.stderr)
            sys.exit(2)

    indent = 2 if args.pretty else None
    out = json.dumps(result, indent=indent) + "\n"
    v = result["validation"]
    _write_output(
        out,
        args.output,
        summary={"validation": v["status"], "warnings": len(v["warnings"])},
    )

    # Post-write on-disk verification: confirm declared output files exist and are non-empty.
    if args.output:
        abs_out = os.path.abspath(args.output)
        if not os.path.isfile(abs_out) or os.path.getsize(abs_out) == 0:
            print(
                f"Error: output file missing or empty after write: {abs_out}",
                file=sys.stderr,
            )
            sys.exit(2)
    if args.write_md:
        abs_md = os.path.abspath(args.write_md)
        if not os.path.isfile(abs_md) or os.path.getsize(abs_md) == 0:
            print(
                f"Error: --write-md file missing or empty after write: {abs_md}",
                file=sys.stderr,
            )
            sys.exit(2)

    # Exit 1 if any required artifacts are missing (regardless of strict mode)
    missing_required = [w for w in result["validation"]["warnings"] if w["code"] == "MISSING_ARTIFACT"]
    if missing_required:
        print("Exiting with code 1: required artifacts missing", file=sys.stderr)
        sys.exit(1)

    if args.strict:
        # Strict blocks on high-severity data/structural warnings only.
        # CHECKLIST_FAILURES (medium) are review findings, not data errors.
        blocking = [w for w in result["validation"]["warnings"] if w["severity"] == "high"]
        if blocking:
            print("STRICT MODE: Exiting with code 1 due to warnings", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()
