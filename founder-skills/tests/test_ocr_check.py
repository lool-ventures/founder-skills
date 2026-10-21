"""deck-review Step 3.95's check (`ocr_check.py`): the numeral rule, the statuses and the refusals.

The rule's cases and named residuals are the ones the OCR plan settled (3.1-F, 3.2, 3.3); a residual is pinned
as a residual so a change to it is a decision, not drift.
"""

from __future__ import annotations

import inspect
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "deck-review" / "scripts"
RUN = "20261021T090000Z"


sys.path[:0] = [str(SCRIPTS)]
import _ocr_scope as SCOPE  # type: ignore[import-not-found]  # noqa: E402
import ocr_check as OC  # type: ignore[import-not-found]  # noqa: E402
import reconcile as RECONCILE  # type: ignore[import-not-found]  # noqa: E402


@pytest.mark.parametrize(
    ("raw", "page", "want"),
    [
        # Space-grouped neighbours: the line reads one long number, each word on its own reads the figure.
        ("370", "ARR 130 370 590", True),
        ("120", "Since 2019 120 customers", True),
        ("120", "Since 2019, 120 customers", True),
        ("450", "Clients: 8, 450 seats", True),
        ("123", "Phases 1, 2, 3", False),
        ("2", "Phases 1, 2, 3", True),
        # A range's shared suffix and percent apply to both ends.
        ("10-15%", "Margin 10-15%", True),
        ("$1.2M", "1.200.000", False),
        ("30 bps", "spread of 30 bps", True),
        ("$20×10⁶", "raised $20M", True),
        # Glued suffixes: a suffix run into the next word answers either reading, never a wrong scale.
        ("$493K", "GMV 493Kin 2024", True),
        ("$493M", "GMV 493K", False),
        ("$14M", "runway 14 Months", False),
        ("14 months", "runway 14 Months", True),
        ("1.5", "grew to 1.5 Million users", False),
        ("2", "about $2 M, mostly", False),
        ("75%", "Gross margin: 75 %", True),
        ("75%", "Gross margin: 75", False),
        ("three", "we have three pilots", True),
        ("one", "money moves", False),
        ("3", "three pilots", True),
    ],
)
def test_the_numeral_rule(raw: str, page: str, want: bool) -> None:
    assert OC.found(raw, page) is want


@pytest.mark.parametrize(
    ("raw", "page", "want"),
    [
        ("$14M", "runway 14Months", True),  # a glued "Months" reads as M: accepted, lowers nothing called wrong
        ("1.5", "$1.5Millionin", True),
        ("$460K", "Clients: 7, 460 K", False),  # the guarded mantissa reads "7, 460"
        # Sign, currency and a multiple's `x` are not compared; a space-grouped neighbour joins the mantissa.
        ("-5%", "fell 5%", True),
        ("\u20ac3M", "raised $3M", True),
        ("3x", "grew 3 times", True),
        ("12,500", "Year 12 500 customers", True),
        ("40%", "40 percent", False),
    ],
)
def test_the_named_residuals(raw: str, page: str, want: bool) -> None:
    assert OC.found(raw, page) is want


def test_page_patterns_are_built_from_the_shared_grammar() -> None:
    for pattern in (OC.GLUED_RE, OC.GLUED_RANGE_RE):
        assert RECONCILE._MANTISSA in pattern.pattern and RECONCILE._SCALE_ALT in pattern.pattern
        assert pattern.flags & re.I
    for name in ("numeral_form", "spelled_number", "strip_group_marks"):
        assert len(inspect.signature(getattr(RECONCILE, name)).parameters) == 1, name
    assert SCOPE.DATE == RECONCILE.DATE


# --- the CLI ---------------------------------------------------------------------------------------------------


