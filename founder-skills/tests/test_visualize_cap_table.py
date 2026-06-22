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
  return {
    id, _html: "", hidden: false, textContent: "", style: {}, dataset: {},
    classList: { toggle() {}, add() {}, remove() {}, contains() { return false; } },
    addEventListener() {}, append() {}, querySelectorAll() { return []; },
    setAttribute() {}, getAttribute() { return null; },
    set innerHTML(v) { this._html = v; if (this.id) _byId[this.id] = this; },
    get innerHTML() { return this._html; },
  };
}
global.document = {
  getElementById(id) { return _byId[id] || (_byId[id] = mkEl(id)); },
  querySelectorAll() { return []; },
  addEventListener() {},
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
        assert "DONUT_ORDER" in app and "_chartInstance.update(" in app, (
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
        assert "function slideIn" in app, "card mount animation helper (P3) missing"
        assert app.count("slideIn(") >= 3, "slideIn must be applied to the impact callout and the compare banner."


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
