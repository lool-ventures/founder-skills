"""Regression tests for cap-table HTML visualization (visualize.py + explore.py).

Focus areas:
1. Design §10 security contract — every user-controlled string MUST be
   HTML-escaped, and explorer.html's inline JSON data block MUST escape `</`
   to prevent `</script>` breakout. These tests inject XSS payloads into
   fixture inputs/instruments and verify outputs are inert.
2. Renderer key-coverage — every key the ownership-aggregate producer can emit
   is either rendered (known to the renderer) or explicitly excluded.  A new
   key added to the producer without updating the renderer/exclusion list will
   cause the relevant test class to fail loudly.
"""

from __future__ import annotations

import copy
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any

import pytest

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPTS = os.path.join(_REPO, "founder-skills", "skills", "cap-table", "scripts")

sys.path.insert(0, SCRIPTS)
import cap_state as cap_state_mod  # type: ignore[import-not-found]  # noqa: E402
import priced_round as priced_round_mod  # type: ignore[import-not-found]  # noqa: E402


def _run(script_name: str, args: list[str]) -> tuple[int, str, str]:
    res = subprocess.run(
        [sys.executable, os.path.join(SCRIPTS, script_name), *args],
        capture_output=True,
        text=True,
    )
    return res.returncode, res.stdout, res.stderr


def _make_fixture_dir(tmp: str, *, company_name: str = "TestCo", safe_id: str = "safe_001") -> str:
    """Build a complete artifact set in tmp; return the dir path."""
    inputs: dict[str, Any] = {
        "company_name": company_name,
        "analysis_date": "2026-05-19",
        "mode": "standard",
        "founders": [
            {"name": "Alice", "founder_id": "alice", "common_shares": 5_000_000},
        ],
        "preferred_series": [],
        "option_pool": {
            "plan_type": "nso",
            "authorized": 1_000_000,
            "issued": 0,
            "unallocated": 1_000_000,
        },
        "common_batches": [],
        "metadata": {"run_id": "rid1"},
    }
    instruments: dict[str, Any] = {
        "safes": [
            {
                "id": safe_id,
                "investor_name": "Angel A",
                "purchase_amount": 250_000,
                "post_money_valuation_cap": 5_000_000,
                "discount_multiplier": None,
                "mfn_provision": None,
                "pro_rata_side_letter": None,
                "issuance_date": "2025-01-01",
                "form": "yc_postmoney_cap",
                "conversion_price_override": None,
                "source_document": None,
                "extraction_confidence": "high",
            }
        ],
        "notes": [],
        "warrants": [],
        "option_grants": [],
        "metadata": {"run_id": "rid1"},
    }
    cap_state = cap_state_mod.build_cap_state(inputs, instruments)
    cap_state["metadata"]["run_id"] = "rid1"
    scenarios: dict[str, Any] = {
        "scenarios": [
            {
                "scenario_id": "s1",
                "label": "Cap-implied baseline",
                "type": "safe_conversion",
                "parameters": {},
                "computed_outputs": {
                    "completeness": "structural_only",
                    "cap_implied_only": True,
                    "blockers": [],
                    "math_provenance": [],
                    "per_safe": {
                        safe_id: {
                            "branch": "cap_implied",
                            "cap_implied_ownership": 0.05,
                            "safe_price": 0.4545,
                            "cap_implied_shares": 550_000,
                        }
                    },
                },
            }
        ],
        "metadata": {"run_id": "rid1"},
    }
    rule_audit: dict[str, Any] = {
        "gating": {},
        "applied_rules": [],
        "counsel_review_items": [],
        "date_sensitive_watchlist": [],
        "metadata": {"run_id": "rid1"},
    }
    counsel_packet: dict[str, Any] = {
        "company_name": company_name,
        "engagement_summary": "Fixture.",
        "items": [],
        "metadata": {"run_id": "rid1"},
    }
    for name, data in [
        ("inputs.json", inputs),
        ("instruments.json", instruments),
        ("cap_state.json", cap_state),
        ("scenarios.json", scenarios),
        ("rule_audit.json", rule_audit),
        ("counsel_packet.json", counsel_packet),
    ]:
        with open(os.path.join(tmp, name), "w") as f:
            json.dump(data, f)
    return tmp


# ===========================================================================
# visualize.py — self-contained HTML
# ===========================================================================


