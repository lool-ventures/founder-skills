#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
Regression tests for IC simulation HTML visualization script.

Run: pytest founder-skills/tests/test_visualize_ic_sim.py -v
All tests use subprocess to exercise the script exactly as the agent does.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import types
from typing import Any

from _dom import Element, by_attr, by_id, parse

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
IC_SIM_DIR = os.path.join(os.path.dirname(SCRIPT_DIR), "skills", "ic-sim", "scripts")

_DIMENSION_IDS = [
    # Team
    "team_founder_market_fit",
    "team_complementary_skills",
    "team_execution_speed",
    "team_coachability",
    # Market
    "market_size_credibility",
    "market_timing",
    "market_growth_trajectory",
    "market_entry_barriers",
    # Product
    "product_differentiation",
    "product_traction_evidence",
    "product_technical_moat",
    "product_user_love",
    # Business Model
    "biz_unit_economics",
    "biz_pricing_power",
    "biz_scalability",
    "biz_gross_margins",
    # Financials
    "fin_capital_efficiency",
    "fin_runway_plan",
    "fin_path_to_next_round",
    "fin_revenue_quality",
    # Risk
    "risk_single_point_failure",
    "risk_regulatory",
    "risk_competitive_response",
    "risk_customer_concentration",
    # Fund Fit
    "fit_thesis_alignment",
    "fit_portfolio_conflict",
    "fit_stage_match",
    "fit_value_add",
]

_CATEGORY_FOR_DIM = (
    ["Team"] * 4
    + ["Market"] * 4
    + ["Product"] * 4
    + ["Business Model"] * 4
    + ["Financials"] * 4
    + ["Risk"] * 4
    + ["Fund Fit"] * 4
)

_VALID_STARTUP: dict[str, Any] = {
    "company_name": "TestCo",
    "simulation_date": "2026-02-22",
    "stage": "seed",
    "one_liner": "Cloud accounting for SMBs",
    "sector": "Fintech",
    "geography": "United States",
    "business_model": "SaaS",
    "materials_provided": ["pitch deck"],
}

_VALID_FUND: dict[str, Any] = {
    "fund_name": "Test Fund",
    "mode": "generic",
    "thesis_areas": ["B2B SaaS"],
    "check_size_range": {"min": 500000, "max": 5000000, "currency": "USD"},
    "stage_focus": ["seed"],
    "archetypes": [
        {
            "role": "visionary",
            "focus_areas": ["market"],
        },
        {
            "role": "operator",
            "focus_areas": ["execution"],
        },
        {
            "role": "analyst",
            "focus_areas": ["numbers"],
        },
    ],
    "portfolio": [
        {"name": "FinLedger", "sector": "Fintech"},
        {"name": "DataPipe", "sector": "Data"},
    ],
    "sources": [],
    "validation": {"status": "valid", "errors": []},
}

_VALID_CONFLICT: dict[str, Any] = {
    "portfolio_size": 2,
    "conflicts": [],
    "summary": {
        "total_checked": 2,
        "conflict_count": 0,
        "has_blocking_conflict": False,
        "overall_severity": "clear",
    },
    "validation": {"status": "valid", "errors": []},
}

_VALID_DISCUSSION: dict[str, Any] = {
    "assessment_mode": "sub-agent",
    "partner_verdicts": [
        {
            "partner": "visionary",
            "verdict": "invest",
            "rationale": "Large market, clear timing catalyst",
        },
        {
            "partner": "operator",
            "verdict": "more_diligence",
            "rationale": "Strong PMF but GTM unclear",
        },
        {
            "partner": "analyst",
            "verdict": "more_diligence",
            "rationale": "Unit economics emerging, need cohorts",
        },
    ],
    "debate_sections": [
        {
            "topic": "GTM Motion",
            "exchanges": [
                {"partner": "operator", "position": "Need channel economics"},
            ],
        },
    ],
    "consensus_verdict": "more_diligence",
    "key_concerns": ["GTM unclear", "Need cohort data"],
    "diligence_requirements": ["Channel CAC", "Cohort curves"],
    "warnings": [],
    "_produced_by": "compose_discussion",
}

_VALID_SCORE: dict[str, Any] = {
    "items": [
        {
            "id": did,
            "category": cat,
            "label": "Test",
            "status": "strong_conviction",
            "evidence": "test",
            "notes": None,
        }
        for did, cat in zip(_DIMENSION_IDS, _CATEGORY_FOR_DIM, strict=True)
    ],
    "summary": {
        "total": 28,
        "strong_conviction": 28,
        "moderate_conviction": 0,
        "concern": 0,
        "dealbreaker": 0,
        "not_applicable": 0,
        "applicable": 28,
        "conviction_score": 100.0,
        "verdict": "invest",
        "by_category": {
            "Team": {
                "strong_conviction": 4,
                "moderate_conviction": 0,
                "concern": 0,
                "dealbreaker": 0,
                "not_applicable": 0,
            },
            "Market": {
                "strong_conviction": 4,
                "moderate_conviction": 0,
                "concern": 0,
                "dealbreaker": 0,
                "not_applicable": 0,
            },
            "Product": {
                "strong_conviction": 4,
                "moderate_conviction": 0,
                "concern": 0,
                "dealbreaker": 0,
                "not_applicable": 0,
            },
            "Business Model": {
                "strong_conviction": 4,
                "moderate_conviction": 0,
                "concern": 0,
                "dealbreaker": 0,
                "not_applicable": 0,
            },
            "Financials": {
                "strong_conviction": 4,
                "moderate_conviction": 0,
                "concern": 0,
                "dealbreaker": 0,
                "not_applicable": 0,
            },
            "Risk": {
                "strong_conviction": 4,
                "moderate_conviction": 0,
                "concern": 0,
                "dealbreaker": 0,
                "not_applicable": 0,
            },
            "Fund Fit": {
                "strong_conviction": 4,
                "moderate_conviction": 0,
                "concern": 0,
                "dealbreaker": 0,
                "not_applicable": 0,
            },
        },
        "dealbreakers": [],
        "top_concerns": [],
        "warnings": [],
    },
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_artifact_dir(artifacts: dict[str, Any]) -> str:
    """Create a temp dir with JSON artifacts. Returns dir path."""
    d = tempfile.mkdtemp(prefix="test-vis-ic-sim-")
    for name, data in artifacts.items():
        path = os.path.join(d, name)
        if isinstance(data, str):
            # Raw string (e.g. corrupt JSON)
            with open(path, "w", encoding="utf-8") as f:
                f.write(data)
        else:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f)
    return d


def _all_required_artifacts() -> dict[str, Any]:
    """Return all 5 required artifacts."""
    return {
        "startup_profile.json": _VALID_STARTUP,
        "fund_profile.json": _VALID_FUND,
        "conflict_check.json": _VALID_CONFLICT,
        "discussion.json": _VALID_DISCUSSION,
        "score_dimensions.json": _VALID_SCORE,
    }


def _run_visualize(
    artifact_dir: str,
    extra_args: list[str] | None = None,
) -> tuple[int, str, str]:
    """Run visualize.py and return (exit_code, stdout, stderr)."""
    cmd = [
        sys.executable,
        os.path.join(IC_SIM_DIR, "visualize.py"),
        "--dir",
        artifact_dir,
    ]
    if extra_args:
        cmd.extend(extra_args)
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.returncode, result.stdout, result.stderr


def _ring(doc: Element) -> Element:
    (ring,) = [e for e in doc.iter() if e.tag == "figure" and " percent" in (e.get("aria-label") or "")]
    return ring