def _review(tmp: Path, pages_source: str = "{1: inventory, 2: inventory}", relations: Any = None) -> Path:
    rv = tmp / "review"
    (rv / "handoff" / "ocr").mkdir(parents=True)
    body = "## Slide 1\n\nTitle\n\n## Slide 2\n\nARR: $1.2M\n"
    front = f"---\nrun_id: {RUN}\nsource: inventory\npages_source: {pages_source}\ndeck_sha256: abc\n---\n"
    (rv / "deck_text.md").write_text(front + body)
    figs = [
        {"id": f"f{i}", "raw": raw, "unit_kind": "money", "slide": 2}
        for i, raw in enumerate(["$1.2M", "$100K", "$900K", "$40K"])
    ] + [{"id": "d", "raw": "2024", "unit_kind": "date", "slide": 2}]
    (rv / "ledger.json").write_text(json.dumps({"figures": figs, "metadata": {"run_id": RUN}}))
    if relations is None:
        relations = [{"operands": ["f0", "f1", "d"], "expected_id": "f2"}, {"operands": ["f3"]}]
    (rv / "reconciliation.json").write_text(
        json.dumps({"status": "ok", "relations": relations, "metadata": {"run_id": RUN}})
    )
    return rv


def _receipt(rv: Path, page_text: str | None = "ARR $1.2M MRR $100K GP $900K", **over: Any) -> None:
    receipt: dict[str, Any] = {"run_id": RUN, "complete": True, "status": "read", "scope_pages": [2]}
    receipt["deck_sha256"] = "abc"  # the deck text's
    receipt["pages"] = {"2": {"kind": "ocr" if page_text is not None else "failed", "attempts": 1}}
    receipt.update(over)
    (rv / "handoff" / "ocr" / "receipt.json").write_text(json.dumps(receipt))
    if page_text is not None:
        (rv / "handoff" / "ocr" / "p2.txt").write_text(page_text)


def _run(rv: Path) -> tuple[int, dict[str, Any]]:
    proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "ocr_check.py"),
            "--ledger",
            str(rv / "ledger.json"),
            "--reconciliation",
            str(rv / "reconciliation.json"),
            "--deck-text",
            str(rv / "deck_text.md"),
            "--ocr-dir",
            str(rv / "handoff" / "ocr"),
            "--run-id",
            RUN,
            "-o",
            str(rv / "ocr_check.json"),
        ],
        capture_output=True,
        text=True,
    )
    return proc.returncode, json.loads(proc.stdout.splitlines()[-1])


def test_checked_counts_the_relations_figures_and_leaves_out_dates(tmp_path: Path) -> None:
    rv = _review(tmp_path)
    _receipt(rv)
    rc, out = _run(rv)
    assert rc == 0, out
    written = json.loads((rv / "ocr_check.json").read_text())
    assert written["status"] == "checked"
    assert written["counts"] == {"in_scope": 4, "checked": 4, "found": 3, "not_found": 1, "not_checked": 0}
    assert written["pages_machine_read"] == [2]
    assert set(written["metadata"]) == {"run_id", "ocr_receipt_sha256", "deck_text_sha256", "reconciliation_sha256"}
    assert "figures" not in written, "per-figure results stay in the hand-off folder"
    figures = json.loads((rv / "handoff" / "ocr" / "figures.json").read_text())["figures"]
    assert [f["id"] for f in figures] == ["f0", "f1", "f2", "f3"]


def test_the_cap_the_read_used_is_the_cap_the_check_uses(tmp_path: Path) -> None:
    rv = _review(tmp_path)
    _receipt(rv, scope_pages=[], max_pages=0, pages={"2": {"kind": "not_read", "attempts": 0}})
    assert _run(rv)[0] == 0
    assert json.loads((rv / "ocr_check.json").read_text())["status"] == "none_read"