class TestVisualizeBasic:
    def test_basic_output(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            _make_fixture_dir(d)
            html_out = os.path.join(d, "report.html")
            rc, stdout, stderr = _run("visualize.py", ["--dir", d, "-o", html_out])
            assert rc == 0, stderr
            assert os.path.exists(html_out)
            assert os.path.getsize(html_out) > 1000  # non-trivial

    def test_self_contained_no_external_urls(self) -> None:
        """Per design §10: report.html must be self-contained; no CDN / external URLs."""
        with tempfile.TemporaryDirectory() as d:
            _make_fixture_dir(d)
            html_out = os.path.join(d, "report.html")
            _run("visualize.py", ["--dir", d, "-o", html_out])
            with open(html_out) as f:
                html = f.read()
            # No external script / stylesheet sources
            assert "https://cdn." not in html
            assert "http://" not in html
            assert "<script src=" not in html
            assert '<link rel="stylesheet" href="http' not in html

    def test_includes_company_name(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            _make_fixture_dir(d, company_name="TestCo")
            html_out = os.path.join(d, "report.html")
            _run("visualize.py", ["--dir", d, "-o", html_out])
            with open(html_out) as f:
                html = f.read()
            assert "TestCo" in html

    def test_deterministic_output(self) -> None:
        """Same inputs produce identical HTML."""
        with tempfile.TemporaryDirectory() as d:
            _make_fixture_dir(d)
            out1 = os.path.join(d, "r1.html")
            out2 = os.path.join(d, "r2.html")
            _run("visualize.py", ["--dir", d, "-o", out1])
            _run("visualize.py", ["--dir", d, "-o", out2])
            with open(out1) as f:
                h1 = f.read()
            with open(out2) as f:
                h2 = f.read()
            assert h1 == h2


# ===========================================================================
# visualize.py — XSS safety (design §10 security contract)
# ===========================================================================


_XSS_PAYLOAD = '<script>alert("xss")</script>&"<>'


class TestVisualizeXSSSafety:
    def test_company_name_xss_escaped(self) -> None:
        """User-controlled company_name must be HTML-escaped."""
        with tempfile.TemporaryDirectory() as d:
            _make_fixture_dir(d, company_name=_XSS_PAYLOAD)
            html_out = os.path.join(d, "report.html")
            rc, _, stderr = _run("visualize.py", ["--dir", d, "-o", html_out])
            assert rc == 0, stderr
            with open(html_out) as f:
                html = f.read()
            # Raw <script>alert must not appear unescaped in body
            assert "<script>alert" not in html, "XSS payload not escaped!"
            # The escaped version IS present
            assert "&lt;script&gt;alert" in html

    def test_as_of_date_xss_escaped(self) -> None:
        """User-controlled cap_state.as_of_date appears in the page header
        and must be HTML-escaped."""
        with tempfile.TemporaryDirectory() as d:
            _make_fixture_dir(d)
            # Tamper with cap_state's as_of_date to contain an XSS payload
            cs_path = os.path.join(d, "cap_state.json")
            with open(cs_path) as f:
                cs = json.load(f)
            cs["as_of_date"] = '<script>alert("xss")</script>'
            with open(cs_path, "w") as f:
                json.dump(cs, f)
            html_out = os.path.join(d, "report.html")
            rc, _, stderr = _run("visualize.py", ["--dir", d, "-o", html_out])
            assert rc == 0, stderr
            with open(html_out) as f:
                html = f.read()
            # Tampered date must NOT appear raw
            assert '<script>alert("xss")</script>' not in html
            # Escaped form IS present
            assert "&lt;script&gt;alert" in html


# ===========================================================================
# explore.py — interactive HTML
# ===========================================================================


class TestExploreBasic:
    def test_basic_output(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            _make_fixture_dir(d)
            html_out = os.path.join(d, "explorer.html")
            rc, _, stderr = _run("explore.py", ["--dir", d, "-o", html_out])
            assert rc == 0, stderr
            assert os.path.exists(html_out)

    def test_includes_inline_data_block(self) -> None:
        """explore.py must inline JSON data in a <script> block (no external fetch)."""
        with tempfile.TemporaryDirectory() as d:
            _make_fixture_dir(d)
            html_out = os.path.join(d, "explorer.html")
            _run("explore.py", ["--dir", d, "-o", html_out])
            with open(html_out) as f:
                html = f.read()
            assert "const DATA =" in html
            assert "scenarios" in html  # data field

    def test_no_external_dependencies(self) -> None:
        """Per design §10: explorer.html is self-contained."""
        with tempfile.TemporaryDirectory() as d:
            _make_fixture_dir(d)
            html_out = os.path.join(d, "explorer.html")
            _run("explore.py", ["--dir", d, "-o", html_out])
            with open(html_out) as f:
                html = f.read()
            assert "https://cdn." not in html
            assert "<script src=" not in html


class TestExploreXSSSafety:
    def test_company_name_in_inline_json_escaped(self) -> None:
        """When user-controlled strings go into inline JSON, they must NOT
        contain raw `</script>` that breaks out of the script tag."""
        # Use a company name containing the literal </script> sequence
        with tempfile.TemporaryDirectory() as d:
            _make_fixture_dir(d, company_name="Co</script><script>alert(1)</script>")
            html_out = os.path.join(d, "explorer.html")
            rc, _, stderr = _run("explore.py", ["--dir", d, "-o", html_out])
            assert rc == 0, stderr
            with open(html_out) as f:
                html = f.read()
            # Per design §10: `</` is escaped to `<\/` in inline JSON
            # so </script> in user data becomes <\/script> and doesn't terminate the block
            # The data block must not contain literal </script> from user input
            inline_data_start = html.find("const DATA =")
            inline_data_end = html.find("};\n", inline_data_start)
            if inline_data_end == -1:
                inline_data_end = html.find("};", inline_data_start)
            inline_block = html[inline_data_start:inline_data_end]
            # Within the inline JSON block, </script> must NOT appear unescaped
            assert "</script>" not in inline_block, (
                "explore.py inline JSON allowed </script> breakout — "
                "per design §10, </ must be escaped to <\\/ in JSON data"
            )

    def test_company_name_in_html_body_escaped(self) -> None:
        """Company name in the HTML body (header) must be escaped."""
        with tempfile.TemporaryDirectory() as d:
            _make_fixture_dir(d, company_name=_XSS_PAYLOAD)
            html_out = os.path.join(d, "explorer.html")
            _run("explore.py", ["--dir", d, "-o", html_out])
            with open(html_out) as f:
                html = f.read()
            # The <h1> with company_name must have escaped content
            # Find the h1 tag and check
            assert "<h1>Cap Table Explorer — &lt;script&gt;" in html


# ===========================================================================
# Negative tests — missing / corrupt inputs
# ===========================================================================


class TestErrorPaths:
    def test_visualize_missing_artifact_raises(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            # Only inputs.json; missing everything else
            with open(os.path.join(d, "inputs.json"), "w") as f:
                json.dump({"company_name": "X", "metadata": {"run_id": "r"}}, f)
            rc, _, _ = _run("visualize.py", ["--dir", d, "-o", os.path.join(d, "out.html")])
            assert rc != 0  # FileNotFoundError or similar

    def test_explore_missing_artifact_raises(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "inputs.json"), "w") as f:
                json.dump({"company_name": "X", "metadata": {"run_id": "r"}}, f)
            rc, _, _ = _run("explore.py", ["--dir", d, "-o", os.path.join(d, "out.html")])
            assert rc != 0


# ===========================================================================
# Shared fixture — full-featured cap state that exercises every branch of
# aggregate_ownership_by_class (founders + preferred + pool + safe + note +
# new_money).  Anti-dilution keys are added separately in the AD-specific tests.
# ===========================================================================

_FULL_INPUTS: dict[str, Any] = {
    "company_name": "TestCo",
    "analysis_date": "2026-05-19",
    "mode": "standard",
    "founders": [
        {"name": "Alice", "founder_id": "founder_alice", "common_shares": 5_000_000},
        {"name": "Bob", "founder_id": "founder_bob", "common_shares": 5_000_000},
    ],
    "preferred_series": [],
    "option_pool": {"plan_type": "nso", "authorized": 1_500_000, "issued": 500_000, "unallocated": 1_000_000},
    "common_batches": [],
    "metadata": {"run_id": "test"},
}

_FULL_INSTRUMENTS: dict[str, Any] = {
    "safes": [
        {
            "id": "safe_001",
            "investor_name": "Anon A",
            "purchase_amount": 500_000,
            "post_money_valuation_cap": 8_000_000,
            "discount_multiplier": None,
            "mfn_provision": None,
            "pro_rata_side_letter": None,
            "issuance_date": "2025-01-01",
            "form": "yc_postmoney_cap",
            "conversion_price_override": None,
            "source_document": None,
            "extraction_confidence": "high",
        }
    ],
    "convertible_notes": [
        {
            "id": "note_001",
            "investor_name": "Anon B",
            "principal": 200_000,
            "annual_interest_rate": 0.06,
            "day_count_basis": 365,
            "compounding_periods_per_year": None,
            "interest_converts_to_shares": True,
            "issuance_date": "2025-06-01",
            "last_interest_event_date": None,
            "valuation_cap": 10_000_000,
            "discount_multiplier": 0.80,
            "capitalization_denominator": 10_000_000,
            "capitalization_denominator_policy": "pre-money fully diluted",
            "qualified_financing_threshold": 1_000_000,
            "maturity_date": "2027-06-01",
            "maturity_default_treatment": "convert_at_cap",
            "maturity_conversion_price_override": None,
            "non_qualified_financing_treatment": None,
            "source_document": None,
            "extraction_confidence": "high",
        }
    ],
    "warrants": [],
    "option_grants": [],
    "metadata": {"run_id": "test"},
}


def _build_full_agg() -> dict[str, Any]:
    """Run the solver with all driver classes active and return aggregate_ownership_by_class."""
    cs = cap_state_mod.build_cap_state(_FULL_INPUTS, _FULL_INSTRUMENTS)
    result = priced_round_mod.solve_priced_round(
        cap_state=cs,
        safes=_FULL_INSTRUMENTS["safes"],
        notes=_FULL_INSTRUMENTS["convertible_notes"],
        pre_money=20_000_000,
        new_money=5_000_000,
        target_pool_percent=0.10,
        target_basis="pre_money",
        conversion_event_date="2026-06-01",
    )
    assert result["completeness"] == "full", f"Fixture solve failed: {result.get('blockers')}"
    agg: dict[str, Any] = result["aggregate_ownership_by_class"]
    return agg


def _build_ad_agg() -> dict[str, Any]:
    """Run the solver with AD protection active — produces the three AD meta keys."""
    inputs_ad = copy.deepcopy(_FULL_INPUTS)
    inputs_ad["preferred_series"] = [
        {
            "series_id": "series_a",
            "series_name": "Series A",
            "shares": 2_000_000,
            "original_issue_price": 1.0,
            "original_conversion_price": 1.0,
            "current_conversion_price": 1.0,
            "issuance_date": "2024-01-01",
            "anti_dilution_protection": "broad_based_weighted_average",
            "ad_trigger_basis": "original_issue_price",
            "ad_a_denominator_basis": "nvca_broad",
        }
    ]
    cs = cap_state_mod.build_cap_state(inputs_ad, _FULL_INSTRUMENTS)
    # Down round: pre_money well below original issue price * FD so AD fires
    result = priced_round_mod.solve_priced_round(
        cap_state=cs,
        safes=[],
        notes=[],
        pre_money=5_000_000,  # down round → PPS < OIP → AD triggers
        new_money=1_000_000,
        conversion_event_date="2026-06-01",
    )
    assert result["completeness"] == "full", f"AD fixture solve failed: {result.get('blockers')}"
    agg: dict[str, Any] = result["aggregate_ownership_by_class"]
    # Confirm AD meta keys are actually present (otherwise the AD tests are vacuous)
    assert "founders_pct_pre_anti_dilution" in agg, "AD fixture did not produce AD meta keys"
    return agg


# ===========================================================================
# Test 1 + 2: visualize.py ownership-key coverage + palette coverage
# ===========================================================================


class TestVisualizeOwnershipKeyCoverage:
    """Every key the solver can emit in aggregate_ownership_by_class is either
    rendered by visualize.py or listed in EXCLUDED_OWNERSHIP_KEYS.

    Invariant: produced_scalar_keys ⊆ rendered_keys ∪ EXCLUDED_OWNERSHIP_KEYS.

    Where rendered_keys are the keys whose _pct suffix stripped form appears in
    PALETTE (the renderer uses _palette_color which strips the _pct suffix).
    The inverse hygiene direction (no stale exclusions) is also checked.
    """

    def _import_visualize(self) -> Any:
        import importlib
        import types

        # Load with a unique sys.modules key so multiple test classes don't
        # collide with each other or with the top-level import.
        mod_name = "_test_viz_cap_coverage_visualize"
        if mod_name in sys.modules:
            return sys.modules[mod_name]
        script_path = os.path.join(SCRIPTS, "visualize.py")
        spec = importlib.util.spec_from_file_location(  # type: ignore[attr-defined]
            mod_name, script_path
        )
        assert spec is not None and spec.loader is not None
        mod = types.ModuleType(mod_name)
        mod.__spec__ = spec  # type: ignore[assignment]
        # __file__ must be set before exec_module so the script's own
        # sys.path.insert(0, os.path.dirname(__file__)) resolves correctly.
        mod.__file__ = script_path  # type: ignore[assignment]
        # Pre-stub _theme so visualize.py loads without needing to import it
        _theme_stub = types.ModuleType("_theme")
        _theme_stub.brand_css = lambda: ""  # type: ignore[attr-defined]
        _theme_stub.FOOTER_CREDIT_HTML = ""  # type: ignore[attr-defined]
        sys.modules.setdefault("_theme", _theme_stub)
        sys.modules[mod_name] = mod
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        return mod

    def test_scalar_produced_keys_all_covered(self) -> None:
        """Every scalar *_pct key the solver emits (base case: no AD) is either
        in the renderer's PALETTE (rendered) or in EXCLUDED_OWNERSHIP_KEYS
        (explicitly excluded).

        Derivation: live fixture — call the solver with all driver classes
        (founders, preferred, pool, safe, note, new_money) and inspect the
        actual aggregate dict keys.  This approach fails the next time the
        producer grows a new key because the assertion will catch the gap.
        """
        viz = self._import_visualize()
        agg = _build_full_agg()

        # Scalar ownership keys (non-dict values) — these are the ones renderers
        # attempt to draw as donut wedges.
        scalar_keys = {k for k, v in agg.items() if isinstance(v, (int, float))}

        # A key is "rendered" if the renderer knows its colour (palette lookup
        # strips _pct suffix).  Keys that hit PALETTE["neutral"] are still rendered
        # (they draw a grey wedge), but the invariant we care about is that every
        # excluded key is NOT in PALETTE — i.e., the exclusion is intentional.
        rendered_keys = {f"{cat}_pct" for cat in viz.PALETTE if cat != "neutral"}
        rendered_keys |= set(viz.PALETTE)  # allow bare-name keys too

        uncovered = scalar_keys - rendered_keys - viz.EXCLUDED_OWNERSHIP_KEYS
        assert not uncovered, (
            f"visualize.py: {len(uncovered)} produced key(s) not in PALETTE and not excluded: "
            f"{sorted(uncovered)}. Add to EXCLUDED_OWNERSHIP_KEYS or PALETTE."
        )

    def test_ad_meta_keys_all_excluded(self) -> None:
        """The three AD meta keys the solver conditionally adds must be in
        EXCLUDED_OWNERSHIP_KEYS so they never appear as donut wedges.
        """
        viz = self._import_visualize()
        agg = _build_ad_agg()

        ad_meta_keys = {k for k, v in agg.items() if isinstance(v, (int, float))} - {
            "founders_pct",
            "preferred_pct",
            "option_pool_pct",
            "safe_pct",
            "note_pct",
            "new_money_pct",
        }

        uncovered_ad = ad_meta_keys - viz.EXCLUDED_OWNERSHIP_KEYS
        assert not uncovered_ad, (
            f"visualize.py: AD meta key(s) not in EXCLUDED_OWNERSHIP_KEYS: "
            f"{sorted(uncovered_ad)}.  These would draw a spurious donut wedge."
        )

    def test_no_stale_exclusions(self) -> None:
        """Every key in EXCLUDED_OWNERSHIP_KEYS must be a real producer key
        (emittable by the solver with AD active).

        Rationale: stale exclusions are not a correctness hazard but signal
        that the exclusion list drifted from the producer.  A comment in the
        exclusion list is the right remedy; deleting a real defensive exclusion
        is wrong.  This test catches purely stale entries (the solver no longer
        emits them at all), not intentionally defensive ones.
        """
        viz = self._import_visualize()
        agg_ad = _build_ad_agg()
        all_producer_keys = set(agg_ad.keys())  # includes non-scalar like founders_by_class

        stale = viz.EXCLUDED_OWNERSHIP_KEYS - all_producer_keys
        assert not stale, (
            f"visualize.py: EXCLUDED_OWNERSHIP_KEYS contains key(s) the solver never emits: "
            f"{sorted(stale)}.  Remove stale entries; if the exclusion is deliberately "
            f"defensive for a branch this test's fixture does not exercise, extend the "
            f"fixture (or this test's expected set) instead of deleting the exclusion."
        )

    def test_palette_covers_all_renderable_classes(self) -> None:
        """Every ownership class the solver emits as a non-excluded scalar *_pct
        key has a named PALETTE entry (not just the neutral fallback) — a new
        producer class fails here until its colour is added to PALETTE.

        Scope note: `warrants` enters rendering via visualize.py's
        cap_state-derived pre-round breakdown, not via this solver aggregate;
        its palette presence is pinned by the palette tests in
        test_cap_table.py, not here.
        """
        viz = self._import_visualize()
        agg = _build_full_agg()

        scalar_keys = {k for k, v in agg.items() if isinstance(v, (int, float))}
        renderable = scalar_keys - viz.EXCLUDED_OWNERSHIP_KEYS

        # Strip the _pct suffix to get the class name the palette is keyed by
        missing_palette = {k for k in renderable if k.removesuffix("_pct") not in viz.PALETTE}
        assert not missing_palette, (
            f"visualize.py: renderable key(s) have no named PALETTE entry (would render grey): "
            f"{sorted(missing_palette)}.  Add a colour to PALETTE."
        )


# ===========================================================================
# Test 3: explore.py ownership-key coverage + palette coverage
# ===========================================================================


class TestExploreOwnershipKeyCoverage:
    """Same invariants as TestVisualizeOwnershipKeyCoverage but for explore.py.

    explore.py uses _filter_agg() which combines the excluded-keys list AND an
    isinstance(v, (int, float)) guard.  Both layers are tested.
    """

    def _import_explore(self) -> Any:
        import importlib
        import types

        mod_name = "_test_viz_cap_coverage_explore"
        if mod_name in sys.modules:
            return sys.modules[mod_name]

        # explore.py imports _theme at call time; stub it
        _theme_stub = types.ModuleType("_theme")
        _theme_stub.brand_css = lambda: ""  # type: ignore[attr-defined]
        _theme_stub.FOOTER_CREDIT_HTML = ""  # type: ignore[attr-defined]
        sys.modules.setdefault("_theme", _theme_stub)

        # explore.py reads the vendored Chart.js at render time; it is tracked
        # in the repo. Never write a stub into the repo tree — skip instead.
        chart_vendored = os.path.join(SCRIPTS, "vendor", "chart.min.js")
        if not os.path.exists(chart_vendored):
            pytest.skip("vendored chart.min.js missing — repo checkout incomplete")

        script_path = os.path.join(SCRIPTS, "explore.py")
        spec = importlib.util.spec_from_file_location(  # type: ignore[attr-defined]
            mod_name, script_path
        )
        assert spec is not None and spec.loader is not None
        mod = types.ModuleType(mod_name)
        mod.__spec__ = spec  # type: ignore[assignment]
        # __file__ must be set before exec_module so the script-level
        # os.path.abspath(__file__) resolves correctly.
        mod.__file__ = script_path  # type: ignore[assignment]
        sys.modules[mod_name] = mod
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        return mod

    def test_filter_agg_excludes_ad_meta_keys(self) -> None:
        """_filter_agg must exclude the three AD meta keys so they never reach
        the JS donut / legend. The expected keys are hardcoded — iterating
        explore.py's own exclusion set would pass vacuously if a key were
        removed from it.
        """
        exp = self._import_explore()
        agg = _build_ad_agg()
        filtered = exp._filter_agg(agg)
        ad_meta_keys = (
            "founders_pct_pre_anti_dilution",
            "preferred_pct_pre_anti_dilution",
            "anti_dilution_delta_pct_points",
        )
        for k in ad_meta_keys:
            assert k in agg, f"fixture no longer emits AD meta key '{k}' — update the fixture"
            assert k not in filtered, f"explore.py._filter_agg let AD meta key '{k}' through to the renderer."

    def test_filter_agg_excludes_dict_values(self) -> None:
        """_filter_agg must exclude non-scalar values (founders_by_class is a
        dict and must never reach the JS donut).
        """
        exp = self._import_explore()
        agg = _build_full_agg()
        filtered = exp._filter_agg(agg)
        for k, v in filtered.items():
            assert isinstance(v, (int, float)), (
                f"explore.py._filter_agg let non-scalar value through for key '{k}': {type(v)}"
            )

    def test_js_palette_covers_renderable_classes(self) -> None:
        """The JS PALETTE dict embedded in explore.py must contain an entry for
        every renderable class the solver can emit.

        Approach: load visualize.py to get the Python-side excluded keys and
        palette, then parse the JS PALETTE block from explore.py source and
        compare.  This is more robust than executing the JS.
        """
        import re

        viz = self._import_visualize()
        excluded = viz.EXCLUDED_OWNERSHIP_KEYS

        # Derive renderable classes from the solver (no-AD fixture)
        agg = _build_full_agg()
        filtered = {k: v for k, v in agg.items() if isinstance(v, (int, float))}
        renderable_classes = {k.removesuffix("_pct") for k in filtered if k not in excluded}

        # Read explore.py source and extract the JS PALETTE block
        with open(os.path.join(SCRIPTS, "explore.py"), encoding="utf-8") as f:
            src = f.read()

        # JS PALETTE in explore.py looks like:
        #   const PALETTE = {{
        #     founders: "#...",
        #     ...
        #   }};
        # The double-brace {{ }} is because it's inside an f-string template.
        palette_block_match = re.search(r"const PALETTE = \{+\s*(.*?)\}\};", src, re.DOTALL)
        assert palette_block_match, "explore.py: could not locate JS PALETTE block"
        palette_block = palette_block_match.group(1)
        # Each line like '  founders: "#0D549D",' → extract "founders".
        # Note: the first key may have zero leading whitespace (it follows
        # directly after the `{{` in the f-string template), so use \s* not \s+.
        js_palette_keys = set(re.findall(r"^[ \t]*(\w+):", palette_block, re.MULTILINE))

        missing = renderable_classes - js_palette_keys
        assert not missing, (
            f"explore.py JS PALETTE missing key(s) for renderable classes: "
            f"{sorted(missing)}.  Add a colour entry to the JS PALETTE block."
        )

    def test_palette_hex_consistency_with_visualize(self) -> None:
        """visualize.py and explore.py must use the same hex value for each
        shared class so the two views are visually consistent.

        Approach: compare the Python PALETTE from visualize.py against the
        hex values parsed from the JS PALETTE block in explore.py.
        """
        viz = self._import_visualize()  # type: ignore[attr-defined]
        import re

        with open(os.path.join(SCRIPTS, "explore.py"), encoding="utf-8") as f:
            src = f.read()

        palette_block_match = re.search(r"const PALETTE = \{+\s*(.*?)\}\};", src, re.DOTALL)
        assert palette_block_match
        palette_block = palette_block_match.group(1)
        # Extract key → hex pairs
        js_pairs = re.findall(r'(\w+):\s*"(#[0-9A-Fa-f]+)"', palette_block)
        js_palette = {k: v for k, v in js_pairs}

        mismatches = []
        for cls, py_hex in viz.PALETTE.items():
            if cls == "neutral":
                # neutral is a fallback in visualize.py; explore.py falls back
                # to the literal "#A6AEB5" string inline — not a PALETTE key.
                # Alignment is checked by the JS fallback "#A6AEB5" matching.
                continue
            if cls in js_palette and js_palette[cls].lower() != py_hex.lower():
                mismatches.append(f"{cls}: visualize={py_hex} explore_js={js_palette[cls]}")

        assert not mismatches, "visualize.py and explore.py use different hex values for same concept: " + "; ".join(
            mismatches
        )

    def _import_visualize(self) -> Any:
        mod_name = "_test_viz_cap_coverage_visualize"
        if mod_name in sys.modules:
            return sys.modules[mod_name]
        import importlib
        import types

        _theme_stub = types.ModuleType("_theme")
        _theme_stub.brand_css = lambda: ""  # type: ignore[attr-defined]
        _theme_stub.FOOTER_CREDIT_HTML = ""  # type: ignore[attr-defined]
        sys.modules.setdefault("_theme", _theme_stub)
        script_path = os.path.join(SCRIPTS, "visualize.py")
        spec = importlib.util.spec_from_file_location(  # type: ignore[attr-defined]
            mod_name, script_path
        )
        assert spec is not None and spec.loader is not None
        mod = types.ModuleType(mod_name)
        mod.__spec__ = spec  # type: ignore[assignment]
        mod.__file__ = script_path  # type: ignore[assignment]
        sys.modules[mod_name] = mod
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        return mod

    def test_mutation_explore_filter_agg_lets_fake_key_through(self) -> None:
        """Removing an exclusion from _EXCLUDED_OWNERSHIP_KEYS causes
        test_filter_agg_excludes_ad_meta_keys to detect the leak.

        Mutation simulation: bypass _filter_agg's exclusion by passing the
        AD key directly to the filtered output and confirm it appears.
        """
        exp = self._import_explore()

        # Simulate what happens if _EXCLUDED_OWNERSHIP_KEYS had the key removed:
        # call the underlying filter with a patched exclusion set that does NOT
        # include the key we're testing.
        agg = _build_ad_agg()
        # Direct dict comprehension replicating _filter_agg logic but with
        # empty exclusion set — AD meta keys should leak through.
        no_exclusion_filtered = {k: v for k, v in agg.items() if isinstance(v, (int, float))}
        # Confirm the AD key would have leaked
        assert "founders_pct_pre_anti_dilution" in no_exclusion_filtered, (
            "Mutation simulation failed: AD key should appear when exclusion is removed."
        )
        # And the real _filter_agg suppresses it
        real_filtered = exp._filter_agg(agg)
        assert "founders_pct_pre_anti_dilution" not in real_filtered, (
            "Real _filter_agg should exclude founders_pct_pre_anti_dilution."
        )


# ===========================================================================
# Test 4: build_top_dilution_drivers coverage
# ===========================================================================


class TestBuildTopDilutionDriversCoverage:
    """Every *_pct dilution-driver key the solver can emit must be surfaced by
    build_top_dilution_drivers.

    The solver emits these driver-relevant aggregate keys:
      new_money_pct, safe_pct, note_pct

    Pool top-up is read from shares_breakdown.pool_topup (not a pct key).

    Invariant: for any scenario where these keys are nonzero, the corresponding
    driver must appear in the returned list.
    """

    def _import_compose(self) -> Any:
        import importlib
        import types

        mod_name = "_test_viz_cap_coverage_compose"
        if mod_name in sys.modules:
            return sys.modules[mod_name]
        script_path = os.path.join(SCRIPTS, "compose_report.py")
        spec = importlib.util.spec_from_file_location(  # type: ignore[attr-defined]
            mod_name, script_path
        )
        assert spec is not None and spec.loader is not None
        mod = types.ModuleType(mod_name)
        mod.__spec__ = spec  # type: ignore[assignment]
        # __file__ must be set so the script's sys.path.insert(__file__) works.
        mod.__file__ = script_path  # type: ignore[assignment]
        # compose_report imports _rule_pack; SCRIPTS is already on sys.path.
        sys.modules[mod_name] = mod
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        return mod

    def _full_scenario_doc(self) -> list[dict[str, Any]]:
        """Build a scenarios list that exercises all four driver classes."""
        cs = cap_state_mod.build_cap_state(_FULL_INPUTS, _FULL_INSTRUMENTS)
        result = priced_round_mod.solve_priced_round(
            cap_state=cs,
            safes=_FULL_INSTRUMENTS["safes"],
            notes=_FULL_INSTRUMENTS["convertible_notes"],
            pre_money=20_000_000,
            new_money=5_000_000,
            target_pool_percent=0.10,
            target_basis="pre_money",
            conversion_event_date="2026-06-01",
        )
        assert result["completeness"] == "full"
        return [
            {
                "scenario_id": "s1",
                "label": "Full priced round",
                "type": "priced_round",
                "parameters": {"pre_money": 20_000_000, "new_money": 5_000_000},
                "computed_outputs": result,
            }
        ]

    def test_all_driver_keys_surfaced(self) -> None:
        """new_money_pct, safe_pct, note_pct, and pool_topup must each produce
        a driver entry when nonzero in the solver output.
        """
        compose = self._import_compose()
        scenarios = self._full_scenario_doc()

        agg = scenarios[0]["computed_outputs"]["aggregate_ownership_by_class"]
        breakdown = scenarios[0]["computed_outputs"]["shares_breakdown"]

        # Confirm all driver keys are nonzero in this fixture
        assert agg.get("new_money_pct", 0) > 0.01, "Fixture: new_money_pct should be nonzero"
        assert agg.get("safe_pct", 0) > 0.01, "Fixture: safe_pct should be nonzero"
        assert agg.get("note_pct", 0) > 0.01, "Fixture: note_pct should be nonzero"
        assert breakdown.get("pool_topup", 0) > 0, "Fixture: pool_topup should be nonzero"

        drivers = compose.build_top_dilution_drivers(scenarios)
        driver_labels = [d["driver"] for d in drivers]

        # Each driver class must appear
        assert any("New money" in label for label in driver_labels), (
            f"build_top_dilution_drivers omitted new_money driver. Got: {driver_labels}"
        )
        assert any("SAFE" in label for label in driver_labels), (
            f"build_top_dilution_drivers omitted SAFE driver. Got: {driver_labels}"
        )
        assert any("Note" in label for label in driver_labels), (
            f"build_top_dilution_drivers omitted Note driver. Got: {driver_labels}"
        )
        assert any("pool" in label.lower() or "Pool" in label for label in driver_labels), (
            f"build_top_dilution_drivers omitted pool top-up driver. Got: {driver_labels}"
        )

    def test_driver_known_key_set_vs_producer(self) -> None:
        """Source-level assertion: the *_pct keys read by build_top_dilution_drivers
        must be a superset of the solver's emittable driver-relevant *_pct keys.

        Approach: read the compose_report.py source and extract the agg.get(...)
        calls inside build_top_dilution_drivers.  Compare against the solver's
        actual output.
        """
        import re

        with open(os.path.join(SCRIPTS, "compose_report.py"), encoding="utf-8") as f:
            src = f.read()

        # Locate the build_top_dilution_drivers function body
        fn_match = re.search(r"def build_top_dilution_drivers\(.*?\n(?=def |\Z)", src, re.DOTALL)
        assert fn_match, "Could not locate build_top_dilution_drivers in compose_report.py"
        fn_body = fn_match.group(0)

        # Extract every agg.get("...") key name in the function
        read_keys = set(re.findall(r'agg\.get\("([^"]+)"', fn_body))

        # The solver's driver-relevant *_pct keys (scalar, non-AD)
        agg = _build_full_agg()
        # These are the driver-relevant keys — exclude AD meta keys (they are
        # dilution-framework metadata, not driver slice pcts) and founders_by_class
        # (dict).  Also exclude keys the renderer explicitly excluded.
        producer_driver_keys = {
            k
            for k, v in agg.items()
            if isinstance(v, (int, float))
            and k
            not in {
                "founders_pct_pre_anti_dilution",
                "preferred_pct_pre_anti_dilution",
                "anti_dilution_delta_pct_points",
                "founders_pct",
                "preferred_pct",
                "option_pool_pct",
            }
        }

        unread = producer_driver_keys - read_keys
        assert not unread, (
            f"build_top_dilution_drivers does not read driver key(s) the solver emits: "
            f"{sorted(unread)}.  Add a driver block for each key."
        )

    def test_mutation_missing_note_driver(self) -> None:
        """Removing note_pct from the function's read set causes the driver to
        be missing from output — the test_all_driver_keys_surfaced assertion
        would fail.

        Mutation simulation: build a scenarios list where note_pct > 0.01 but
        zero out note_pct in the aggregate so build_top_dilution_drivers skips it.
        """
        compose = self._import_compose()
        scenarios = self._full_scenario_doc()

        # Mutate: zero out note_pct so the driver is skipped
        mutated = copy.deepcopy(scenarios)
        mutated[0]["computed_outputs"]["aggregate_ownership_by_class"]["note_pct"] = 0.0

        drivers = compose.build_top_dilution_drivers(mutated)
        driver_labels = [d["driver"] for d in drivers]

        # With note_pct zeroed, note driver must NOT appear (confirms the gate
        # is pct-driven and the mutation is effective)
        assert not any("Note" in label for label in driver_labels), (
            "Mutation simulation failed: zeroing note_pct should suppress the note driver."
        )


# ===========================================================================
# P0 — number-ticker animation wiring (design §10).
#
# These guard the exact regression that shipped before: countUp was defined
# but never called, so the advertised number-ticker silently did nothing. A
# string-presence check is not enough (the definition contains the substring),
# so each guard strips the definition line first, then asserts a remaining
# call site. The node --check test is a syntax/parse net (NOT a runtime net).
# ===========================================================================


def _render_explorer_app_script(tmp: str) -> str:
    """Render explorer.html from a full fixture and return the app <script>
    block — the last one, after the vendored Chart.js block."""
    _make_fixture_dir(tmp)
    out = os.path.join(tmp, "explorer.html")
    rc, _, err = _run("explore.py", ["--dir", tmp, "-o", out])
    assert rc == 0, err
    with open(out, encoding="utf-8") as f:
        html = f.read()
    blocks = re.findall(r"<script>(.*?)</script>", html, re.DOTALL)
    assert blocks, "explorer.html has no <script> blocks"
    return blocks[-1]


class TestExploreNumberTickerWiring:
    def test_countup_invoked_not_just_defined(self) -> None:
        # Proves countUp is reachable (called by animateMetric), not dead-defined.
        # NOTE: this alone does NOT prove the tickers are wired into
        # selectScenario — animateMetric internally calls countUp, so this would
        # pass even if the selectScenario wiring were deleted. The actual wiring
        # is guarded by test_metric_tickers_wired_into_selectscenario below.
        with tempfile.TemporaryDirectory() as d:
            app = _render_explorer_app_script(d)
        without_def = app.replace("function countUp(", "")
        assert "countUp(" in without_def, "countUp is defined but never called — the §10 number-ticker is dead code."

    def test_metric_tickers_wired_into_selectscenario(self) -> None:
        # The real P0 regression guard: each of the three hero metrics must have
        # its own animateMetric call site. If the selectScenario wiring were
        # removed, animateMetric would have zero call sites (it is only called
        # from there) and these asserts would fail.
        with tempfile.TemporaryDirectory() as d:
            app = _render_explorer_app_script(d)
        for metric_id in ("founder-pct", "price-psh", "post-fd"):
            assert f'animateMetric("{metric_id}"' in app, (
                f"Hero metric '{metric_id}' is not wired to animateMetric in selectScenario — "
                "the number-ticker regressed to a snap."
            )

    def test_reduced_motion_guard_present(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            app = _render_explorer_app_script(d)
        assert "prefers-reduced-motion" in app, (
            "Number tickers must honor prefers-reduced-motion (direct-set, no tween)."
        )

    def test_countup_seeds_start_value_synchronously(self) -> None:
        # Without a synchronous seed of `from`, the rebuilt node already holds
        # the final value, so it flashes for one frame before the tween starts.
        with tempfile.TemporaryDirectory() as d:
            app = _render_explorer_app_script(d)
        assert "el.textContent = formatter(from)" in app, (
            "countUp must seed the start value synchronously to avoid a 1-frame flash."
        )

    def test_app_script_parses_with_node_check(self) -> None:
        # Syntax/parse net only — does NOT catch a runtime ReferenceError.
        node = shutil.which("node")
        if node is None:
            pytest.skip("node not available; skipping JS syntax check")
        with tempfile.TemporaryDirectory() as d:
            app = _render_explorer_app_script(d)
            js_path = os.path.join(d, "app.js")
            with open(js_path, "w", encoding="utf-8") as f:
                f.write(app)
            res = subprocess.run([node, "--check", js_path], capture_output=True, text=True)
        assert res.returncode == 0, f"node --check failed on explorer app script:\n{res.stderr}"

    def test_walkthrough_counsel_copy_handles_zero_and_plural(self) -> None:
        # The walkthrough must not read "0 counsel-review items ... questions for
        # your lawyer" when there are none, and must pluralize.
        with tempfile.TemporaryDirectory() as d:
            app = _render_explorer_app_script(d)
        assert "No counsel-review items were flagged" in app, "zero-counsel case not handled in walkthrough"
        assert 'nCounsel === 1 ? "" : "s"' in app, "counsel count not pluralized in walkthrough"
        # The old hardcoded interpolated count must be gone.
        assert "counsel_items.length}} counsel-review items" not in app


# ===========================================================================
# Donut/legend palette — the `_pct` key-mismatch bug.
#
# aggregate_ownership_by_class keys carry a `_pct` suffix (founders_pct, …) but
# PALETTE keys do not. A raw PALETTE[cat] lookup therefore returns undefined and
# every wedge falls back to gray + labels read "founders pct". The render must
# strip `_pct` via sliceColor/sliceLabel. (The existing palette tests only check
# PALETTE *key presence*, so they pass even with this bug live — these guard it.)
# ===========================================================================


class TestExploreDonutPalette:
    def test_ownership_render_uses_pct_stripping_helpers(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            app = _render_explorer_app_script(d)
        assert "sliceColor(" in app and "sliceLabel(" in app, (
            "donut/legend must color+label via sliceColor/sliceLabel (which strip _pct)."
        )

    def test_no_raw_palette_lookup_on_pct_keys(self) -> None:
        # The bug site was a raw `PALETTE[cat]` where cat is a _pct-suffixed key.
        with tempfile.TemporaryDirectory() as d:
            app = _render_explorer_app_script(d)
        assert "PALETTE[cat]" not in app, (
            "raw PALETTE[cat] lookup remains — _pct-suffixed aggregate keys fall back to gray. Use sliceColor(cat)."
        )


# ===========================================================================
# Runtime smoke (the real anti-crash net node --check can't provide).
#
# Runs the inline app script through a minimal DOM shim and lets the wire-up
# call selectScenario(0) for the cap-implied fixture. Catches runtime
# ReferenceErrors / missing-node bugs (e.g. the persistent-DOM refactor losing
# a getElementById target) that a parse check misses. The cap-implied path does
# not touch Chart.js, so no chart engine is needed in the shim.
# ===========================================================================


_DOM_SHIM = r"""
const _byId = {};
function mkEl(id) {
  const _classes = new Set();
  const _listeners = {};
  return {
    id, _html: "", hidden: false, textContent: "", style: {}, dataset: {},
    classList: {
      add(c) { _classes.add(c); },
      remove(c) { _classes.delete(c); },
      contains(c) { return _classes.has(c); },
      toggle(c, force) {
        const on = force === undefined ? !_classes.has(c) : force;
        if (on) _classes.add(c); else _classes.delete(c);
        return on;
      },
    },
    addEventListener(type, fn) { (_listeners[type] = _listeners[type] || []).push(fn); },
    dispatchEvent(ev) { (_listeners[ev.type] || []).forEach(fn => fn(ev)); return true; },
    click() { this.dispatchEvent({ type: "click", target: this }); },
    append() {}, querySelectorAll() { return []; },
    setAttribute(k, v) { this["_attr_" + k] = v; },
    getAttribute(k) { return this["_attr_" + k] ?? null; },
    set innerHTML(v) { this._html = v; if (this.id) _byId[this.id] = this; },
    get innerHTML() { return this._html; },
  };
}
global.document = {
  getElementById(id) { return _byId[id] || (_byId[id] = mkEl(id)); },
  querySelectorAll() { return []; },
  addEventListener() {},
  createElement() { return null; },  // canvas/pattern path falls back to solid
  body: mkEl("body"),
};
global.window = { matchMedia() { return { matches: false }; } };
global.location = { search: "" };
global.URLSearchParams = class { constructor() {} get() { return null; } };
global.requestAnimationFrame = function () {};
global.performance = { now() { return 0; } };
global.getComputedStyle = function () { return { getPropertyValue() { return "#000"; } }; };
// Run timers synchronously so the Sankey fade swap (setTimeout) actually
// executes within the test rather than after node exits.
global.setTimeout = function (fn) { fn(); return 0; };
global.clearTimeout = function () {};
global.Chart = class {
  constructor(el, cfg) { this.canvas = el; this.data = cfg.data; this.options = cfg.options; }
  update() {}
  destroy() {}
};
"""


def _full_scenario(scenario_id: str, label: str, founders_pct: float) -> dict[str, Any]:
    """A 'full' priced-round scenario that exercises the donut + Sankey path."""
    return {
        "scenario_id": scenario_id,
        "label": label,
        "type": "priced_round",
        "parameters": {"pre_money": 20_000_000, "new_money": 5_000_000},
        "computed_outputs": {
            "completeness": "full",
            "cap_implied_only": False,
            "blockers": [],
            "math_provenance": [],
            "aggregate_ownership_by_class": {
                "founders_pct": founders_pct,
                "preferred_pct": 0.20,
                "option_pool_pct": 0.10,
                "new_money_pct": round(0.70 - founders_pct, 4),
            },
            "equity_financing_price": 1.2345,
            "post_round_fully_diluted_shares": 8_000_000,
            "shares_breakdown": {
                "pre_round_fully_diluted": 6_000_000,
                "new_money": 2_000_000,
                "safe_converted": 0,
                "note_converted": 0,
                "pool_topup": 0,
            },
            "founder_impact": {"plain_language": "Founders diluted to a controlling-but-shared stake."},
            "per_safe": {},
            "per_note": {},
        },
    }


class TestExploreRuntimeSmoke:
    def test_selectscenario_runs_headless_without_error(self) -> None:
        node = shutil.which("node")
        if node is None:
            pytest.skip("node not available; skipping headless runtime smoke")
        with tempfile.TemporaryDirectory() as d:
            app = _render_explorer_app_script(d)
            runner = (
                _DOM_SHIM
                + "\n"
                + app
                + "\nconst _v = document.getElementById('scenario-variable').innerHTML || '';"
                + "\nif (!_v.length) throw new Error('selectScenario did not populate scenario-variable');"
                + "\nconsole.log('OK_NO_THROW');\n"
            )
            js_path = os.path.join(d, "runner.js")
            with open(js_path, "w", encoding="utf-8") as f:
                f.write(runner)
            res = subprocess.run([node, js_path], capture_output=True, text=True)
        assert res.returncode == 0 and "OK_NO_THROW" in res.stdout, (
            f"explorer app threw at runtime running selectScenario(0):\n{res.stderr}"
        )

    def test_donut_morph_and_sankey_path_run_headless(self) -> None:
        # Exercise the full/mixed render path (donut .update() morph + Sankey
        # transition) by switching between two full scenarios. Catches runtime
        # bugs in renderDonut/renderSankey the cap-implied smoke can't reach.
        node = shutil.which("node")
        if node is None:
            pytest.skip("node not available; skipping headless morph smoke")
        with tempfile.TemporaryDirectory() as d:
            _make_fixture_dir(d)
            scenarios = {
                "scenarios": [
                    _full_scenario("p1", "Base case", 0.50),
                    _full_scenario("p2", "Higher pre-money", 0.55),
                ],
                "metadata": {"run_id": "rid1"},
            }
            with open(os.path.join(d, "scenarios.json"), "w", encoding="utf-8") as f:
                json.dump(scenarios, f)
            out = os.path.join(d, "explorer.html")
            rc, _, err = _run("explore.py", ["--dir", d, "-o", out])
            assert rc == 0, err
            with open(out, encoding="utf-8") as f:
                app = re.findall(r"<script>(.*?)</script>", f.read(), re.DOTALL)[-1]
            # load (auto-selects scenario 0 → new Chart), then switch to 1 → morph.
            runner = (
                _DOM_SHIM
                + "\n"
                + app
                + "\nselectScenario(1);"  # exercises the in-place .update() morph branch
                # With synchronous setTimeout the Sankey fade swap runs; assert it populated.
                + "\nconst _sk = document.getElementById('sankey').innerHTML || '';"
                + "\nif (!_sk.length) throw new Error('Sankey not populated after switch');"
                + "\nconsole.log('OK_MORPH');\n"
            )
            js_path = os.path.join(d, "runner.js")
            with open(js_path, "w", encoding="utf-8") as f:
                f.write(runner)
            res = subprocess.run([node, js_path], capture_output=True, text=True)
        assert res.returncode == 0 and "OK_MORPH" in res.stdout, (
            f"donut morph / Sankey path threw at runtime:\n{res.stderr}"
        )


class TestExploreDonutMorphWiring:
    def test_donut_morphs_in_place_over_stable_order(self) -> None:
        # Locks the morph (a behavioral test still passes with destroy+recreate,
        # so guard the in-place update + stable order explicitly).
        with tempfile.TemporaryDirectory() as d:
            app = _render_explorer_app_script(d)
        # The donut morphs in place by updating the chart registered for its
        # canvas (the per-canvas registry, not a single shared instance).
        assert "DONUT_ORDER" in app and "existing.update(" in app, (
            "donut must morph in place over a stable category order (P1), not destroy+recreate."
        )
        assert "filter: item => item.parsed > 0" in app, (
            "tooltip must filter the zero-area wedges the fixed order introduces."
        )

    def test_sankey_uses_transition_helper(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            app = _render_explorer_app_script(d)
        assert "function setSankeyHTML" in app and "setSankeyHTML(container" in app, (
            "Sankey must swap via the fade transition helper (P2), not a raw innerHTML snap."
        )

    def test_card_slide_in_applied(self) -> None:
        # P3 / §10-D: impact callout + compare banner mount with a fade+translate.
        with tempfile.TemporaryDirectory() as d:
            app = _render_explorer_app_script(d)
        assert "function slideIn" in app, "card mount animation helper missing"
        assert app.count("slideIn(") >= 3, "slideIn must be applied to the impact callout and the compare view."


# ===========================================================================
# P4 — pre-money sweep generator (sweep.py) + explorer slider.
# ===========================================================================


def _write_priced_round_base(d: str) -> None:
    """Overwrite scenarios.json with a priced_round base (pre_money + new_money)."""
    scen = {
        "scenarios": [
            {
                "scenario_id": "pr1",
                "label": "Series A",
                "type": "priced_round",
                "parameters": {"pre_money": 20_000_000, "new_money": 5_000_000},
                "computed_outputs": {"completeness": "full", "math_provenance": [], "blockers": []},
            }
        ],
        "metadata": {"run_id": "rid1"},
    }
    with open(os.path.join(d, "scenarios.json"), "w", encoding="utf-8") as f:
        json.dump(scen, f)


class TestSweepGenerator:
    def test_generates_real_frames_monotonic(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            _make_fixture_dir(d)
            _write_priced_round_base(d)
            out = os.path.join(d, "sweep.json")
            rc, _, err = _run("sweep.py", ["--dir", d, "--run-id", "rid1", "-o", out, "--steps", "13"])
            assert rc == 0, err
            with open(out, encoding="utf-8") as f:
                sw = json.load(f)
        assert sw["axis"] == "pre_money"
        assert len(sw["frames"]) == 13
        assert all(fr["valid"] for fr in sw["frames"])
        fps = [fr["outputs"]["aggregate_ownership_by_class"]["founders_pct"] for fr in sw["frames"]]
        # Higher pre-money -> less dilution -> higher founder %. Every frame is
        # real solver output (no interpolation).
        assert fps == sorted(fps), "founder % must rise monotonically with pre-money"

    def test_new_money_held_fixed(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            _make_fixture_dir(d)
            _write_priced_round_base(d)
            out = os.path.join(d, "sweep.json")
            _run("sweep.py", ["--dir", d, "--run-id", "rid1", "-o", out])
            with open(out, encoding="utf-8") as f:
                sw = json.load(f)
        assert {fr["new_money"] for fr in sw["frames"]} == {5_000_000}

    def test_no_base_scenario_yields_empty_sweep(self) -> None:
        # The default fixture has only a cap-implied safe_conversion scenario.
        with tempfile.TemporaryDirectory() as d:
            _make_fixture_dir(d)
            out = os.path.join(d, "sweep.json")
            rc, _, err = _run("sweep.py", ["--dir", d, "--run-id", "rid1", "-o", out])
            assert rc == 0, err
            with open(out, encoding="utf-8") as f:
                sw = json.load(f)
        assert sw["frames"] == [] and sw["base_scenario_id"] is None

    def test_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            _make_fixture_dir(d)
            _write_priced_round_base(d)
            o1, o2 = os.path.join(d, "s1.json"), os.path.join(d, "s2.json")
            _run("sweep.py", ["--dir", d, "--run-id", "rid1", "-o", o1])
            _run("sweep.py", ["--dir", d, "--run-id", "rid1", "-o", o2])
            with open(o1, encoding="utf-8") as f:
                a = f.read()
            with open(o2, encoding="utf-8") as f:
                b = f.read()
        assert a == b

    def test_steps_one_uses_base_pre_money(self) -> None:
        # --steps 1 must produce the base value, not the low end of the range.
        with tempfile.TemporaryDirectory() as d:
            _make_fixture_dir(d)
            _write_priced_round_base(d)
            out = os.path.join(d, "sweep.json")
            _run("sweep.py", ["--dir", d, "--run-id", "rid1", "-o", out, "--steps", "1"])
            with open(out, encoding="utf-8") as f:
                sw = json.load(f)
        assert len(sw["frames"]) == 1
        assert sw["frames"][0]["pre_money"] == sw["base_pre_money"] == 20_000_000


class TestExploreSweepSlider:
    def _render_with_sweep(self, d: str) -> str:
        _make_fixture_dir(d)
        _write_priced_round_base(d)
        _run("sweep.py", ["--dir", d, "--run-id", "rid1", "-o", os.path.join(d, "sweep.json")])
        out = os.path.join(d, "explorer.html")
        rc, _, err = _run("explore.py", ["--dir", d, "-o", out])
        assert rc == 0, err
        with open(out, encoding="utf-8") as f:
            return f.read()

    def test_slider_present_with_sweep(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            html = self._render_with_sweep(d)
        assert 'id="sweep-slider"' in html
        app = re.findall(r"<script>(.*?)</script>", html, re.DOTALL)[-1]
        assert "function initSweep" in app and "function applySweepFrame" in app
        assert "aria-valuetext" in app, "slider must announce its value to screen readers"

    def test_no_slider_without_sweep(self) -> None:
        # Back-compat: no sweep.json → sweep payload null → slider stays hidden.
        with tempfile.TemporaryDirectory() as d:
            _make_fixture_dir(d)
            out = os.path.join(d, "explorer.html")
            rc, _, err = _run("explore.py", ["--dir", d, "-o", out])
            assert rc == 0, err
            with open(out, encoding="utf-8") as f:
                app = re.findall(r"<script>(.*?)</script>", f.read(), re.DOTALL)[-1]
        assert '"sweep": null' in app or '"sweep":null' in app

    def test_slider_snaps_number_to_real_frame_headless(self) -> None:
        # Drag the slider headless; the founder-% must equal a real frame value
        # (snap — no fabricated in-between number).
        node = shutil.which("node")
        if node is None:
            pytest.skip("node not available")
        with tempfile.TemporaryDirectory() as d:
            html = self._render_with_sweep(d)
            app = re.findall(r"<script>(.*?)</script>", html, re.DOTALL)[-1]
            runner = (
                _DOM_SHIM
                + "\n"
                + app
                + "\napplySweepFrame(0);"
                + "\nconst _txt = document.getElementById('founder-pct').textContent || '';"
                + "\nconst _f0 = DATA.sweep.frames[0].aggregate.founders_pct;"
                + "\nconst _expect = (_f0 * 100).toFixed(1) + '%';"
                + "\nif (_txt !== _expect) throw new Error('slider number not real: ' + _txt + ' vs ' + _expect);"
                + "\nconsole.log('OK_SLIDER');\n"
            )
            js_path = os.path.join(d, "runner.js")
            with open(js_path, "w", encoding="utf-8") as f:
                f.write(runner)
            res = subprocess.run([node, js_path], capture_output=True, text=True)
        assert res.returncode == 0 and "OK_SLIDER" in res.stdout, res.stderr

    def test_slider_updates_legend_sankey_and_impact(self) -> None:
        # Dragging the slider must update the legend (per-class % next to the
        # pie), the dilution-flow Sankey, AND the Founder-Impact callout — not
        # just the top numbers + donut.
        node = shutil.which("node")
        if node is None:
            pytest.skip("node not available")
        with tempfile.TemporaryDirectory() as d:
            html = self._render_with_sweep(d)
            app = re.findall(r"<script>(.*?)</script>", html, re.DOTALL)[-1]
            runner = (
                _DOM_SHIM
                + "\n"
                + app
                + "\nselectScenario(0);"  # the priced-round base is full → legend/sankey/impact present
                + "\napplySweepFrame(0);"
                + "\nconst leg0 = document.getElementById('legend').innerHTML || '';"
                + "\nconst snk0 = document.getElementById('sankey').innerHTML || '';"
                + "\nconst imp0 = document.getElementById('impact-callout').innerHTML || '';"
                + "\napplySweepFrame(DATA.sweep.frames.length - 1);"
                + "\nconst leg1 = document.getElementById('legend').innerHTML || '';"
                + "\nconst snk1 = document.getElementById('sankey').innerHTML || '';"
                + "\nconst imp1 = document.getElementById('impact-callout').innerHTML || '';"
                + "\nif (!leg0.length || leg0 === leg1) throw new Error('legend did not update on slider drag');"
                + "\nif (!snk0.length || snk0 === snk1) throw new Error('sankey did not update on slider drag');"
                + "\nif (!imp0.length || imp0 === imp1) throw new Error('impact did not update on slider drag');"
                + "\nconsole.log('OK_LEGEND_SANKEY_IMPACT');\n"
            )
            js_path = os.path.join(d, "runner.js")
            with open(js_path, "w", encoding="utf-8") as f:
                f.write(runner)
            res = subprocess.run([node, js_path], capture_output=True, text=True)
        assert res.returncode == 0 and "OK_LEGEND_SANKEY_IMPACT" in res.stdout, res.stderr

    def test_slider_panel_matches_scenario_selection_comprehensive(self) -> None:
        # COMPREHENSIVE guard against per-element whack-a-mole: applySweepFrame(i)
        # must produce the SAME pre-money-dependent panel as selecting that frame
        # as a full scenario. If any element is wired into selectScenario's full
        # path but not the slider (or vice-versa), the signatures diverge and this
        # fails — naming the offending element.
        node = shutil.which("node")
        if node is None:
            pytest.skip("node not available")
        with tempfile.TemporaryDirectory() as d:
            html = self._render_with_sweep(d)
            app = re.findall(r"<script>(.*?)</script>", html, re.DOTALL)[-1]
            # Reduced-motion so selectScenario direct-sets metrics (matching the
            # slider's snap), making the two panels directly comparable.
            shim_rm = _DOM_SHIM.replace(
                "matchMedia() { return { matches: false }; }", "matchMedia() { return { matches: true }; }"
            )
            probe = (
                "\nfunction _panelSig() {"
                "\n  const g = id => { const e = document.getElementById(id);"
                "\n    return e ? (e.innerHTML || e.textContent || '') : null; };"
                "\n  return JSON.stringify({"
                "\n    fp: g('founder-pct'), price: g('price-psh'), fd: g('post-fd'),"
                "\n    legend: g('legend'), impact: g('impact-callout'),"
                "\n    variable: g('scenario-variable'), sankey: g('sankey'),"
                "\n    donut: _charts['donut-chart']"
                "\n      ? JSON.stringify(_charts['donut-chart'].data.datasets[0].data) : null,"
                "\n  });"
                "\n}"
                "\nconst _i = DATA.sweep.frames.length - 1;"  # use a frame far from the base
                "\nconst _fr = DATA.sweep.frames[_i];"
                "\nconst _synth = { scenario_id: 'probe', label: 'probe', type: 'priced_round',"
                "\n  completeness: 'full', cap_implied_only: false, blockers: [],"
                "\n  aggregate: _fr.aggregate, equity_financing_price: _fr.equity_financing_price,"
                "\n  post_round_fd: _fr.post_round_fd, shares_breakdown: _fr.shares_breakdown,"
                "\n  founder_impact: _fr.impact_text ? { plain_language: _fr.impact_text } : null,"
                "\n  per_safe: _fr.per_safe, per_note: _fr.per_note, parameters: {} };"
                "\nDATA.scenarios.push(_synth);"
                "\nselectScenario(DATA.scenarios.length - 1);"  # render the frame AS a scenario
                "\nconst _sigScenario = _panelSig();"
                "\napplySweepFrame(_i);"  # render the same frame via the slider
                "\nconst _sigSlider = _panelSig();"
                "\nif (_sigScenario !== _sigSlider) {"
                "\n  const a = JSON.parse(_sigScenario), b = JSON.parse(_sigSlider);"
                "\n  const diff = Object.keys(a).filter(k => a[k] !== b[k]);"
                "\n  throw new Error('slider panel diverges from scenario in: ' + diff.join(', '));"
                "\n}"
                "\nconsole.log('OK_COMPREHENSIVE');"
            )
            runner = shim_rm + "\n" + app + "\n" + probe + "\n"
            js_path = os.path.join(d, "runner.js")
            with open(js_path, "w", encoding="utf-8") as f:
                f.write(runner)
            res = subprocess.run([node, js_path], capture_output=True, text=True)
        assert res.returncode == 0 and "OK_COMPREHENSIVE" in res.stdout, res.stderr


class TestVisualizeCapImplied:
    def test_cap_implied_card_shows_table_not_phantom_blockers(self) -> None:
        # The fixture's only scenario is cap_implied_only with per_safe data and
        # NO blockers. The report card must show the cap-implied ownership table,
        # not "see blockers" (there are none).
        with tempfile.TemporaryDirectory() as d:
            _make_fixture_dir(d)
            out = os.path.join(d, "report.html")
            rc, _, err = _run("visualize.py", ["--dir", d, "-o", out])
            assert rc == 0, err
            with open(out, encoding="utf-8") as f:
                html_doc = f.read()
        assert "Cap-implied %" in html_doc, "cap-implied per-SAFE table missing from report"
        assert "see blockers" not in html_doc, "report claims 'see blockers' for a cap-implied scenario that has none"


class TestHumanizedLabels:
    """Internal enums must not leak as visible prose into founder-facing output;
    they appear as friendly labels with the raw code only as a hover tooltip."""

    def test_report_humanizes_completeness_and_type(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            _make_fixture_dir(d)  # cap-implied safe_conversion / structural_only
            out = os.path.join(d, "report.html")
            rc, _, err = _run("visualize.py", ["--dir", d, "-o", out])
            assert rc == 0, err
            with open(out, encoding="utf-8") as f:
                html_doc = f.read()
        assert "SAFE conversion" in html_doc, "scenario type not humanized in report"
        assert "Structure only" in html_doc, "completeness not humanized in report"
        # The raw enum must not appear as visible text — only inside a title= tooltip.
        assert "<code>structural_only</code>" not in html_doc
        assert ">structural_only<" not in html_doc
        assert 'title="structural_only"' in html_doc, "raw enum should be preserved as a tooltip"

    def test_explorer_carries_label_map_and_helpers(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            app = _render_explorer_app_script(d)
        assert "const LABELS" in app, "explorer missing the injected label map"
        assert "function humanize" in app and "function term" in app, "explorer missing label helpers"


class TestWatchlistGrouping:
    def test_group_watchlist_dedupes_and_picks_urgent(self) -> None:
        import _rules  # type: ignore[import-not-found]

        items = [
            {
                "rule_id": "r.a",
                "title": "Rule A",
                "current_status": "pre_effective",
                "event_date_value": "2024-09-01",
                "action_required": "wait",
            },
            {
                "rule_id": "r.a",
                "title": "Rule A",
                "current_status": "in_window",
                "event_date_value": "2025-01-15",
                "action_required": "act now",
            },
            {
                "rule_id": "r.b",
                "title": "Rule B",
                "current_status": "missing_event_date",
                "event_date_value": None,
                "action_required": "give date",
            },
        ]
        grouped = _rules.group_watchlist(items)
        assert len(grouped) == 2, "per-instance rows must collapse to one row per rule"
        a = next(g for g in grouped if g["rule_id"] == "r.a")
        assert a["count"] == 2
        assert a["status"] == "in_window", "most-urgent status must win"
        assert a["action"] == "act now", "action must come from the urgent instance"
        assert a["dates"] == ["2024-09-01", "2025-01-15"]

    def test_report_watchlist_is_slim_and_deduped(self) -> None:
        # Inject a watchlist with the same rule firing on two instances; the
        # report must show one row per rule with Rule/Status/When/Action (no
        # Scope column, no rule-code in the cell).
        with tempfile.TemporaryDirectory() as d:
            _make_fixture_dir(d)
            with open(os.path.join(d, "rule_audit.json"), encoding="utf-8") as f:
                ra = json.load(f)
            ra["date_sensitive_watchlist"] = [
                {
                    "rule_id": "safe.israeli_2025_safe_harbor",
                    "title": "Israel 2025 SAFE temporary guidance",
                    "scope": "legal_tax_applicability",
                    "current_status": "in_window",
                    "event_date_value": "2025-01-15",
                    "action_required": "Confirm the SAFE was signed in the safe-harbor window.",
                    "applies_when_matched": True,
                },
                {
                    "rule_id": "safe.israeli_2025_safe_harbor",
                    "title": "Israel 2025 SAFE temporary guidance",
                    "scope": "legal_tax_applicability",
                    "current_status": "pre_effective",
                    "event_date_value": "2024-09-01",
                    "action_required": "Window has not started yet.",
                    "applies_when_matched": True,
                },
            ]
            with open(os.path.join(d, "rule_audit.json"), "w", encoding="utf-8") as f:
                json.dump(ra, f)
            out = os.path.join(d, "report.html")
            rc, _, err = _run("visualize.py", ["--dir", d, "-o", out])
            assert rc == 0, err
            with open(out, encoding="utf-8") as f:
                html_doc = f.read()
        seg = html_doc[html_doc.find("Date-sensitive watchlist") :]
        for col in ("<th>Rule</th>", "<th>Status</th>", "<th>When</th>", "<th>Action</th>"):
            assert col in seg, f"watchlist missing column {col}"
        assert "<th>Scope</th>" not in seg, "Scope column should be dropped"
        # Two instances of one rule → one row (one <tr> in the tbody).
        tbody = seg[seg.find("<tbody>") : seg.find("</tbody>")]
        assert tbody.count("<tr>") == 1, "per-instance watchlist rows must dedupe to one per rule"
        assert "rule-code" not in tbody, "compact watchlist cell must not show the raw rule_id code"
        assert "· 2×" in tbody, "deduped row should show the instance count"


# ===========================================================================
# Explorer usability surface — responsive layout, de-emoji chrome, contained
# what-if slider, default-to-modeled view, plain-language flow, counsel cue +
# relevance + codes toggle, print-to-PDF, donut accessibility, controllable
# walkthrough.
# ===========================================================================


def _render_explorer_full(tmp: str) -> str:
    """Render explorer.html from a full fixture and return the whole document."""
    _make_fixture_dir(tmp)
    out = os.path.join(tmp, "explorer.html")
    rc, _, err = _run("explore.py", ["--dir", tmp, "-o", out])
    assert rc == 0, err
    with open(out, encoding="utf-8") as f:
        return f.read()


class TestExploreResponsiveLayout:
    def test_breakpoints_present(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            html = _render_explorer_full(d)
        assert "@media (max-width: 1180px)" in html, "tablet breakpoint missing"
        assert "@media (max-width: 760px)" in html, "mobile breakpoint missing"

    def test_metric_row_is_grid_not_clipping_flex(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            html = _render_explorer_full(d)
        # A1: the three metric cards live in a grid of equal min-0 tracks, so the
        # third (FD) card can never be clipped off the right edge.
        assert ".metric-row {{ display: grid".replace("{{", "{") in html
        assert "repeat(3, minmax(0, 1fr))" in html

    def test_graphics_row_donut_and_flow_side_by_side(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            html = _render_explorer_full(d)
        assert 'id="graphics-row"' in html
        assert ".graphics-row" in html


class TestExploreNoEmoji:
    def test_no_chrome_emoji(self) -> None:
        # E2: explicit codepoint denylist of the three replaced emoji. NOT a
        # property/range check — ▶ ■ → ↗ … — are legitimate non-emoji glyphs.
        with tempfile.TemporaryDirectory() as d:
            html = _render_explorer_full(d)
        for cp, name in ((0x2600, "sun"), (0x1F319, "moon"), (0x1F4CC, "pin")):
            assert chr(cp) not in html, f"chrome still contains the {name} emoji U+{cp:04X}"

    def test_chrome_uses_svg_icons(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            html = _render_explorer_full(d)
        assert 'id="theme-ico"' in html, "theme toggle should be an SVG icon, not an emoji"
        assert 'id="print-btn"' in html


class TestExploreDefaultView:
    def test_defaults_to_first_modeled_scenario(self) -> None:
        # The default landing index is firstModeledIdx(), not a hardcoded 0.
        with tempfile.TemporaryDirectory() as d:
            html = _render_explorer_full(d)
        app = re.findall(r"<script>(.*?)</script>", html, re.DOTALL)[-1]
        assert "function firstModeledIdx" in app
        assert "selectScenario(firstModeledIdx())" in app
        assert "selectScenario(0)" not in app, "default must not hardcode scenario 0"


class TestExplorePlainLanguageFlow:
    def test_flow_renamed_no_sankey_jargon(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            html = _render_explorer_full(d)
        assert "Where your ownership went" in html, "flow should use plain language"
        assert "Dilution flow" not in html, "jargon heading 'Dilution flow' should be gone"

    def test_flow_keeps_transition_helper_and_path_class(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            app = re.findall(r"<script>(.*?)</script>", _render_explorer_full(d), re.DOTALL)[-1]
        assert "function setSankeyHTML" in app and "setSankeyHTML(container" in app
        assert "sankey-path" in app


class TestExploreContainedSlider:
    def _with_sweep(self, d: str) -> str:
        _make_fixture_dir(d)
        _write_priced_round_base(d)
        _run("sweep.py", ["--dir", d, "--run-id", "rid1", "-o", os.path.join(d, "sweep.json")])
        out = os.path.join(d, "explorer.html")
        rc, _, err = _run("explore.py", ["--dir", d, "-o", out])
        assert rc == 0, err
        with open(out, encoding="utf-8") as f:
            return f.read()

    def test_modeled_state_and_reset_control(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            html = self._with_sweep(d)
        assert 'id="sweep-reset"' in html, "reset-to-scenario control missing"
        app = re.findall(r"<script>(.*?)</script>", html, re.DOTALL)[-1]
        assert "function enterModeled" in app and "function exitModeled" in app
        assert "enterModeled()" in app, "a slider drag must mark the cards modeled"

    def test_slider_gated_to_sweep_base_scenario(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            app = re.findall(r"<script>(.*?)</script>", self._with_sweep(d), re.DOTALL)[-1]
        assert "function _isSweepBase" in app
        assert "base_scenario_id" in app, "sweep payload must carry the base scenario id"


class TestExploreCounselRail:
    def test_header_counsel_cue(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            html = _render_explorer_full(d)
        assert 'id="counsel-cue"' in html
        app = re.findall(r"<script>(.*?)</script>", html, re.DOTALL)[-1]
        assert "function renderCounselCue" in app
        assert "for your lawyer" in app

    def test_relevance_tiers_present(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            app = re.findall(r"<script>(.*?)</script>", _render_explorer_full(d), re.DOTALL)[-1]
        assert "Applies here" in app and "Likely relevant" in app and "General" in app
        assert "function _counselTier" in app

    def test_rule_codes_behind_toggle_but_reachable(self) -> None:
        # B2: codes hidden by default behind one toggle, still present for counsel.
        with tempfile.TemporaryDirectory() as d:
            html = _render_explorer_full(d)
        assert "Show rule codes (for counsel)" in html
        assert ".counsel-code {{ display: none".replace("{{", "{") in html
        assert "codes-shown" in html, "toggle reveals codes via a class, not removal"


class TestExplorePrint:
    def test_print_button_and_media_query(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            html = _render_explorer_full(d)
        assert "@media print" in html
        app = re.findall(r"<script>(.*?)</script>", html, re.DOTALL)[-1]
        assert "window.print()" in app
        # print CSS must respect the [hidden] attribute so torn-down widgets
        # don't print empty.
        assert "[hidden] {{ display: none".replace("{{", "{") in html


class TestExploreDonutA11y:
    def test_aria_text_alternative(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            app = re.findall(r"<script>(.*?)</script>", _render_explorer_full(d), re.DOTALL)[-1]
        assert "function renderDonutSummary" in app
        assert 'setAttribute("aria-label"' in app, "donut needs a text alternative"

    def test_pattern_fills_with_headless_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            app = re.findall(r"<script>(.*?)</script>", _render_explorer_full(d), re.DOTALL)[-1]
        assert "function _wedgeFill" in app and "function _wedgePattern" in app
        assert 'typeof document.createElement !== "function"' in app, (
            "pattern builder must fall back to solid color under the headless shim"
        )
        # The pattern fill must not reintroduce a raw PALETTE[cat] lookup on _pct keys.
        assert "_wedgeFill" in app and "PALETTE[cat]" not in app


class TestExploreWalkthroughControls:
    def test_prev_next_pause_controls(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            html = _render_explorer_full(d)
        for el in ('id="wt-prev"', 'id="wt-next"', 'id="wt-playpause"'):
            assert el in html, f"walkthrough control {el} missing"
        app = re.findall(r"<script>(.*?)</script>", html, re.DOTALL)[-1]
        assert "function _wtStep" in app and "function _wtPlayPause" in app

    def test_walkthrough_counsel_copy_preserved(self) -> None:
        # The verbatim counsel copy that the zero/plural test pins must stay intact.
        with tempfile.TemporaryDirectory() as d:
            app = re.findall(r"<script>(.*?)</script>", _render_explorer_full(d), re.DOTALL)[-1]
        assert "No counsel-review items were flagged" in app
        assert 'nCounsel === 1 ? "" : "s"' in app


class TestExploreCompareView:
    def test_compare_markup_and_functions(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            html = _render_explorer_full(d)
        assert 'id="compare-toggle"' in html, "Compare button missing"
        assert 'id="compare-view"' in html and 'id="compare-grid"' in html
        app = re.findall(r"<script>(.*?)</script>", html, re.DOTALL)[-1]
        assert "function renderCompare" in app and "function toggleCompare" in app
        assert "cmp-donut-a" in app and "cmp-donut-b" in app

    def test_chart_registry_replaces_single_global(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            app = re.findall(r"<script>(.*?)</script>", _render_explorer_full(d), re.DOTALL)[-1]
        assert "const _charts" in app and "function _destroyChart" in app
        # The single-global must be fully gone so two donuts can coexist.
        assert "_chartInstance" not in app, "the single shared chart instance must be gone"

    def test_compare_runs_headless_with_two_donuts(self) -> None:
        node = shutil.which("node")
        if node is None:
            pytest.skip("node not available; skipping compare headless smoke")
        with tempfile.TemporaryDirectory() as d:
            _make_fixture_dir(d)
            scenarios = {
                "scenarios": [
                    _full_scenario("p1", "Base case", 0.50),
                    _full_scenario("p2", "Higher pre-money", 0.58),
                ],
                "metadata": {"run_id": "rid1"},
            }
            with open(os.path.join(d, "scenarios.json"), "w", encoding="utf-8") as f:
                json.dump(scenarios, f)
            out = os.path.join(d, "explorer.html")
            rc, _, err = _run("explore.py", ["--dir", d, "-o", out])
            assert rc == 0, err
            with open(out, encoding="utf-8") as f:
                app = re.findall(r"<script>(.*?)</script>", f.read(), re.DOTALL)[-1]
            runner = (
                _DOM_SHIM
                + "\n"
                + app
                + "\ntoggleCompare();"  # enter compare → A shown, B is a pick-one placeholder
                + "\nconst _g = document.getElementById('compare-grid').innerHTML || '';"
                + "\nif (!_g.length) throw new Error('compare-grid not populated');"
                + "\nif (!_charts['cmp-donut-a']) throw new Error('A donut must render on entry');"
                + "\nif (_charts['cmp-donut-b']) throw new Error('B must stay empty until the user picks');"
                + "\nconst _b = [0,1].find(i => i !== _activeIdx);"
                + "\nonPillClick(_b);"  # pick B → second donut renders
                + "\nif (!_charts['cmp-donut-a'] || !_charts['cmp-donut-b'])"
                + "\n  throw new Error('both compare donuts must register once B is picked');"
                + "\nif (_charts['cmp-donut-a'] === _charts['cmp-donut-b'])"
                + "\n  throw new Error('two distinct chart instances required');"
                + "\ntoggleCompare();"  # exit → tears the compare donuts down
                + "\nif (_charts['cmp-donut-a'] || _charts['cmp-donut-b'])"
                + "\n  throw new Error('compare donuts must be torn down on exit');"
                + "\nconsole.log('OK_COMPARE');\n"
            )
            js_path = os.path.join(d, "runner.js")
            with open(js_path, "w", encoding="utf-8") as f:
                f.write(runner)
            res = subprocess.run([node, js_path], capture_output=True, text=True)
        assert res.returncode == 0 and "OK_COMPARE" in res.stdout, f"compare view threw at runtime:\n{res.stderr}"


class TestExploreHeadlessBehavior:
    """Behavioral (not string-presence) checks enabled by the stateful DOM shim:
    real classList membership + dispatched click handlers."""

    def _sweep_app(self, d: str) -> str:
        _make_fixture_dir(d)
        _write_priced_round_base(d)
        _run("sweep.py", ["--dir", d, "--run-id", "rid1", "-o", os.path.join(d, "sweep.json")])
        out = os.path.join(d, "explorer.html")
        rc, _, err = _run("explore.py", ["--dir", d, "-o", out])
        assert rc == 0, err
        with open(out, encoding="utf-8") as f:
            return re.findall(r"<script>(.*?)</script>", f.read(), re.DOTALL)[-1]

    def _node(self, runner: str, d: str) -> subprocess.CompletedProcess:
        js_path = os.path.join(d, "runner.js")
        with open(js_path, "w", encoding="utf-8") as f:
            f.write(runner)
        return subprocess.run([shutil.which("node"), js_path], capture_output=True, text=True)

    def test_modeled_marker_set_on_drag_and_cleared_on_reset(self) -> None:
        if shutil.which("node") is None:
            pytest.skip("node not available")
        with tempfile.TemporaryDirectory() as d:
            app = self._sweep_app(d)
            runner = (
                _DOM_SHIM
                + "\n"
                + app
                + "\napplySweepFrame(0);"  # a drag opts into the what-if
                + "\nif (!document.getElementById('metric-row').classList.contains('modeled'))"
                + "\n  throw new Error('metric cards must be marked modeled during a what-if');"
                + "\nif (document.getElementById('sweep-reset').classList.contains('invisible'))"
                + "\n  throw new Error('Reset control must be visible while modeled');"
                + "\ndocument.getElementById('sweep-reset').click();"  # reset → selectScenario(active)
                + "\nif (document.getElementById('metric-row').classList.contains('modeled'))"
                + "\n  throw new Error('modeled state must clear on reset');"
                + "\nconsole.log('OK_MODELED');\n"
            )
            res = self._node(runner, d)
        assert res.returncode == 0 and "OK_MODELED" in res.stdout, res.stderr

    def test_donut_aria_regenerates_on_drag(self) -> None:
        if shutil.which("node") is None:
            pytest.skip("node not available")
        with tempfile.TemporaryDirectory() as d:
            app = self._sweep_app(d)
            runner = (
                _DOM_SHIM
                + "\n"
                + app
                + "\napplySweepFrame(0);"
                + "\nconst _a0 = document.getElementById('donut-chart').getAttribute('aria-label');"
                + "\napplySweepFrame(DATA.sweep.frames.length - 1);"
                + "\nconst _a1 = document.getElementById('donut-chart').getAttribute('aria-label');"
                + "\nif (!_a0 || !_a1) throw new Error('donut aria-label must be set on each frame');"
                + "\nif (_a0 === _a1) throw new Error('donut aria-label must update as the what-if changes');"
                + "\nconsole.log('OK_ARIA');\n"
            )
            res = self._node(runner, d)
        assert res.returncode == 0 and "OK_ARIA" in res.stdout, res.stderr

    def test_walkthrough_pause_and_step(self) -> None:
        if shutil.which("node") is None:
            pytest.skip("node not available")
        with tempfile.TemporaryDirectory() as d:
            app = self._sweep_app(d)
            # Stub setTimeout so auto-advance doesn't run the tour to completion;
            # we drive the state machine by hand to verify pause/step.
            runner = (
                _DOM_SHIM
                + "\nglobal.setTimeout = function () { return 0; };\n"
                + app
                + "\nstartWalkthrough();"
                + "\nif (_wtState !== 'playing') throw new Error('walkthrough should start playing');"
                + "\n_wtPlayPause();"
                + "\nif (_wtState !== 'paused') throw new Error('play-pause should pause');"
                + "\nconst _f = _wtFrame; _wtStep(1);"
                + "\nif (_wtFrame !== _f + 1) throw new Error('next should advance one frame');"
                + "\n_wtStep(-1);"
                + "\nif (_wtFrame !== _f) throw new Error('prev should step back one frame');"
                + "\nstopWalkthrough();"
                + "\nif (_wtState !== 'idle') throw new Error('end should return to idle');"
                + "\nconsole.log('OK_WALK');\n"
            )
            res = self._node(runner, d)
        assert res.returncode == 0 and "OK_WALK" in res.stdout, res.stderr


class TestExploreBlockerDemotion:
    def test_blocker_leads_with_remedy_not_code(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            app = re.findall(r"<script>(.*?)</script>", _render_explorer_full(d), re.DOTALL)[-1]
        # The remedy is the first thing in the blocker; the raw code sits on a
        # muted secondary line, never leading.
        assert 'class="blocker">${escape(b.remedy)}' in app, "blocker must lead with the remedy"
        assert '<div class="blocker"><code>' not in app, "raw code must not lead the blocker"
        assert "blocker-code" in app, "code is demoted to a secondary line, still present"


class TestExploreDonutResponsive:
    def test_donut_canvas_has_max_width(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            html = _render_explorer_full(d)
        assert "max-width: 100%" in html, "donut canvas must be able to shrink below 200px"
        assert ".donut-wrap" not in html, "dead .donut-wrap CSS should be removed"


class TestExploreDefaultViewBehavior:
    def test_default_skips_structure_only_scenario_headless(self) -> None:
        node = shutil.which("node")
        if node is None:
            pytest.skip("node not available")
        with tempfile.TemporaryDirectory() as d:
            _make_fixture_dir(d)
            structural = {
                "scenario_id": "cap_today",
                "label": "Cap-implied today",
                "type": "safe_conversion",
                "parameters": {},
                "computed_outputs": {"completeness": "structural_only", "cap_implied_only": True, "blockers": []},
            }
            scenarios = {
                "scenarios": [structural, _full_scenario("p1", "Series A", 0.55)],
                "metadata": {"run_id": "rid1"},
            }
            with open(os.path.join(d, "scenarios.json"), "w", encoding="utf-8") as f:
                json.dump(scenarios, f)
            out = os.path.join(d, "explorer.html")
            rc, _, err = _run("explore.py", ["--dir", d, "-o", out])
            assert rc == 0, err
            with open(out, encoding="utf-8") as f:
                app = re.findall(r"<script>(.*?)</script>", f.read(), re.DOTALL)[-1]
            runner = (
                _DOM_SHIM
                + "\n"
                + app
                + "\nif (_activeIdx !== 1)"
                + "\n  throw new Error('default must skip the structure-only scenario, landed on ' + _activeIdx);"
                + "\nconsole.log('OK_DEFAULT');\n"
            )
            js_path = os.path.join(d, "runner.js")
            with open(js_path, "w", encoding="utf-8") as f:
                f.write(runner)
            res = subprocess.run([node, js_path], capture_output=True, text=True)
        assert res.returncode == 0 and "OK_DEFAULT" in res.stdout, res.stderr


class TestExploreMockFidelity:
    """The shipped explorer should match the approved 'Improved' design mock on
    the visible details: donut center overlay, metric sub-captions, the compare
    Dilution row + greener winning column, constant-scale flow, scenario status
    dots + B badge, the structure-only CTA, legend share counts, slider end
    labels, and the cap-table-level counsel intro."""

    def test_donut_and_metric_details(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            html = _render_explorer_full(d)
        assert 'id="donut-center-val"' in html and "founders" in html, "donut hole needs a founder% overlay"
        assert "what new investors pay" in html and "fully diluted total" in html, "metric sub-captions missing"
        app = re.findall(r"<script>(.*?)</script>", html, re.DOTALL)[-1]
        assert "function _setDonutCenter" in app

    def test_compare_dilution_greener_and_center(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            html = _render_explorer_full(d)
        assert "The greener column keeps more" in html, "compare subtitle should match the mock"
        assert ".compare-card.better" in html, "winning column must tint greener"
        app = re.findall(r"<script>(.*?)</script>", html, re.DOTALL)[-1]
        assert '_cmpRow("Dilution"' in app, "compare card needs the Dilution row"
        assert "cmp-center" in app, "compare donuts need a center % overlay"

    def test_flow_uses_constant_reference(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            app = re.findall(r"<script>(.*?)</script>", _render_explorer_full(d), re.DOTALL)[-1]
        # The Before stack must stay a constant height across frames, so the
        # scale divides by a fixed reference, not the per-frame post-round total.
        assert "_FLOW_REF" in app
        assert "innerH / postFd" not in app, "flow must not scale per-frame by postFd"

    def test_scenario_pills_have_status_and_b_badge(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            html = _render_explorer_full(d)
        app = re.findall(r"<script>(.*?)</script>", html, re.DOTALL)[-1]
        assert "function _scenarioStatus" in app
        assert "pill-dot" in app and 'class="b-badge"' in app, "pills need a status dot + compare B badge"
        assert ".scenario-pill.pinned .b-badge" in html, "B badge shows on the pinned compare target"

    def test_legend_shows_per_class_shares(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            app = re.findall(r"<script>(.*?)</script>", _render_explorer_full(d), re.DOTALL)[-1]
        assert "fmtShares(frac * fd)" in app, "legend rows should carry the per-class share count"

    def test_counsel_intro_is_cap_table_level(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            app = re.findall(r"<script>(.*?)</script>", _render_explorer_full(d), re.DOTALL)[-1]
        assert "most relevant to your cap table first" in app

    def test_slider_end_labels_and_reset_visibility(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            html = _render_explorer_full(d)
        assert 'id="sweep-end-lo"' in html and 'id="sweep-end-hi"' in html, "slider needs min/max end labels"
        assert ".sweep-reset.invisible" in html, "reset toggles via visibility, not display"

    def test_structure_only_cta_headless(self) -> None:
        node = shutil.which("node")
        if node is None:
            pytest.skip("node not available")
        with tempfile.TemporaryDirectory() as d:
            _make_fixture_dir(d)
            structural = {
                "scenario_id": "cap_today",
                "label": "Cap-implied today",
                "type": "safe_conversion",
                "parameters": {},
                "computed_outputs": {"completeness": "structural_only", "cap_implied_only": True, "blockers": []},
            }
            scenarios = {
                "scenarios": [structural, _full_scenario("p1", "Series A", 0.55)],
                "metadata": {"run_id": "rid1"},
            }
            with open(os.path.join(d, "scenarios.json"), "w", encoding="utf-8") as f:
                json.dump(scenarios, f)
            out = os.path.join(d, "explorer.html")
            rc, _, err = _run("explore.py", ["--dir", d, "-o", out])
            assert rc == 0, err
            with open(out, encoding="utf-8") as f:
                app = re.findall(r"<script>(.*?)</script>", f.read(), re.DOTALL)[-1]
            runner = (
                _DOM_SHIM
                + "\n"
                + app
                + "\nselectScenario(0);"  # the structure-only scenario
                + "\nif (document.getElementById('scenario-variable').innerHTML.indexOf('No priced round yet') < 0)"
                + "\n  throw new Error('structure-only scenario must offer the View-a-modeled-round CTA');"
                + "\ndocument.getElementById('go-modeled').click();"
                + "\nif (_activeIdx !== 1) throw new Error('CTA must jump to the modeled scenario');"
                + "\nconsole.log('OK_CTA');\n"
            )
            js_path = os.path.join(d, "runner.js")
            with open(js_path, "w", encoding="utf-8") as f:
                f.write(runner)
            res = subprocess.run([node, js_path], capture_output=True, text=True)
        assert res.returncode == 0 and "OK_CTA" in res.stdout, res.stderr


class TestExploreCompareSetB:
    def test_no_pin_button_or_banner(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            html = _render_explorer_full(d)
        # The pin button + delta banner were retired in favor of click-to-set-B.
        assert 'id="pin-btn"' not in html and 'id="compare-banner"' not in html
        app = re.findall(r"<script>(.*?)</script>", html, re.DOTALL)[-1]
        assert "function onPillClick" in app

    def test_click_in_compare_mode_sets_b_not_a(self) -> None:
        node = shutil.which("node")
        if node is None:
            pytest.skip("node not available")
        with tempfile.TemporaryDirectory() as d:
            _make_fixture_dir(d)
            scenarios = {
                "scenarios": [
                    _full_scenario("p1", "Series A", 0.50),
                    _full_scenario("p2", "Series A — high", 0.58),
                    _full_scenario("p3", "Series A — low", 0.44),
                ],
                "metadata": {"run_id": "rid1"},
            }
            with open(os.path.join(d, "scenarios.json"), "w", encoding="utf-8") as f:
                json.dump(scenarios, f)
            out = os.path.join(d, "explorer.html")
            rc, _, err = _run("explore.py", ["--dir", d, "-o", out])
            assert rc == 0, err
            with open(out, encoding="utf-8") as f:
                app = re.findall(r"<script>(.*?)</script>", f.read(), re.DOTALL)[-1]
            runner = (
                _DOM_SHIM
                + "\n"
                + app
                + "\nconst _a = _activeIdx;"
                + "\ntoggleCompare();"  # enter compare → B auto-seeded
                + "\nif (!_compareMode) throw new Error('compare mode should be on');"
                + "\nconst _other = [0,1,2].find(i => i !== _a);"
                + "\nonPillClick(_other);"  # clicking a scenario sets it as B
                + "\nif (_compareIdx !== _other) throw new Error('click in compare mode must set B');"
                + "\nif (_activeIdx !== _a)"
                + "\n  throw new Error('active scenario (A) must not change on a compare-mode click');"
                + "\nconsole.log('OK_SETB');\n"
            )
            js_path = os.path.join(d, "runner.js")
            with open(js_path, "w", encoding="utf-8") as f:
                f.write(runner)
            res = subprocess.run([node, js_path], capture_output=True, text=True)
        assert res.returncode == 0 and "OK_SETB" in res.stdout, res.stderr


class TestExploreSliderHomeFrame:
    """Returning the slider to the scenario's own pre-money clears the modeled
    what-if; any other frame keeps it."""

    def _sweep_app(self, d: str) -> str:
        _make_fixture_dir(d)
        _write_priced_round_base(d)
        _run("sweep.py", ["--dir", d, "--run-id", "rid1", "-o", os.path.join(d, "sweep.json")])
        out = os.path.join(d, "explorer.html")
        rc, _, err = _run("explore.py", ["--dir", d, "-o", out])
        assert rc == 0, err
        with open(out, encoding="utf-8") as f:
            return re.findall(r"<script>(.*?)</script>", f.read(), re.DOTALL)[-1]

    def test_home_frame_clears_modeled_other_frames_set_it(self) -> None:
        node = shutil.which("node")
        if node is None:
            pytest.skip("node not available")
        with tempfile.TemporaryDirectory() as d:
            app = self._sweep_app(d)
            runner = (
                _DOM_SHIM
                + "\n"
                + app
                + "\nconst _home = _sweepHomeIdx();"
                + "\nconst _away = _home === 0 ? DATA.sweep.frames.length - 1 : 0;"
                + "\nconst _mr = document.getElementById('metric-row');"
                + "\napplySweepFrame(_away);"  # a real what-if
                + "\nif (!_mr.classList.contains('modeled'))"
                + "\n  throw new Error('a non-home frame must mark the cards modeled');"
                + "\napplySweepFrame(_home);"  # back to the scenario's own pre-money
                + "\nif (_mr.classList.contains('modeled'))"
                + "\n  throw new Error('returning to the home frame must clear the modeled state');"
                + "\nconsole.log('OK_HOME');\n"
            )
            js_path = os.path.join(d, "runner.js")
            with open(js_path, "w", encoding="utf-8") as f:
                f.write(runner)
            res = subprocess.run([node, js_path], capture_output=True, text=True)
        assert res.returncode == 0 and "OK_HOME" in res.stdout, res.stderr