def _ring_tone(doc: Element) -> str | None:
    """The ring's tone: its modifier class, the only place `_ui.score_ring` carries it."""
    m = re.search(r"\bui-ring--(\w+)\b", _ring(doc).get("class") or "")
    return m.group(1) if m else None


def _verdict(doc: Element) -> str:
    (verdict,) = by_attr(doc, "data-verdict")
    return verdict.text()


def _pill_tone(el: Element) -> str | None:
    m = re.search(r"\bui-pill--(\w+)\b", el.get("class") or "")
    return m.group(1) if m else None


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_complete_artifacts() -> None:
    """All 5 required artifacts -> valid HTML with all chart SVGs."""
    d = _make_artifact_dir(_all_required_artifacts())
    rc, stdout, stderr = _run_visualize(d)
    assert rc == 0, f"exit {rc}, stderr={stderr}"
    assert "<!DOCTYPE html>" in stdout
    assert "<svg" in stdout
    assert "TestCo" in stdout


def test_missing_optional_artifact() -> None:
    """No partner assessment files -> HTML renders fine."""
    d = _make_artifact_dir(_all_required_artifacts())
    rc, stdout, stderr = _run_visualize(d)
    assert rc == 0, f"exit {rc}, stderr={stderr}"
    assert "<!DOCTYPE html>" in stdout


def test_missing_required_artifact() -> None:
    """No score_dimensions.json -> HTML renders with placeholders."""
    arts = _all_required_artifacts()
    del arts["score_dimensions.json"]
    d = _make_artifact_dir(arts)
    rc, stdout, stderr = _run_visualize(d)
    assert rc == 0, f"exit {rc}, stderr={stderr}"
    assert "<!DOCTYPE html>" in stdout
    # Should contain placeholder text
    assert "not available" in stdout.lower() or "placeholder" in stdout.lower()


def test_corrupt_artifact() -> None:
    """Corrupt discussion.json -> no crash, placeholder."""
    arts = _all_required_artifacts()
    d = _make_artifact_dir(arts)
    # Overwrite discussion.json with corrupt content
    with open(os.path.join(d, "discussion.json"), "w") as f:
        f.write("{corrupt json!!!}")
    rc, stdout, stderr = _run_visualize(d)
    assert rc == 0, f"exit {rc}, stderr={stderr}"
    assert "<!DOCTYPE html>" in stdout
    assert "Data unavailable" in stdout


def test_stub_artifact() -> None:
    """score_dimensions.json = stub -> placeholder with reason."""
    arts = _all_required_artifacts()
    arts["score_dimensions.json"] = {
        "skipped": True,
        "reason": "Insufficient data",
    }
    d = _make_artifact_dir(arts)
    rc, stdout, stderr = _run_visualize(d)
    assert rc == 0, f"exit {rc}, stderr={stderr}"
    assert "<!DOCTYPE html>" in stdout
    assert "Insufficient data" in stdout


def test_output_flag() -> None:
    """-o /tmp/file.html writes to file, stdout empty."""
    d = _make_artifact_dir(_all_required_artifacts())
    with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as f:
        tmp = f.name
    try:
        rc, stdout, stderr = _run_visualize(d, extra_args=["-o", tmp])
        assert rc == 0, f"exit {rc}, stderr={stderr}"
        receipt = json.loads(stdout)
        assert receipt["ok"] is True
        with open(tmp, encoding="utf-8") as fh:
            content = fh.read()
        assert "<!DOCTYPE html>" in content
        assert "TestCo" in content
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def test_self_contained() -> None:
    """No external URLs in src/href attributes."""
    d = _make_artifact_dir(_all_required_artifacts())
    rc, stdout, stderr = _run_visualize(d)
    assert rc == 0, f"exit {rc}, stderr={stderr}"

    # Find all src="..." and href="..." attributes
    allowed = {
        "https://github.com/lool-ventures/founder-skills",
        "https://github.com/lool-ventures/founder-skills/discussions/new?category=ideas-feedback",
        "https://lool.vc",
    }
    src_matches = re.findall(r'(?:src|href)\s*=\s*"([^"]*)"', stdout)
    for url in src_matches:
        if url in allowed:
            continue
        assert not url.startswith("http://"), f"External HTTP URL: {url}"
        assert not url.startswith("https://"), f"External HTTPS URL: {url}"


def test_chart_data_values() -> None:
    """Conviction score 100.0 appears, partner verdicts appear."""
    d = _make_artifact_dir(_all_required_artifacts())
    rc, stdout, stderr = _run_visualize(d)
    assert rc == 0, f"exit {rc}, stderr={stderr}"
    # Score value
    assert "100.0" in stdout
    # Partner verdicts
    assert "Invest" in stdout
    assert "More Diligence" in stdout


def test_xss_safety_text() -> None:
    """company_name with script tag -> escaped in output."""
    arts = _all_required_artifacts()
    arts["startup_profile.json"] = dict(_VALID_STARTUP)
    arts["startup_profile.json"]["company_name"] = "<script>alert(1)</script>"
    d = _make_artifact_dir(arts)
    rc, stdout, stderr = _run_visualize(d)
    assert rc == 0, f"exit {rc}, stderr={stderr}"
    # Raw script tag must NOT appear
    assert "<script>alert(1)</script>" not in stdout
    # Escaped version should be present
    assert "&lt;script&gt;" in stdout


_XSS = "<script>alert(1)</script> & deal_flow"


def test_xss_safety_text_in_the_fund_and_the_verdicts() -> None:
    """Every string the page builds itself (outside the shared components' own escaping) is put through the
    founder-text policy and then escaped: the fund's name, a thesis area, a focus area, the check size's
    currency, the committee's verdict and a partner's verdict. The `&` beside a snake_case token shows the
    order: the token is still reworded, and the `&` arrives escaped once."""
    arts = _all_required_artifacts()
    fund = json.loads(json.dumps(_VALID_FUND))
    fund["fund_name"] = _XSS
    fund["thesis_areas"] = [_XSS]
    fund["archetypes"][0]["focus_areas"] = [_XSS]
    fund["check_size_range"]["currency"] = _XSS
    arts["fund_profile.json"] = fund
    score = json.loads(json.dumps(_VALID_SCORE))
    score["summary"]["verdict"] = _XSS
    arts["score_dimensions.json"] = score
    disc = json.loads(json.dumps(_VALID_DISCUSSION))
    disc["partner_verdicts"][0]["verdict"] = _XSS
    arts["discussion.json"] = disc
    d = _make_artifact_dir(arts)
    rc, stdout, stderr = _run_visualize(d)
    assert rc == 0, f"exit {rc}, stderr={stderr}"
    assert "<script>alert(1)</script>" not in stdout
    escaped = "&lt;script&gt;alert(1)&lt;/script&gt; &amp; deal flow"
    assert stdout.count(escaped) >= 6, stdout.count(escaped)
    assert "&amp;amp;" not in stdout and "deal_flow" not in stdout
    fund_section = by_id(parse(stdout), "fund")
    assert fund_section is not None and fund_section.text().count("<script>alert(1)</script> & deal flow") >= 4