def test_low_match_hides_the_count_at_the_boundary(tmp_path: Path) -> None:
    rv = _review(tmp_path)
    _receipt(rv, page_text="ARR $1.2M")  # 1 of 4 found
    assert _run(rv)[0] == 0
    assert json.loads((rv / "ocr_check.json").read_text())["status"] == "low_match"
    _receipt(rv, page_text="ARR $1.2M MRR $100K")  # 2 of 4: exactly half is not under half
    assert _run(rv)[0] == 0
    assert json.loads((rv / "ocr_check.json").read_text())["status"] == "checked"


def test_a_failed_page_is_none_read(tmp_path: Path) -> None:
    rv = _review(tmp_path)
    _receipt(rv, page_text=None)
    assert _run(rv)[0] == 0
    written = json.loads((rv / "ocr_check.json").read_text())
    assert written["status"] == "none_read" and written["counts"]["not_checked"] == 4


def test_no_inventory_slide_in_scope_is_no_figures(tmp_path: Path) -> None:
    rv = _review(tmp_path, pages_source="{1: inventory, 2: extracted}")
    _receipt(rv, status="no_figures", scope_pages=[])
    assert _run(rv)[0] == 0
    assert json.loads((rv / "ocr_check.json").read_text())["status"] == "no_figures"


@pytest.mark.parametrize("reason", ["deck_mismatch", "page_count_mismatch", "no_inventory"])
def test_a_not_applicable_receipt_is_carried_with_its_reason(tmp_path: Path, reason: str) -> None:
    rv = _review(tmp_path)
    _receipt(rv, status="not_applicable", reason=reason)
    assert _run(rv)[0] == 0
    written = json.loads((rv / "ocr_check.json").read_text())
    assert (written["status"], written["reason"]) == ("not_applicable", reason)


def test_unavailable_is_carried(tmp_path: Path) -> None:
    rv = _review(tmp_path)
    _receipt(rv, status="unavailable", reason="no_ocr_tools")
    assert _run(rv)[0] == 0
    assert json.loads((rv / "ocr_check.json").read_text())["status"] == "unavailable"


@pytest.mark.parametrize(
    ("setup", "rc", "code"),
    [
        ("none", 2, "OCR_NOT_RUN"),
        ("incomplete", 2, "OCR_INCOMPLETE"),
        ("other_scope", 2, "OCR_INCOMPLETE"),
        ("other_deck", 2, "OCR_INCOMPLETE"),
        ("no_figures_then", 2, "OCR_INCOMPLETE"),
        ("other_run", 1, "OCR_OTHER_RUN"),
    ],
)
def test_refusals_leave_the_output_untouched(tmp_path: Path, setup: str, rc: int, code: str) -> None:
    rv = _review(tmp_path)
    if setup == "incomplete":
        _receipt(rv, complete=False)
    elif setup == "other_scope":
        _receipt(rv, scope_pages=[1, 2])
    elif setup == "other_run":
        _receipt(rv, run_id="20200101T000000Z")
    elif setup == "other_deck":
        _receipt(rv, deck_sha256="def")
    elif setup == "no_figures_then":  # read when the kept relations used no image slide; they now do
        _receipt(rv, status="no_figures", reason="no_figures", scope_pages=[])
    sentinel = rv / "ocr_check.json"
    sentinel.write_text("SENTINEL")
    got_rc, out = _run(rv)
    assert (got_rc, out["code"]) == (rc, code)
    assert "Step 3.95" in out["fix"]
    assert sentinel.read_text() == "SENTINEL"


def test_every_code_steps_3_95_and_4_print_is_in_the_host_contract() -> None:
    contract = json.loads((SCRIPTS.parents[2] / "data" / "host-contract.json").read_text())
    listed = json.dumps(contract)
    for script in ("deck_ocr.py", "ocr_check.py", "slide_reviews.py"):
        source = (SCRIPTS / script).read_text()
        codes = set(re.findall(r'"((?:OCR|DECK|LEDGER|RECONCILIATION|OUTPUT)_[A-Z_]+)"', source))
        assert codes, script
        missing = sorted(c for c in codes if f'"{c}"' not in listed)
        assert not missing, (script, missing)
