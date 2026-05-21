"""Regression tests for cap-table HTML visualization (visualize.py + explore.py).

Focus: the design §10 security contract — every user-controlled string MUST be
HTML-escaped, and explorer.html's inline JSON data block MUST escape `</` to
prevent `</script>` breakout. These tests inject XSS payloads into fixture
inputs/instruments and verify outputs are inert.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from typing import Any

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPTS = os.path.join(_REPO, "founder-skills", "skills", "cap-table", "scripts")

sys.path.insert(0, SCRIPTS)
import cap_state as cap_state_mod  # type: ignore[import-not-found]  # noqa: E402


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