def test_the_fund_panel_reads_only_the_role_and_its_focus_areas() -> None:
    """Partners are role names only. A generic profile's archetype may carry an old invented `background` (the
    one exemption the people rule allows); it never reaches the page. An archetype may carry a `name` equal to
    its role's label; the panel's partner labels are the role labels, read from the role."""
    arts = _all_required_artifacts()
    fund = json.loads(json.dumps(_VALID_FUND))
    labels = {"visionary": "The Visionary", "operator": "The Operator", "analyst": "The Analyst"}
    for arch in fund["archetypes"]:
        arch["background"] = "Distinctive invented background marker"
        arch["name"] = labels[arch["role"]]
    arts["fund_profile.json"] = fund
    d = _make_artifact_dir(arts)
    rc, stdout, stderr = _run_visualize(d)
    assert rc == 0, f"exit {rc}, stderr={stderr}"
    assert "Distinctive invented background marker" not in stdout
    fund_section = by_id(parse(stdout), "fund")
    assert fund_section is not None
    rows = [e for e in fund_section.iter() if e.tag == "tr"]
    partner_rows = [r for r in rows if [c.tag for c in r.children if isinstance(c, Element)] == ["td", "td"]]
    got = [[c.text() for c in r.children if isinstance(c, Element)] for r in partner_rows]
    assert got == [["The Visionary", "market"], ["The Operator", "execution"], ["The Analyst", "numbers"]]


def test_a_profile_that_names_a_person_is_refused_before_the_page_is_written() -> None:
    arts = _all_required_artifacts()
    fund = json.loads(json.dumps(_VALID_FUND))
    fund["archetypes"][0]["name"] = "Invented Person"
    arts["fund_profile.json"] = fund
    d = _make_artifact_dir(arts)
    out = os.path.join(d, "report.html")
    rc, stdout, _stderr = _run_visualize(d, extra_args=["-o", out])
    assert rc != 0
    assert "FUND_PROFILE_NAMES_PEOPLE" in stdout
    assert "Invented Person" not in stdout
    assert not os.path.exists(out)


def test_xss_safety_attribute() -> None:
    """Partner rationale with attribute injection -> properly escaped."""
    arts = _all_required_artifacts()
    arts["discussion.json"] = dict(_VALID_DISCUSSION)
    arts["discussion.json"]["partner_verdicts"] = [
        {
            "partner": "visionary",
            "verdict": "invest",
            "rationale": '"foo" onload="alert(1)"',
        },
        {
            "partner": "operator",
            "verdict": "more_diligence",
            "rationale": "Normal text",
        },
        {
            "partner": "analyst",
            "verdict": "pass",
            "rationale": "Normal text",
        },
    ]
    d = _make_artifact_dir(arts)
    rc, stdout, stderr = _run_visualize(d)
    assert rc == 0, f"exit {rc}, stderr={stderr}"
    # The raw dangerous attribute must not appear
    assert 'onload="alert(1)"' not in stdout
    # Escaped quotes should appear
    assert "&quot;foo&quot;" in stdout


def test_deterministic_output() -> None:
    """Run twice -> identical HTML bytes."""
    d = _make_artifact_dir(_all_required_artifacts())
    rc1, out1, _ = _run_visualize(d)
    rc2, out2, _ = _run_visualize(d)
    assert rc1 == 0
    assert rc2 == 0
    assert out1 == out2, "Output differs between runs"


def test_html_structural_sanity() -> None:
    """DOCTYPE present, balanced SVG tags, no script tags."""
    d = _make_artifact_dir(_all_required_artifacts())
    rc, stdout, _ = _run_visualize(d)
    assert rc == 0
    assert stdout.strip().startswith("<!DOCTYPE html>")

    # Balanced SVG tags
    open_count = len(re.findall(r"<svg[\s>]", stdout))
    close_count = stdout.count("</svg>")
    assert open_count == close_count, f"Unbalanced SVG tags: {open_count} opens vs {close_count} closes"

    # Inline JS is allowed; verify script tags are balanced
    script_count = stdout.lower().count("<script")
    script_close = stdout.lower().count("</script>")
    assert script_count == script_close, "Unbalanced script tags"


def test_dealbreaker_verdict() -> None:
    """A hard-pass render rings as a fail and its verdict reads "Decline — Hard Pass"."""
    arts = _all_required_artifacts()
    score = dict(_VALID_SCORE)
    items = list(_VALID_SCORE["items"])
    # Replace first item with a dealbreaker
    items[0] = dict(items[0])
    items[0]["status"] = "dealbreaker"
    score["items"] = items

    summary = dict(_VALID_SCORE["summary"])
    summary["verdict"] = "hard_pass"
    summary["conviction_score"] = 96.4
    summary["dealbreaker"] = 1
    summary["strong_conviction"] = 27
    summary["dealbreakers"] = [
        {
            "id": _DIMENSION_IDS[0],
            "category": "Team",
            "label": "Test",
            "evidence": "test",
            "notes": "fatal",
        },
    ]
    score["summary"] = summary
    arts["score_dimensions.json"] = score

    d = _make_artifact_dir(arts)
    rc, stdout, stderr = _run_visualize(d)
    assert rc == 0, f"exit {rc}, stderr={stderr}"
    doc = parse(stdout)
    assert _ring_tone(doc) == "fail"
    assert _verdict(doc).startswith("Decline — Hard Pass")
    assert "Decline — Hard Pass" in (_ring(doc).get("aria-label") or "")


def test_gauge_pass_verdict_says_decline_not_bare_pass() -> None:
    """The ring, the hero verdict and the partner pills never render a bare 'Pass' for a 'pass' verdict —
    it reads as 'passes the bar' to a founder skimming the report. They say "Decline"."""
    arts = _all_required_artifacts()
    score = json.loads(json.dumps(_VALID_SCORE))
    score["summary"]["verdict"] = "pass"
    score["summary"]["conviction_score"] = 30.0
    arts["score_dimensions.json"] = score
    disc = json.loads(json.dumps(_VALID_DISCUSSION))
    disc["partner_verdicts"][2]["verdict"] = "pass"
    arts["discussion.json"] = disc
    d = _make_artifact_dir(arts)
    rc, stdout, stderr = _run_visualize(d)
    assert rc == 0, f"exit {rc}, stderr={stderr}"
    doc = parse(stdout)
    assert (_ring(doc).get("aria-label") or "").endswith(", Decline")
    assert _verdict(doc).startswith("Decline")
    pills = [e.text() for e in by_attr(doc, "data-partner") if e.tag == "span"]
    assert "Analyst: Decline" in pills
    # No bare "Pass" text node (Hard Pass is fine, a bare Pass is not).
    assert re.search(r"(?<!Hard )>Pass<", stdout) is None, stdout
    assert not re.search(r"\bpass\b", " ".join(pills + [_verdict(doc)]), re.I)


def test_partner_card_pass_verdict_says_decline() -> None:
    """A partner-level 'pass' verdict on the partner-card chart must also
    render an unambiguous decline word, not a bare 'Pass'."""
    arts = _all_required_artifacts()
    disc = dict(arts["discussion.json"])
    disc["partner_verdicts"] = [
        {"partner": "visionary", "verdict": "invest", "rationale": "Great"},
        {"partner": "operator", "verdict": "more_diligence", "rationale": "Ok"},
        {"partner": "analyst", "verdict": "pass", "rationale": "Weak"},
    ]
    arts["discussion.json"] = disc
    d = _make_artifact_dir(arts)
    rc, stdout, stderr = _run_visualize(d)
    assert rc == 0, f"exit {rc}, stderr={stderr}"
    assert "Decline" in stdout
    assert re.search(r"(?<!Hard )>Pass<", stdout) is None, stdout


def test_summary_bar_pass_verdict_says_decline() -> None:
    """The header's partners row names a 'pass' partner verdict "Decline", as report.md's Partner Split does."""
    arts = _all_required_artifacts()
    disc = dict(arts["discussion.json"])
    disc["partner_verdicts"] = [
        {"partner": "visionary", "verdict": "invest", "rationale": "Great"},
        {"partner": "operator", "verdict": "more_diligence", "rationale": "Ok"},
        {"partner": "analyst", "verdict": "pass", "rationale": "Weak"},
    ]
    arts["discussion.json"] = disc
    d = _make_artifact_dir(arts)
    rc, stdout, stderr = _run_visualize(d)
    assert rc == 0, f"exit {rc}, stderr={stderr}"
    (row,) = by_attr(parse(stdout), "data-partners")
    assert "Analyst: Decline" in row.text()


def test_malformed_list_elements() -> None:
    """Non-dict items in partner_verdicts and conflicts don't crash."""
    arts = dict(_all_required_artifacts())
    # Inject non-dict elements into partner_verdicts
    disc = dict(arts["discussion.json"])
    disc["partner_verdicts"] = [
        "bad_string",
        {"partner": "visionary", "verdict": "invest", "rationale": "Great team"},
        42,
    ]
    arts["discussion.json"] = disc
    # Inject non-dict elements into conflicts
    conflict = dict(arts["conflict_check.json"])
    conflict["conflicts"] = [
        "not_a_dict",
        {"company": "SomeComp", "type": "adjacent", "severity": "manageable"},
    ]
    arts["conflict_check.json"] = conflict
    d = _make_artifact_dir(arts)
    rc, stdout, stderr = _run_visualize(d)
    assert rc == 0, f"exit {rc}, stderr={stderr}"
    assert "<!DOCTYPE html>" in stdout


def test_partner_role_case_insensitive() -> None:
    """Partner verdicts with mixed-case roles still match canonical cards."""
    arts = dict(_all_required_artifacts())
    disc = dict(arts["discussion.json"])
    disc["partner_verdicts"] = [
        {"partner": "Visionary", "verdict": "invest", "rationale": "Great"},
        {"partner": " OPERATOR ", "verdict": "more_diligence", "rationale": "Ok"},
        {"partner": "Analyst", "verdict": "pass", "rationale": "Weak"},
    ]
    arts["discussion.json"] = disc
    d = _make_artifact_dir(arts)
    rc, stdout, stderr = _run_visualize(d)
    assert rc == 0, f"exit {rc}, stderr={stderr}"
    # All 3 canonical partners should have real verdicts (not "No verdict")
    assert stdout.count("No verdict") == 0, "Mixed-case roles should match canonical partners"
    assert "Invest" in stdout
    assert "More Diligence" in stdout


def test_verdict_color_case_insensitive() -> None:
    """A capitalized verdict still gets its tone and its word, never the neutral fallback."""
    arts = _all_required_artifacts()
    disc = dict(arts["discussion.json"])
    disc["partner_verdicts"] = [
        {"partner": "visionary", "verdict": "Invest", "rationale": "Great"},
        {"partner": "operator", "verdict": "MORE_DILIGENCE", "rationale": "Ok"},
        {"partner": "analyst", "verdict": "Pass", "rationale": "Weak"},
    ]
    arts["discussion.json"] = disc
    score = json.loads(json.dumps(_VALID_SCORE))
    score["summary"]["verdict"] = "INVEST"
    arts["score_dimensions.json"] = score
    d = _make_artifact_dir(arts)
    rc, stdout, _stderr = _run_visualize(d)
    assert rc == 0
    doc = parse(stdout)
    assert _ring_tone(doc) == "pass"
    assert (_ring(doc).get("aria-label") or "").endswith(", Invest")
    pills = {e.get("data-partner"): e for e in by_attr(doc, "data-partner") if e.tag == "span"}
    assert pills["visionary"].text() == "Visionary: Invest" and _pill_tone(pills["visionary"]) == "pass"
    assert pills["operator"].text() == "Operator: More Diligence" and _pill_tone(pills["operator"]) == "warn"
    assert pills["analyst"].text() == "Analyst: Decline" and _pill_tone(pills["analyst"]) == "fail"


def test_severity_color_case_insensitive() -> None:
    """A capitalized severity like 'Blocking' still shows its word and its tone in the conflicts table."""
    arts = _all_required_artifacts()
    arts["conflict_check.json"] = {
        "conflicts": [
            {
                "company": "CompetitorCo",
                "type": "direct_competitor",
                "severity": "Blocking",
                "detail": "Same market",
            },
        ],
        "summary": {"overall_severity": "Blocking", "total": 1},
    }
    d = _make_artifact_dir(arts)
    rc, stdout, _stderr = _run_visualize(d)
    assert rc == 0
    section = by_id(parse(stdout), "conflicts")
    assert section is not None
    (sev,) = by_attr(section, "data-severity")
    assert sev.text() == "Blocking" and _pill_tone(sev) == "fail"
    assert "Overall severity: Blocking" in section.text()


def test_empty_partner_role_skipped() -> None:
    """Empty string partner role doesn't produce a blank card."""
    arts = _all_required_artifacts()
    disc = dict(arts["discussion.json"])
    disc["partner_verdicts"] = [
        {"partner": "", "verdict": "invest", "rationale": "Ghost"},
        {"partner": "visionary", "verdict": "invest", "rationale": "Great"},
    ]
    arts["discussion.json"] = disc
    d = _make_artifact_dir(arts)
    rc, stdout, _stderr = _run_visualize(d)
    assert rc == 0
    # The empty-role entry should not appear as a card
    assert "Ghost" not in stdout, "Empty partner role should be skipped"


# ---------------------------------------------------------------------------
# AI simulation disclaimer tests
# ---------------------------------------------------------------------------


def test_visualize_partner_disclaimer() -> None:
    """HTML contains 'AI-simulated' text in partner verdicts section."""
    d = _make_artifact_dir(_all_required_artifacts())
    rc, stdout, _stderr = _run_visualize(d)
    assert rc == 0
    assert "AI-simulated" in stdout


def test_dealbreaker_color_visible() -> None:
    """A dealbreaker dimension is a fail row that says "Dealbreaker" in words, not by colour alone."""
    arts = _all_required_artifacts()
    score = json.loads(json.dumps(_VALID_SCORE))
    score["items"][0]["status"] = "dealbreaker"
    score["items"][1]["status"] = "to_confirm"
    arts["score_dimensions.json"] = score
    d = _make_artifact_dir(arts)
    rc, stdout, stderr = _run_visualize(d)
    assert rc == 0, f"exit {rc}, stderr={stderr}"
    doc = parse(stdout)
    (row,) = by_attr(doc, "data-criterion", _DIMENSION_IDS[0])
    assert row.get("data-status") == "fail" and row.get("data-status-word") == "Dealbreaker"
    assert "Dealbreaker" in row.text()
    (tbc,) = by_attr(doc, "data-criterion", _DIMENSION_IDS[1])
    assert tbc.get("data-status") == "na" and tbc.get("data-status-word") == "To confirm"


def test_visualize_conviction_disclaimer() -> None:
    """HTML contains 'AI-generated assessment' below conviction gauge."""
    d = _make_artifact_dir(_all_required_artifacts())
    rc, stdout, _stderr = _run_visualize(d)
    assert rc == 0
    assert "AI-generated assessment" in stdout


def test_radar_zero_score_not_at_center() -> None:
    """Categories with 0% score should NOT collapse to exact center (minimum floor)."""
    arts = _all_required_artifacts()
    score = dict(_VALID_SCORE)
    summary = dict(score["summary"])
    # Team has 0 strong, 0 moderate -> 0% weighted score
    summary["by_category"] = {
        "Team": {"strong_conviction": 0, "moderate_conviction": 0, "concern": 3, "dealbreaker": 1, "not_applicable": 0},
        "Market": {
            "strong_conviction": 4,
            "moderate_conviction": 0,
            "concern": 0,
            "dealbreaker": 0,
            "not_applicable": 0,
        },
        "Product": {
            "strong_conviction": 4,
            "moderate_conviction": 0,
            "concern": 0,
            "dealbreaker": 0,
            "not_applicable": 0,
        },
        "Business Model": {
            "strong_conviction": 4,
            "moderate_conviction": 0,
            "concern": 0,
            "dealbreaker": 0,
            "not_applicable": 0,
        },
        "Financials": {
            "strong_conviction": 0,
            "moderate_conviction": 0,
            "concern": 4,
            "dealbreaker": 0,
            "not_applicable": 0,
        },
        "Risk": {"strong_conviction": 4, "moderate_conviction": 0, "concern": 0, "dealbreaker": 0, "not_applicable": 0},
        "Fund Fit": {
            "strong_conviction": 4,
            "moderate_conviction": 0,
            "concern": 0,
            "dealbreaker": 0,
            "not_applicable": 0,
        },
    }
    score["summary"] = summary
    arts["score_dimensions.json"] = score
    d = _make_artifact_dir(arts)
    rc, stdout, stderr = _run_visualize(d)
    assert rc == 0, f"exit {rc}, stderr={stderr}"
    # The data polygon has fill-opacity="0.2" — find it loosely
    polygon_match = re.search(
        r'<polygon points="([^"]+)"[^>]*fill-opacity="0\.2"', stdout[stdout.index('data-chart="radar"') :]
    )
    assert polygon_match, "Radar data polygon not found"
    points_str = polygon_match.group(1)
    # Derive center and radius from SVG so the test doesn't hardcode geometry.
    # Every spoke line originates from center (x1, y1) and ends at the rim (x2, y2).
    radar = stdout[stdout.index('data-chart="radar"') :]
    spoke = re.search(r'<line x1="([\d.]+)" y1="([\d.]+)" x2="([\d.]+)" y2="([\d.]+)"', radar)
    assert spoke, "No spoke line found in radar chart"
    cx, cy = float(spoke.group(1)), float(spoke.group(2))
    sx, sy = float(spoke.group(3)), float(spoke.group(4))
    max_r = ((sx - cx) ** 2 + (sy - cy) ** 2) ** 0.5
    # Allow 0.1px tolerance for :.2f coordinate rounding.
    min_dist = max_r * 0.05 - 0.1
    pairs = [p.strip() for p in points_str.split(" ") if "," in p]
    for pair in pairs:
        x, y = (float(v) for v in pair.split(","))
        dist = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5
        assert dist >= min_dist, f"Data point {pair} is {dist:.1f}px from center, need >= {min_dist:.1f}px (5% floor)"


def test_html_title_includes_company() -> None:
    """HTML <title> should include company name, not be generic."""
    d = _make_artifact_dir(_all_required_artifacts())
    rc, stdout, stderr = _run_visualize(d)
    assert rc == 0, f"exit {rc}, stderr={stderr}"
    assert "<title>IC Simulation: TestCo</title>" in stdout


def test_css_has_responsive_breakpoint() -> None:
    """The debate's three partner cards fall to one column on a phone."""
    d = _make_artifact_dir(_all_required_artifacts())
    rc, stdout, stderr = _run_visualize(d)
    assert rc == 0, f"exit {rc}, stderr={stderr}"
    m = re.search(r"@media \(max-width: (\d+)px\) \{ \.ic-debate \{ grid-template-columns: 1fr; \} \}", stdout)
    assert m, "the debate grid has no single-column rule for narrow screens"
    assert 390 <= int(m.group(1)) < 720
    assert re.search(r"\.ic-debate \{[^}]*grid-template-columns: repeat\(3,", stdout)


def test_svg_scales_on_mobile() -> None:
    """SVGs should have max-width:100% so they don't overflow containers."""
    d = _make_artifact_dir(_all_required_artifacts())
    rc, stdout, stderr = _run_visualize(d)
    assert rc == 0, f"exit {rc}, stderr={stderr}"
    assert "max-width: 100%" in stdout or "max-width:100%" in stdout


def test_rationale_is_shown_whole() -> None:
    """A partner's rationale is shown whole on the page, as report.md shows it."""
    arts = _all_required_artifacts()
    disc = dict(arts["discussion.json"])
    long_rationale = (
        "The market opportunity is genuinely massive with multiple secular tailwinds driving adoption. "
        "The founding team brings deep domain expertise from a decade at top-tier enterprise companies. "
        "However the unit economics are entirely unproven and require significant further validation."
    )
    assert len(long_rationale) > 250, f"Test rationale must exceed 250 chars, got {len(long_rationale)}"
    disc["partner_verdicts"] = [
        {"partner": "visionary", "verdict": "invest", "rationale": long_rationale},
        {"partner": "operator", "verdict": "more_diligence", "rationale": "Short."},
        {"partner": "analyst", "verdict": "pass", "rationale": "Short."},
    ]
    arts["discussion.json"] = disc
    d = _make_artifact_dir(arts)
    rc, stdout, stderr = _run_visualize(d)
    assert rc == 0, f"exit {rc}, stderr={stderr}"
    (card,) = [e for e in by_attr(parse(stdout), "data-partner", "visionary") if e.tag == "article"]
    assert long_rationale in card.text()


_LONG_TOKEN = ("https://example.invalid/" + "a" * 620)[:620]


def test_a_long_unbroken_token_cannot_widen_the_page() -> None:
    """Model-written text can carry one long unbroken token (a cited URL). It reaches the page whole, in the
    one-liner, a dimension's evidence, a rationale, a supplied fact and a finding, and the page's stylesheet
    breaks it rather than widening the page: the body wraps anywhere and the header's text column may shrink.
    Layout itself needs a browser (measured at a phone's width, with this fixture); what a test can see is
    that the token is in each container and the rules are on the page."""
    assert len(_LONG_TOKEN) == 620
    arts = _all_required_artifacts()
    startup = dict(_VALID_STARTUP, one_liner=_LONG_TOKEN)
    startup["host_context"] = {
        "provenance": "supplied_with_request",
        "sha256": "0" * 64,
        "items": [{"index": 1, "fact": _LONG_TOKEN, "source": "Invented note", "date": "2026-01-15"}],
        "dropped": [],
    }
    arts["startup_profile.json"] = startup
    score = json.loads(json.dumps(_VALID_SCORE))
    score["items"][0]["evidence"] = _LONG_TOKEN
    score["items"][1]["status"] = "some_new_status"
    arts["score_dimensions.json"] = score
    disc = json.loads(json.dumps(_VALID_DISCUSSION))
    disc["partner_verdicts"][0]["rationale"] = _LONG_TOKEN
    disc["diligence_requirements"] = [_LONG_TOKEN]
    arts["discussion.json"] = disc
    d = _make_artifact_dir(arts)
    rc, stdout, stderr = _run_visualize(d)
    assert rc == 0, f"exit {rc}, stderr={stderr}"
    doc = parse(stdout)
    (hero,) = [e for e in doc.iter() if e.tag == "header"]
    context = by_id(doc, "context")
    (evidence_row,) = by_attr(doc, "data-criterion", _DIMENSION_IDS[0])
    (card,) = [e for e in by_attr(doc, "data-partner", "visionary") if e.tag == "article"]
    (actions,) = by_attr(doc, "data-findings", "actions")
    for name, el in (
        ("hero", hero),
        ("context", context),
        ("evidence", evidence_row),
        ("rationale", card),
        ("finding", actions),
    ):
        assert el is not None and _LONG_TOKEN in el.text(), name
    css = " ".join(e.text() for e in doc.iter() if e.tag == "style")
    assert re.search(r"body\.ui-body \{[^}]*overflow-wrap: anywhere", css)
    assert re.search(r"\.ui-hero__text \{[^}]*min-width: 0", css)
    # An unknown status is not scored, in the closed set's word, never the model's text.
    (unknown,) = by_attr(doc, "data-criterion", _DIMENSION_IDS[1])
    assert unknown.get("data-status") == "na" and unknown.get("data-status-word") == "Not scored"
    assert "some_new_status" not in stdout and "Some new status" not in stdout


def test_summary_bar_present() -> None:
    """The header carries the one-liner, the sector and every partner's verdict; the Dimensions chips carry
    each status's count."""
    d = _make_artifact_dir(_all_required_artifacts())
    rc, stdout, stderr = _run_visualize(d)
    assert rc == 0, f"exit {rc}, stderr={stderr}"
    doc = parse(stdout)
    (hero,) = [e for e in doc.iter() if e.tag == "header"]
    assert _VALID_STARTUP["one_liner"] in hero.text(), "One-liner should appear in the header"
    assert _VALID_STARTUP["sector"] in hero.text(), "Sector should appear in the header"
    chips = {e.get("for"): e.text() for e in doc.iter() if e.tag == "label" and e.has("for")}
    summary = _VALID_SCORE["summary"]
    assert chips["ck-f-pass"] == f"Strong {summary['strong_conviction']}"
    assert chips["ck-f-neutral"] == f"Moderate {summary['moderate_conviction']}"
    assert chips["ck-f-warn"] == f"Concern {summary['concern']}"
    assert chips["ck-f-fail"] == f"Dealbreaker {summary['dealbreaker']}"
    (row,) = by_attr(doc, "data-partners")
    for want in ("Visionary: Invest", "Operator: More Diligence", "Analyst: More Diligence"):
        assert want in row.text(), want


def test_radar_outer_labels_show_scores() -> None:
    """Outer category labels should include percentage scores beneath category names."""
    arts = _all_required_artifacts()
    score = dict(_VALID_SCORE)
    summary = dict(score["summary"])
    summary["by_category"] = {
        "Team": {"strong_conviction": 1, "moderate_conviction": 1, "concern": 2, "dealbreaker": 0, "not_applicable": 0},
        "Market": {
            "strong_conviction": 4,
            "moderate_conviction": 0,
            "concern": 0,
            "dealbreaker": 0,
            "not_applicable": 0,
        },
        "Product": {
            "strong_conviction": 4,
            "moderate_conviction": 0,
            "concern": 0,
            "dealbreaker": 0,
            "not_applicable": 0,
        },
        "Business Model": {
            "strong_conviction": 4,
            "moderate_conviction": 0,
            "concern": 0,
            "dealbreaker": 0,
            "not_applicable": 0,
        },
        "Financials": {
            "strong_conviction": 4,
            "moderate_conviction": 0,
            "concern": 0,
            "dealbreaker": 0,
            "not_applicable": 0,
        },
        "Risk": {"strong_conviction": 4, "moderate_conviction": 0, "concern": 0, "dealbreaker": 0, "not_applicable": 0},
        "Fund Fit": {
            "strong_conviction": 4,
            "moderate_conviction": 0,
            "concern": 0,
            "dealbreaker": 0,
            "not_applicable": 0,
        },
    }
    # Team: (1*1.0 + 1*0.5) / 4 * 100 = 37.5% -> renders as "38%" (rounded)
    score["summary"] = summary
    arts["score_dimensions.json"] = score
    d = _make_artifact_dir(arts)
    rc, stdout, stderr = _run_visualize(d)
    assert rc == 0, f"exit {rc}, stderr={stderr}"
    assert "38%" in stdout, "Team's 37.5% rounded to 38% should appear as outer label"
    assert "Team" in stdout, "Category name should appear as outer label"


def test_key_findings_distinguishes_mixed_strong_from_all_strong() -> None:
    """A category with strong AND moderate convictions (no concerns) must read
    'leans strong with no concerns', not the inaccurate 'scores all strong
    conviction' (which is reserved for categories that are purely strong)."""
    arts = _all_required_artifacts()
    score = dict(_VALID_SCORE)
    summary = dict(score["summary"])
    summary["by_category"] = {
        # mixed positive: strong present, moderate present, no concerns
        "Team": {"strong_conviction": 2, "moderate_conviction": 2, "concern": 0, "dealbreaker": 0, "not_applicable": 0},
        # purely strong
        "Market": {
            "strong_conviction": 4,
            "moderate_conviction": 0,
            "concern": 0,
            "dealbreaker": 0,
            "not_applicable": 0,
        },
        "Product": {
            "strong_conviction": 4,
            "moderate_conviction": 0,
            "concern": 0,
            "dealbreaker": 0,
            "not_applicable": 0,
        },
        "Business Model": {
            "strong_conviction": 4,
            "moderate_conviction": 0,
            "concern": 0,
            "dealbreaker": 0,
            "not_applicable": 0,
        },
        "Financials": {
            "strong_conviction": 4,
            "moderate_conviction": 0,
            "concern": 0,
            "dealbreaker": 0,
            "not_applicable": 0,
        },
        "Risk": {"strong_conviction": 4, "moderate_conviction": 0, "concern": 0, "dealbreaker": 0, "not_applicable": 0},
        "Fund Fit": {
            "strong_conviction": 4,
            "moderate_conviction": 0,
            "concern": 0,
            "dealbreaker": 0,
            "not_applicable": 0,
        },
    }
    score["summary"] = summary
    arts["score_dimensions.json"] = score
    d = _make_artifact_dir(arts)
    rc, stdout, stderr = _run_visualize(d)
    assert rc == 0, f"exit {rc}, stderr={stderr}"
    assert "Team leans strong with no concerns" in stdout
    assert "Team scores all strong conviction" not in stdout
    # a purely-strong category still uses the original phrasing
    assert "Market scores all strong conviction" in stdout


# ---------------------------------------------------------------------------
# Honesty-guard parity tests: mirror compose_report.py's conviction_basis /
# coverage_* / debated_dealbreakers handling into the HTML report.
# ---------------------------------------------------------------------------


def test_gauge_shows_coverage_denominator_when_basis_insufficient() -> None:
    """conviction_basis.sufficient=False puts the 'X of Y' denominator in the header, under the verdict."""
    arts = _all_required_artifacts()
    score = json.loads(json.dumps(_VALID_SCORE))
    summary = score["summary"]
    summary["applicable"] = 2
    summary["conviction_score"] = 50.0
    summary["verdict"] = "more_diligence"
    summary["conviction_basis"] = {"applicable": 2, "total": 28, "sufficient": False}
    arts["score_dimensions.json"] = score
    d = _make_artifact_dir(arts)
    rc, stdout, stderr = _run_visualize(d)
    assert rc == 0, f"exit {rc}, stderr={stderr}"
    (note,) = by_attr(parse(stdout), "data-note", "basis")
    assert note.text().startswith("Scored on 2 of 28")


def test_gauge_omits_coverage_denominator_when_basis_sufficient() -> None:
    """A fully-scored run (sufficient=True) must NOT show the denominator
    caveat — it's reserved for the thin-base case."""
    d = _make_artifact_dir(_all_required_artifacts())
    rc, stdout, stderr = _run_visualize(d)
    assert rc == 0, f"exit {rc}, stderr={stderr}"
    assert "Scored on" not in stdout
    assert not by_attr(parse(stdout), "data-note", "basis")


def test_verdict_label_distinguishes_coverage_floored_held_from_capped_and_merits() -> None:
    """coverage_floored/coverage_held share one label; coverage_capped gets a
    different one; and the plain-merits more_diligence default is different
    from both. Three renders, three distinct labels — not three copies of a
    bare 'More Diligence'."""
    base_score = json.loads(json.dumps(_VALID_SCORE))
    base_score["summary"]["verdict"] = "more_diligence"
    base_score["summary"]["conviction_score"] = 60.0

    def _label_for(coverage_flags: dict[str, bool]) -> str:
        score = json.loads(json.dumps(base_score))
        score["summary"].update({"coverage_capped": False, "coverage_floored": False, "coverage_held": False})
        score["summary"].update(coverage_flags)
        arts = _all_required_artifacts()
        arts["score_dimensions.json"] = score
        d = _make_artifact_dir(arts)
        rc, stdout, stderr = _run_visualize(d)
        assert rc == 0, f"exit {rc}, stderr={stderr}"
        return _verdict(parse(stdout))

    merits_label = _label_for({})
    floored_label = _label_for({"coverage_floored": True})
    held_label = _label_for({"coverage_held": True})
    capped_label = _label_for({"coverage_capped": True})

    assert floored_label == held_label, (
        f"coverage_floored and coverage_held must share one label, got {floored_label!r} vs {held_label!r}"
    )
    assert capped_label != floored_label, "coverage_capped must have its own distinct label"
    assert merits_label != floored_label, "the plain-merits default must differ from the coverage labels"
    assert merits_label != capped_label, "the plain-merits default must differ from the coverage labels"
    assert merits_label == "More Diligence — promising but needs more evidence", merits_label


def test_dealbreaker_provenance_distinguishes_debated_from_scoring_only() -> None:
    """A dealbreaker two partners argued in the debate must render different
    provenance text from one the scoring pass produced alone — presenting
    them identically overstates the evidentiary weight of the latter."""
    arts = _all_required_artifacts()
    score = json.loads(json.dumps(_VALID_SCORE))
    score["summary"]["dealbreaker"] = 2
    score["summary"]["strong_conviction"] = 26
    score["summary"]["verdict"] = "hard_pass"
    score["summary"]["dealbreakers"] = [
        {
            "id": _DIMENSION_IDS[0],
            "category": "Team",
            "label": "Debated Flaw",
            "evidence": "test",
        },
        {
            "id": _DIMENSION_IDS[1],
            "category": "Team",
            "label": "Scoring-Only Flaw",
            "evidence": "test",
        },
    ]
    arts["score_dimensions.json"] = score

    disc = dict(_VALID_DISCUSSION)
    disc["debated_dealbreakers"] = [
        {"dimension": _DIMENSION_IDS[0], "raised_by": ["visionary", "operator"]},
    ]
    arts["discussion.json"] = disc

    d = _make_artifact_dir(arts)
    rc, stdout, stderr = _run_visualize(d)
    assert rc == 0, f"exit {rc}, stderr={stderr}"
    assert "Dealbreaker in Team: Debated Flaw (raised in debate by Visionary, Operator)" in stdout
    assert "Dealbreaker in Team: Scoring-Only Flaw (scoring pass only — not raised in debate)" in stdout


def test_dealbreaker_provenance_unavailable_when_no_id_level_channel() -> None:
    """discussion.json with no 'debated_dealbreakers' list at all must render
    as provenance-unavailable, not silently as 'scoring pass only' (which
    would imply the debate WAS checked and found nothing)."""
    arts = _all_required_artifacts()
    score = json.loads(json.dumps(_VALID_SCORE))
    score["summary"]["dealbreaker"] = 1
    score["summary"]["strong_conviction"] = 27
    score["summary"]["verdict"] = "hard_pass"
    score["summary"]["dealbreakers"] = [
        {"id": _DIMENSION_IDS[0], "category": "Team", "label": "Some Flaw", "evidence": "test"},
    ]
    arts["score_dimensions.json"] = score

    disc = dict(_VALID_DISCUSSION)
    disc.pop("debated_dealbreakers", None)
    arts["discussion.json"] = disc

    d = _make_artifact_dir(arts)
    rc, stdout, stderr = _run_visualize(d)
    assert rc == 0, f"exit {rc}, stderr={stderr}"
    assert "Dealbreaker in Team: Some Flaw (debate provenance unavailable)" in stdout


# ===========================================================================
# Key-coverage tests: producer output keys ⊆ renderer known sets
# ===========================================================================
#
# Invariant: when score_dimensions.py / detect_conflicts.py adds a new
# status, verdict, or severity value, the corresponding visualize.py color
# map must be updated. These tests pin the current complete sets so any new
# emitted key causes a loud failure with the offending name listed.
# ===========================================================================

_IC_SIM_VISUALIZE_SCRIPT = os.path.join(IC_SIM_DIR, "visualize.py")
_IC_SIM_SCORE_DIMENSIONS_SCRIPT = os.path.join(IC_SIM_DIR, "score_dimensions.py")
_IC_SIM_DETECT_CONFLICTS_SCRIPT = os.path.join(IC_SIM_DIR, "detect_conflicts.py")


def _load_ic_sim_visualize() -> types.ModuleType:
    """Import ic-sim visualize.py with a unique sys.modules key.

    _theme is imported lazily inside a render function, so no stub is needed
    at module load time.
    """
    key = "_ic_sim_keycov_visualize"
    if key in sys.modules:
        return sys.modules[key]  # type: ignore[return-value]
    spec = importlib.util.spec_from_file_location(key, _IC_SIM_VISUALIZE_SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = types.ModuleType(key)
    mod.__spec__ = spec  # type: ignore[assignment]
    mod.__file__ = _IC_SIM_VISUALIZE_SCRIPT  # type: ignore[assignment]
    sys.modules[key] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _load_ic_sim_score_dimensions() -> types.ModuleType:
    """Import ic-sim score_dimensions.py with a unique sys.modules key."""
    key = "_ic_sim_keycov_score_dimensions"
    if key in sys.modules:
        return sys.modules[key]  # type: ignore[return-value]
    spec = importlib.util.spec_from_file_location(key, _IC_SIM_SCORE_DIMENSIONS_SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = types.ModuleType(key)
    mod.__spec__ = spec  # type: ignore[assignment]
    mod.__file__ = _IC_SIM_SCORE_DIMENSIONS_SCRIPT  # type: ignore[assignment]
    sys.modules[key] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _load_ic_sim_detect_conflicts() -> types.ModuleType:
    """Import ic-sim detect_conflicts.py with a unique sys.modules key."""
    key = "_ic_sim_keycov_detect_conflicts"
    if key in sys.modules:
        return sys.modules[key]  # type: ignore[return-value]
    spec = importlib.util.spec_from_file_location(key, _IC_SIM_DETECT_CONFLICTS_SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = types.ModuleType(key)
    mod.__spec__ = spec  # type: ignore[assignment]
    mod.__file__ = _IC_SIM_DETECT_CONFLICTS_SCRIPT  # type: ignore[assignment]
    sys.modules[key] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


# ---------------------------------------------------------------------------
# Test A: dimension statuses → a checklist tone and a word
# ---------------------------------------------------------------------------


class TestIcSimDimensionStatusColorCoverage:
    """Every dimension status that score_dimensions.py can emit has a checklist tone and a word on the page,
    so no row renders under the fallback. Produced set is derived live from score_dimensions.VALID_STATUSES."""

    def test_all_dimension_statuses_have_a_tone_and_a_word(self) -> None:
        produced = _load_ic_sim_score_dimensions().VALID_STATUSES
        viz = _load_ic_sim_visualize()
        missing = (produced - set(viz._STATUS_TONE)) | (produced - set(viz._STATUS_WORD))
        assert not missing, f"visualize has no tone or word for dimension status(es): {sorted(missing)}"
        assert set(viz._STATUS_TONE.values()) <= set(viz._CHECKLIST_STATUSES)

    def test_producer_dimension_statuses_min_count(self) -> None:
        """Guard against vacuous tests: VALID_STATUSES must have at least 5 statuses."""
        produced = _load_ic_sim_score_dimensions().VALID_STATUSES
        assert len(produced) >= 5, (
            f"VALID_STATUSES expected >= 5 entries, got {len(produced)}. Check score_dimensions.VALID_STATUSES."
        )

    def test_the_words_tell_apart_statuses_that_share_a_tone(self) -> None:
        viz = _load_ic_sim_visualize()
        words = list(viz._STATUS_WORD.values())
        assert len(set(words)) == len(words)


# ---------------------------------------------------------------------------
# Test B: verdict values → a decision word and a tone
# ---------------------------------------------------------------------------


class TestIcSimPartnerVerdictColorCoverage:
    """Every verdict value that score_dimensions.py's summary can emit has a decision word
    (`_ic_view.VERDICT_WORD`), a ring tone and a partner-pill tone, so nothing renders under the fallback.

    The 4 verdicts come from _summarize() branches in score_dimensions.py — there is no exported constant,
    so they are pinned here. A source-grep guard ensures each literal is still present in the source.
    """

    PRODUCER_VERDICTS: set[str] = {
        "invest",
        "more_diligence",
        "pass",
        "hard_pass",
    }

    def test_verdict_literals_present_in_source(self) -> None:
        """Each hardcoded verdict must appear as a string literal in score_dimensions.py."""
        with open(_IC_SIM_SCORE_DIMENSIONS_SCRIPT, encoding="utf-8") as fh:
            src = fh.read()
        for verdict in self.PRODUCER_VERDICTS:
            assert f'"{verdict}"' in src or f"'{verdict}'" in src, (
                f"Verdict string {verdict!r} not found as a literal in score_dimensions.py. "
                f"Update PRODUCER_VERDICTS if _summarize() was changed."
            )

    def test_every_verdict_has_a_word_a_ring_tone_and_a_pill_tone(self) -> None:
        viz = _load_ic_sim_visualize()
        view = viz._ic_view
        for verdict in self.PRODUCER_VERDICTS:
            assert verdict in view.VERDICT_WORD, verdict
            assert verdict in viz._VERDICT_TONE, verdict
            assert view.ring_tone({"verdict": verdict}) != "neutral", verdict

    def test_producer_verdicts_min_count(self) -> None:
        """Guard against vacuous tests: producer set must have exactly 4 verdicts."""
        assert len(self.PRODUCER_VERDICTS) == 4, (
            f"PRODUCER_VERDICTS expected 4 entries, got {len(self.PRODUCER_VERDICTS)}."
        )

    def test_verdict_words_pairwise_distinct(self) -> None:
        """Each verdict's word differs from every other's. The tones cannot: pass and hard_pass are both a
        decline, so the word is what tells the two most severe outcomes apart."""
        view = _load_ic_sim_visualize()._ic_view
        words = {v: view.VERDICT_WORD[v] for v in self.PRODUCER_VERDICTS}
        assert len(set(words.values())) == len(words), words


# ---------------------------------------------------------------------------
# Test C: conflict severity values → a word and a tone
# ---------------------------------------------------------------------------


class TestIcSimConflictSeverityColorCoverage:
    """Every conflict severity value that detect_conflicts.py can emit has a word and a tone in the conflicts
    table. VALID_SEVERITIES ({"blocking", "manageable"}) is loaded live; "clear" is computed in
    overall_severity when no conflicts exist and is pinned here with a source-grep guard.
    """

    _HARDCODED_EXTRA: set[str] = {"clear"}

    def _producer_severities(self) -> set[str]:
        """VALID_SEVERITIES union hardcoded extras."""
        return set[str](_load_ic_sim_detect_conflicts().VALID_SEVERITIES) | self._HARDCODED_EXTRA

    def test_clear_literal_present_in_source(self) -> None:
        """'clear' must appear as a string literal in detect_conflicts.py source."""
        with open(_IC_SIM_DETECT_CONFLICTS_SCRIPT, encoding="utf-8") as fh:
            src = fh.read()
        assert '"clear"' in src or "'clear'" in src, (
            "'clear' not found as a literal in detect_conflicts.py. "
            "Update _HARDCODED_EXTRA if the severity was renamed."
        )

    def test_all_severities_have_a_word_and_a_tone(self) -> None:
        produced = self._producer_severities()
        viz = _load_ic_sim_visualize()
        missing = (produced - set(viz._SEVERITY_WORD)) | (produced - set(viz._SEVERITY_TONE))
        assert not missing, f"visualize has no word or tone for severity value(s): {sorted(missing)}"

    def test_producer_severities_min_count(self) -> None:
        """Guard against vacuous tests: produced set must have at least 3 severities."""
        produced = self._producer_severities()
        assert len(produced) >= 3, f"VALID_SEVERITIES + extras expected >= 3 entries, got {len(produced)}."

    def test_each_severity_is_shown_in_words_on_the_page(self) -> None:
        arts = _all_required_artifacts()
        produced = sorted(self._producer_severities())
        arts["conflict_check.json"] = {
            "conflicts": [{"company": f"Co{i}", "type": "adjacent", "severity": sev} for i, sev in enumerate(produced)],
            "summary": {"overall_severity": "blocking", "conflict_count": len(produced)},
        }
        d = _make_artifact_dir(arts)
        rc, stdout, _stderr = _run_visualize(d)
        assert rc == 0
        section = by_id(parse(stdout), "conflicts")
        assert section is not None
        viz = _load_ic_sim_visualize()
        assert [e.text() for e in by_attr(section, "data-severity")] == [viz._SEVERITY_WORD[s] for s in produced]


# ---------------------------------------------------------------------------
# Test D: score_dimensions categories → visualize._CANONICAL_CATEGORIES coverage
# ---------------------------------------------------------------------------


class TestIcSimCategoryCoverage:
    """Every category name that score_dimensions.py can emit must appear in
    visualize.py's _CANONICAL_CATEGORIES so radar and bar charts include all
    spokes/bars in the correct order.

    Produced set is derived live from score_dimensions.DIMENSION_ITEMS.
    """

    @staticmethod
    def _producer_categories() -> set[str]:
        """Derive emittable category names live from DIMENSION_ITEMS."""
        sd = _load_ic_sim_score_dimensions()
        return {item["category"] for item in sd.DIMENSION_ITEMS}

    def test_all_producer_categories_in_canonical_list(self) -> None:
        """Every category the score producer emits must appear in _CANONICAL_CATEGORIES."""
        produced = self._producer_categories()
        viz = _load_ic_sim_visualize()
        canonical: set[str] = set(viz._CANONICAL_CATEGORIES)

        missing = produced - canonical
        assert not missing, (
            f"visualize._CANONICAL_CATEGORIES is missing category(ies) "
            f"emitted by score_dimensions.py: {sorted(missing)}. "
            f"Add them to _CANONICAL_CATEGORIES in the correct order."
        )

    def test_producer_categories_min_count(self) -> None:
        """Guard against vacuous tests: produced set must have at least 7 categories."""
        produced = self._producer_categories()
        assert len(produced) >= 7, (
            f"DIMENSION_ITEMS expected >= 7 distinct categories, got {len(produced)}. "
            f"Check score_dimensions.DIMENSION_ITEMS."
        )

    def test_canonical_categories_min_count(self) -> None:
        """_CANONICAL_CATEGORIES must list at least the producer categories."""
        produced = self._producer_categories()
        viz = _load_ic_sim_visualize()
        assert len(viz._CANONICAL_CATEGORIES) >= len(produced), (
            f"visualize._CANONICAL_CATEGORIES has only {len(viz._CANONICAL_CATEGORIES)} entries; "
            f"expected >= {len(produced)}."
        )
