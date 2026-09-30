"""The option pool's sizing basis: one allow-list gate in the solver, reaching every entry point.

The solver computes `pre_money`, `post_money` and `post_money_increase`. Every other basis is refused
(`E_POOL_BASIS_NOT_MODELED`) or, for `post_money_excluding_converting_securities` with conversions present,
refused unless the founder chose the plain post-money reading (`E_POOL_BASIS_EXCLUDING_NOT_MODELED`). No
published source defines an excluding pool denominator, and `custom` carries no definition, so neither is
invented. Before this, an unknown basis crashed at every entry point and the refusal lived only in
run_scenario, so quick_assess and the priced-round CLI solved the excluding basis as plain post-money,
silently.
"""

from __future__ import annotations

import os
import re
import sys
from typing import Any

import pytest

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPTS = os.path.join(_REPO, "founder-skills", "skills", "cap-table", "scripts")
sys.path.insert(0, SCRIPTS)

import _warning_callouts as WC  # type: ignore[import-not-found]  # noqa: E402
import cap_state as cap_state_mod  # type: ignore[import-not-found]  # noqa: E402
import compose_report  # type: ignore[import-not-found]  # noqa: E402
import option_pool  # type: ignore[import-not-found]  # noqa: E402
import priced_round  # type: ignore[import-not-found]  # noqa: E402
import quick_assess  # type: ignore[import-not-found]  # noqa: E402
import rule_audit  # type: ignore[import-not-found]  # noqa: E402
import run_scenario  # type: ignore[import-not-found]  # noqa: E402

EXCL = "post_money_excluding_converting_securities"
CHOICE = "post_money_by_founder_choice"
NO_SWITCH = re.compile(r"\b(?:switch|change|set|use|re-?run)\b[^.]{0,40}\b(?:pre|post)[-_ ]money\b", re.I)
DIRECTION = re.compile(r"overstat|understat|conservativ", re.I)


def _inputs() -> dict[str, Any]:
    return {
        "company_name": "Foobar",
        "founders": [{"id": "f", "name": "Founders", "common_shares": 8_000_000, "share_class": "class_a"}],
        # `unallocated` is the input key cap_state reads into `available_for_grant`; the canonical name here
        # would be dropped silently and leave the existing pool at zero.
        "option_pool": {"authorized": 1_000_000, "issued": 400_000, "unallocated": 600_000},
        "metadata": {"run_id": "r"},
    }


def _safes(total: float, *, usable: bool = True) -> list[dict[str, Any]]:
    out = []
    for i in range(3 if total else 0):
        s: dict[str, Any] = {
            "id": f"s{i}",
            "investor_name": f"Investor {i}",
            "form": "yc_postmoney_cap",
            "post_money_valuation_cap": 12_000_000,
            "issuance_date": "2024-01-01",
        }
        if usable:
            s["purchase_amount"] = total / 3
        out.append(s)
    return out


def _state(safes: list[dict[str, Any]], *, existing_pool: int | None = None) -> dict[str, Any]:
    instruments = {"safes": safes, "convertible_notes": [], "metadata": {"run_id": "r"}}
    inputs = _inputs()
    if existing_pool is not None:
        inputs["option_pool"]["unallocated"] = existing_pool
    state: dict[str, Any] = cap_state_mod.build_cap_state(inputs, instruments)
    return state


def _solve(
    basis: str, safes: list[dict[str, Any]], target: float | None = 0.12, existing_pool: int | None = None, **extra: Any
) -> dict[str, Any]:
    out: dict[str, Any] = priced_round.solve_priced_round(
        cap_state=_state(safes, existing_pool=existing_pool),
        safes=safes,
        notes=[],
        pre_money=20_000_000,
        new_money=6_000_000,
        target_pool_percent=target,
        target_basis=basis,
        **extra,
    )
    return out


def _scenario(basis: str, safes: list[dict[str, Any]], *, kind: str = "priced_round", **params: Any) -> dict[str, Any]:
    p: dict[str, Any] = {"pre_money": 20_000_000, "new_money": 6_000_000, "target_pool_percent": 0.12}
    if kind == "safe_conversion":  # this path reaches the solver only through its priced-round keys
        p.update({"priced_round_pre_money": 20_000_000, "priced_round_new_money": 6_000_000})
    p["target_basis"] = basis
    p.update(params)
    instruments = {"safes": safes, "convertible_notes": [], "metadata": {"run_id": "r"}}
    req = {"scenario_id": "a", "type": kind, "parameters": p}
    out: dict[str, Any] = run_scenario.run_all_scenarios(
        inputs=_inputs(), instruments=instruments, cap_state=_state(safes), scenario_requests=[req]
    )[0]["computed_outputs"]
    return out


def _fast(basis: str, safes: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
    out: dict[str, Any] = quick_assess.quick_assess(
        company_name="Foobar",
        inputs=_inputs(),
        safes=safes,
        notes=[],
        pre_money=20_000_000,
        new_money=6_000_000,
        target_pool_percent=0.12,
        target_basis=basis,
        **extra,
    )
    return out


def _codes(result: dict[str, Any]) -> list[str]:
    return [str(b.get("code")) for b in result.get("blockers") or []]


def _warning_codes(result: dict[str, Any]) -> list[str]:
    return [str(w.get("code")) for w in result.get("warnings") or [] if isinstance(w, dict)]


# --- the allow-list: an unknown basis is refused, never a traceback, at every entry point -------------------


@pytest.mark.parametrize("basis", ["fully_diluted", "Custom", "post-money", ""])
def test_an_unknown_basis_is_refused_by_the_solver(basis: str) -> None:
    out = _solve(basis, _safes(3_000_000))
    assert _codes(out) == ["E_POOL_BASIS_NOT_MODELED"], out
    assert not (out.get("aggregate_ownership_by_class") or {}).get("founders_pct")


def test_an_unknown_basis_is_refused_by_run_scenario_on_both_solver_paths() -> None:
    for kind in ("priced_round", "safe_conversion"):
        out = _scenario("fully_diluted", _safes(3_000_000), kind=kind)
        assert _codes(out) == ["E_POOL_BASIS_NOT_MODELED"], (kind, out)


def test_an_unknown_basis_is_refused_by_fast_assess_and_rendered() -> None:
    out = _fast("fully_diluted", _safes(3_000_000))
    md = out["_report_md"]
    assert "E_POOL_BASIS_NOT_MODELED" in md
    # Both spellings: the line used to render the raw value with its underscores replaced, which a check for
    # the underscored form alone cannot see.
    for echoed in ("fully_diluted", "fully diluted"):
        assert echoed not in md.lower(), "a raw value we don't recognise is never echoed to the founder"
    assert "- Pool target: 12% (basis not modelled)" in md
    assert not out.get("headline_data"), "no ownership figures on a refused basis"


# --- custom: document-defined, never computed; the founder's stated answer is recorded and disclosed ----------


def test_custom_with_a_pool_target_is_refused_with_three_computable_answers() -> None:
    out = _solve("custom", _safes(3_000_000))
    assert _codes(out) == ["E_POOL_BASIS_NOT_MODELED"]
    remedy = out["blockers"][0]["remedy"]
    assert "before the new money" in remedy
    assert "counting the SAFE and note conversions" in remedy
    assert "not counting them" in remedy
    assert "stays unmodelled" in remedy
    assert not DIRECTION.search(remedy) and not NO_SWITCH.search(remedy), remedy


@pytest.mark.parametrize("target", [None, 0.0])
def test_custom_without_a_pool_target_changes_nothing(target: float | None) -> None:
    custom = _solve("custom", _safes(3_000_000), target=target)
    pre = _solve("pre_money", _safes(3_000_000), target=target)
    assert not custom.get("blockers")
    assert custom["aggregate_ownership_by_class"] == pre["aggregate_ownership_by_class"]


def test_custom_is_refused_on_the_run_scenario_and_fast_assess_paths() -> None:
    assert _codes(_scenario("custom", _safes(3_000_000))) == ["E_POOL_BASIS_NOT_MODELED"]
    assert _codes(_scenario("custom", _safes(3_000_000), kind="safe_conversion")) == ["E_POOL_BASIS_NOT_MODELED"]
    assert "E_POOL_BASIS_NOT_MODELED" in _fast("custom", _safes(3_000_000))["_report_md"]


def test_the_founders_stated_answer_for_custom_is_solved_and_disclosed() -> None:
    stated = _solve("custom", _safes(3_000_000), custom_basis_stated_by_founder="pre_money")
    pre = _solve("pre_money", _safes(3_000_000))
    assert not stated.get("blockers")
    assert stated["aggregate_ownership_by_class"] == pre["aggregate_ownership_by_class"]
    assert "W_CUSTOM_BASIS_STATED_BY_FOUNDER" in _warning_codes(stated)
    assert "W_CUSTOM_BASIS_STATED_BY_FOUNDER" not in _warning_codes(pre)


def test_a_founder_stating_the_excluding_reading_for_custom_reaches_the_excluding_gate() -> None:
    out = _solve("custom", _safes(3_000_000), custom_basis_stated_by_founder=EXCL)
    assert _codes(out) == ["E_POOL_BASIS_EXCLUDING_NOT_MODELED"]


def test_an_unrecognised_stated_answer_leaves_custom_refused() -> None:
    out = _solve("custom", _safes(3_000_000), custom_basis_stated_by_founder="custom")
    assert _codes(out) == ["E_POOL_BASIS_NOT_MODELED"]


# --- the excluding basis, gated in the solver (it used to be run_scenario only) ---------------------------------


def test_the_excluding_basis_is_refused_by_the_solver_directly() -> None:
    assert _codes(_solve(EXCL, _safes(3_000_000))) == ["E_POOL_BASIS_EXCLUDING_NOT_MODELED"]


def test_the_excluding_basis_is_refused_by_fast_assess() -> None:
    """Fast-assess called the solver directly and used to compute the basis as plain post-money."""
    out = _fast(EXCL, _safes(3_000_000))
    assert "E_POOL_BASIS_EXCLUDING_NOT_MODELED" in out["_report_md"]
    assert not out.get("headline_data")


def test_fast_assess_honours_the_founders_choice_and_shows_the_disclosure() -> None:
    chose = _fast(EXCL, _safes(3_000_000), excluding_basis_modeled_as=CHOICE)
    post = _fast("post_money", _safes(3_000_000))
    fp = "founder_impact"
    assert (
        chose["headline_data"][fp]["ownership_post_financing_pct"]
        == post["headline_data"][fp]["ownership_post_financing_pct"]
    )
    assert "W_EXCLUDING_BASIS_MODELED_AS_POST_MONEY" in chose.get("warnings", [])
    assert "counsel" in chose["_report_md"].lower()
    assert "W_EXCLUDING_BASIS_MODELED_AS_POST_MONEY" not in (post.get("warnings") or [])


def test_a_terms_only_safe_does_not_trigger_the_excluding_refusal() -> None:
    """The solver drops a SAFE with no usable purchase amount: it converts to nothing, so the two readings
    are the same number and there is nothing to refuse."""
    excl = _solve(EXCL, _safes(3_000_000, usable=False))
    post = _solve("post_money", _safes(3_000_000, usable=False))
    assert not excl.get("blockers")
    assert excl["aggregate_ownership_by_class"] == post["aggregate_ownership_by_class"]


@pytest.mark.parametrize("target", [None, 0.0])
def test_the_excluding_basis_without_a_pool_target_is_not_refused(target: float | None) -> None:
    assert not _solve(EXCL, _safes(3_000_000), target=target).get("blockers")


def test_the_founders_choice_survives_an_acquisition_round() -> None:
    out = _solve(EXCL, _safes(3_000_000), excluding_basis_modeled_as=CHOICE, acquisition={"consideration_pct": 0.1})
    assert not out.get("blockers"), out.get("blockers")
    assert "W_EXCLUDING_BASIS_MODELED_AS_POST_MONEY" in _warning_codes(out)


# --- the texts: no unsourced direction, no prescribed switch, clean founder text -------------------------------


def _founder_text() -> Any:
    sys.path.insert(0, os.path.join(_REPO, "founder-skills", "scripts"))
    try:
        import _founder_text  # type: ignore[import-not-found]
    finally:
        sys.path.pop(0)
    return _founder_text


def test_no_refusal_or_disclosure_claims_a_direction_nobody_has_sourced() -> None:
    ft = _founder_text()
    texts = [
        _solve(EXCL, _safes(3_000_000))["blockers"][0]["remedy"],
        _solve("custom", _safes(3_000_000))["blockers"][0]["remedy"],
        _solve("fully_diluted", _safes(3_000_000))["blockers"][0]["remedy"],
        WC._SOLVER_WARNING_PROSE["W_EXCLUDING_BASIS_MODELED_AS_POST_MONEY"],
        WC._SOLVER_WARNING_PROSE["W_CUSTOM_BASIS_STATED_BY_FOUNDER"],
    ]
    for text in texts:
        assert not DIRECTION.search(text), text
        assert not NO_SWITCH.search(text), text
        assert ft.scan(text) == {"enums": [], "filenames": []}, text


def test_the_disclosures_have_a_label_and_prose_on_the_shared_renderer() -> None:
    for code in ("W_EXCLUDING_BASIS_MODELED_AS_POST_MONEY", "W_CUSTOM_BASIS_STATED_BY_FOUNDER"):
        assert code in WC._SOLVER_WARNING_PROSE and code in WC._SOLVER_WARNING_LABELS
        rendered = "\n".join(WC.render_solver_warning_callouts([{"code": code, "severity": "high"}]))
        assert WC._SOLVER_WARNING_PROSE[code] in rendered


# --- option_pool refuses the bases it does not compute ---------------------------------------------------------


@pytest.mark.parametrize("basis", [EXCL, "custom"])
def test_required_topup_refuses_a_basis_it_does_not_compute(basis: str) -> None:
    with pytest.raises(ValueError, match="not modelled"):
        option_pool.required_topup(
            pre_topup_fully_diluted_shares=10_000_000,
            existing_unallocated_pool=500_000,
            target_pool_percent=0.10,
            new_money_shares=1_000_000,
            target_basis=basis,
        )


# --- review follow-ups: the solved basis is what the founder reads, and a disclosure qualifies only figures ----


@pytest.mark.parametrize(
    ("basis", "extra", "safes_total", "label"),
    [
        (
            "custom",
            {"custom_basis_stated_by_founder": "pre_money"},
            3_000_000,
            "measured against the fully diluted share count before the round, from your answer",
        ),
        (
            # "from your answer" qualifies the measure, so it comes before the term sheet's wording, never after.
            "custom",
            {"custom_basis_stated_by_founder": "post_money"},
            3_000_000,
            "measured against the fully diluted share count after the round, from your answer; a term sheet "
            'writes this as a "12% post-money pool"',
        ),
        (
            EXCL,
            {"excluding_basis_modeled_as": CHOICE},
            3_000_000,
            "measured with the conversion shares, at your choice",
        ),
        (
            EXCL,
            {},
            0,
            "measured against the fully diluted share count after the round; a term sheet writes this as a "
            '"12% post-money pool"',
        ),
        ("pre_money", {}, 3_000_000, "measured against the fully diluted share count before the round"),
    ],
)
def test_fast_assess_names_the_basis_it_solved_not_the_one_requested(
    basis: str, extra: dict[str, Any], safes_total: float, label: str
) -> None:
    md = _fast(basis, _safes(safes_total), **extra)["_report_md"]
    assert f"- Pool target: 12% ({label})" in md, md
    # The quick answer names the measure the way the full report does: never an old basis label, never "pre-money"
    # beside "pool". ("post-money SAFE" is the instrument's name and stays.)
    assert not re.search(r"\b(?:pre|post)-money basis\b|\bplain post-money\b", md), md
    assert not re.search(r"\bpre-money\s+(?:option\s+)?pool\b|\bpool\b[^.\n]{0,40}\bpre-money\b", md, re.I), md


def test_a_disclosure_never_rides_a_scenario_blocked_for_another_reason() -> None:
    out = _solve("custom", _safes(3_000_000), target=1.5, custom_basis_stated_by_founder="pre_money")
    assert _codes(out) == ["E_POOL_TARGET_OUT_OF_RANGE"]
    assert "W_CUSTOM_BASIS_STATED_BY_FOUNDER" not in _warning_codes(out)
    # Positive control: the same answer on a solvable target IS disclosed, so the absence above is the gate.
    ok = _solve("custom", _safes(3_000_000), custom_basis_stated_by_founder="pre_money")
    assert "W_CUSTOM_BASIS_STATED_BY_FOUNDER" in _warning_codes(ok)


def test_an_explicit_null_basis_takes_the_defaulted_path_not_a_refusal() -> None:
    out = _scenario(None, _safes(3_000_000))  # type: ignore[arg-type]
    assert not out.get("blockers"), out.get("blockers")
    assert "target_basis_defaulted" in _warning_codes(out)


# --- the increase-sized pool: the percentage sizes the NEW options, and the existing pool is not credited -----

INCREASE = "post_money_increase"


def test_the_increase_is_sized_alone_at_a_fixed_price() -> None:
    """Worked example (fixed price): pre-top-up FD 10,000,000, existing unallocated 500,000, new-money shares
    1,000,000, target 10%. Resulting pool: (0.10 x 11,000,000 - 500,000) / 0.90 = 666,666.67. Increase:
    0.10 x 11,000,000 / 0.90 = 1,222,222.2, and 1,222,222 / 12,222,222 = 10.000%."""
    kw: dict[str, Any] = {
        "pre_topup_fully_diluted_shares": 10_000_000,
        "existing_unallocated_pool": 500_000,
        "target_pool_percent": 0.10,
        "new_money_shares": 1_000_000,
    }
    resulting = option_pool.required_topup(target_basis="post_money", **kw)
    increase = option_pool.required_topup(target_basis=INCREASE, **kw)
    assert resulting["required_pool_topup_shares"] == 666_667
    assert increase["required_pool_topup_shares"] == 1_222_222
    assert increase["post_topup_increase_percent"] == pytest.approx(0.10, abs=1e-7)
    # The resulting pool is the increase plus the existing pool's post-closing share.
    assert increase["post_topup_pool_percent"] == pytest.approx(0.10 + 500_000 / 12_222_222, abs=1e-7)
    assert "option_pool.increase_sized_target" in {p["rule_id"] for p in increase["math_provenance"]}


def _pool_share(result: dict[str, Any], existing: float) -> float:
    """The free pool after the round over post-round FD. Never the aggregate's `option_pool_pct`, which also
    counts granted options."""
    return float((existing + result["shares_breakdown"]["pool_topup"]) / result["post_round_fully_diluted_shares"])


def test_through_the_solver_the_two_readings_differ_by_the_existing_pools_share() -> None:
    """Through the solver the top-up moves the price, so the SHARE-COUNT difference is not E/(1-t). The
    pool-share identity still holds exactly, because it follows from each run's own pool equation."""
    safes = _safes(3_000_000)
    existing = 600_000.0
    increase = _solve(INCREASE, safes)
    resulting = _solve("post_money", safes)
    assert not increase.get("blockers"), increase.get("blockers")
    post_fd = increase["post_round_fully_diluted_shares"]
    assert increase["shares_breakdown"]["pool_topup"] / post_fd == pytest.approx(0.12, abs=1 / post_fd)
    diff = _pool_share(increase, existing) - _pool_share(resulting, existing)
    assert diff == pytest.approx(existing / post_fd, abs=2 / post_fd)


def test_with_no_existing_pool_the_two_readings_are_the_same_number() -> None:
    kw: dict[str, Any] = {
        "pre_topup_fully_diluted_shares": 10_000_000,
        "existing_unallocated_pool": 0,
        "target_pool_percent": 0.10,
        "new_money_shares": 1_000_000,
    }
    a = option_pool.required_topup(target_basis=INCREASE, **kw)
    b = option_pool.required_topup(target_basis="post_money", **kw)
    assert a["required_pool_topup_shares"] == b["required_pool_topup_shares"]


def _increase_reference(pre_pool: float, nm: float, t: float, acq_t: float, pb: str) -> tuple[float, float]:
    """Independent fixed point for the increase basis: x = t * (post-round FD with the consideration when it
    counts), C = b * (pre_pool + nm + x). The existing pool appears nowhere."""
    b = acq_t / (1.0 - acq_t)
    x = 0.0
    for _ in range(5_000_000):
        C = b * (pre_pool + nm + x)
        denom_without_x = pre_pool + nm + (C if pb == "include" else 0.0)
        x_new = t * denom_without_x / (1.0 - t)
        if abs(x_new - x) <= 1e-4:
            x = x_new
            break
        x = x_new
    return x, b * (pre_pool + nm + x)


@pytest.mark.parametrize("pool_basis", ["include", "exclude"])
def test_the_acquisition_system_does_not_credit_the_existing_pool_on_the_increase_basis(pool_basis: str) -> None:
    # A non-clamping existing pool: crediting it would change x by hundreds of thousands of shares.
    got = priced_round._acquisition_pool_C(
        pre_pool=16_000_000,
        nm=3_000_000,
        target=0.10,
        acq_t=0.20,
        existing=500_000,
        target_basis=INCREASE,
        pool_basis=pool_basis,
    )
    assert got is not None
    x_ref, c_ref = _increase_reference(16_000_000, 3_000_000, 0.10, 0.20, pool_basis)
    assert abs(got[0] - x_ref) <= 1.0, (got, x_ref)
    assert abs(got[1] - c_ref) <= 1.0, (got, c_ref)


def test_the_increase_basis_joins_the_acquisition_overdetermination_guard() -> None:
    out = _solve(INCREASE, _safes(3_000_000), target=0.5, acquisition={"consideration_pct": 0.6})
    assert _codes(out) == ["E_ACQUISITION_POOL_OVERDETERMINED"], out.get("blockers")


def _counsel_rule_ids(scenarios: list[dict[str, Any]], *, existing_pool: int = 600_000) -> set[str]:
    import json

    with open(os.path.join(SCRIPTS, "..", "data", "cap-table-rules.json"), encoding="utf-8") as f:
        rules = json.load(f)
    inputs = _inputs()
    inputs["option_pool"]["unallocated"] = existing_pool
    instruments: dict[str, Any] = {"safes": [], "convertible_notes": []}
    state = cap_state_mod.build_cap_state(inputs, instruments)
    gating = rule_audit.build_gating_block(rules, inputs=inputs, instruments=instruments, cap_state=state)
    items = rule_audit.build_counsel_review_items(gating, rules, {"scenarios": scenarios}, inputs)
    return {str(i["rule_id"]) for i in items}


def test_counsel_is_asked_about_the_increase_reading_only_when_a_pool_is_sized_that_way() -> None:
    rid = "option_pool.increase_sized_target"
    solved = {"completeness": "full"}
    increase = {"parameters": {"target_basis": INCREASE, "target_pool_percent": 0.1}, "computed_outputs": solved}
    assert rid in _counsel_rule_ids([increase])
    # Where the two readings are one number, or nothing was solved, counsel has nothing to decide.
    assert rid not in _counsel_rule_ids([increase], existing_pool=0)
    blocked = {**increase, "computed_outputs": {"completeness": "structural_only"}}
    assert rid not in _counsel_rule_ids([blocked])
    # Both directions: a predicate hard-wired to True passes the first assertion alone.
    post = {"parameters": {"target_basis": "post_money", "target_pool_percent": 0.1}, "computed_outputs": solved}
    assert rid not in _counsel_rule_ids([post])
    assert rid not in _counsel_rule_ids([{"parameters": {"target_basis": INCREASE}, "computed_outputs": solved}])
    assert rid not in _counsel_rule_ids([])


def test_the_increase_is_named_as_an_increase_wherever_the_pool_is_described() -> None:
    label = compose_report._pool_sizing_label(INCREASE, 0.1)
    assert label.startswith("new options equal to 10% of the fully diluted share count after the round")
    assert "existing unallocated options" in label
    # The resulting-pool reading names a different numerator, so the two sizings never read the same.
    assert label != compose_report._pool_sizing_label("post_money", 0.1)
    md = _fast(INCREASE, _safes(3_000_000))["_report_md"]
    assert "- Pool target: 12% (new options only, measured against the fully diluted share count after the round)" in md


def test_the_increase_reading_is_compared_with_the_resulting_pool_reading() -> None:
    co = _scenario(INCREASE, _safes(3_000_000))
    cf = co["pool_sizing_counterfactual"]
    assert cf["modeled_basis"] == INCREASE and cf["other_basis"] == "post_money", cf
    assert cf["status"] == "computed", cf
    # The resulting-pool reading credits the existing pool, so it adds fewer options.
    assert cf["pool_topup_shares"]["other"] < cf["pool_topup_shares"]["modeled"]


def test_the_solver_cli_carries_the_founders_answer(tmp_path: Any) -> None:
    import json
    import subprocess

    safes = _safes(3_000_000)
    (tmp_path / "cs.json").write_text(json.dumps(_state(safes)), encoding="utf-8")
    (tmp_path / "inst.json").write_text(json.dumps({"safes": safes, "convertible_notes": []}), encoding="utf-8")
    base = [
        sys.executable,
        os.path.join(SCRIPTS, "priced_round.py"),
        "--cap-state",
        str(tmp_path / "cs.json"),
        "--instruments",
        str(tmp_path / "inst.json"),
        "--pre-money",
        "20000000",
        "--new-money",
        "6000000",
        "--target-pool-pct",
        "0.12",
        "--target-basis",
        "custom",
    ]
    refused = json.loads(subprocess.run(base, capture_output=True, text=True, check=True).stdout)
    assert _codes(refused) == ["E_POOL_BASIS_NOT_MODELED"]
    answered = subprocess.run(
        [*base, "--custom-basis-stated-by-founder", "pre_money"], capture_output=True, text=True, check=True
    )
    assert "W_CUSTOM_BASIS_STATED_BY_FOUNDER" in _warning_codes(json.loads(answered.stdout))


def test_the_acquisition_pool_note_never_states_an_increase_as_the_pools_size() -> None:
    note = compose_report.build_pool_basis_note(
        target_pool_percent=0.12,
        pool_consideration_basis="exclude",
        realized_pool_pct=0.15,
        acquisition_pct=0.2,
        target_basis=INCREASE,
    )
    assert "new options equal to 12%" in note and "sized to 12%" not in note, note
    # Control: the resulting-pool reading keeps its own wording.
    plain = compose_report.build_pool_basis_note(
        target_pool_percent=0.12, pool_consideration_basis="exclude", realized_pool_pct=0.15, acquisition_pct=0.2
    )
    assert "sized to 12%" in plain


def test_the_digest_names_the_excluding_basis_as_the_post_money_it_solved_as() -> None:
    """With nothing converting the gate passes the excluding basis through and it solves as post-money; the
    coach is told only the bases it has words for, so the digest must not carry the raw value."""
    co = _scenario(EXCL, [])
    assert not co.get("blockers"), co.get("blockers")
    assert compose_report._solved_pool_basis({"target_basis": EXCL, "target_pool_percent": 0.12}, co) == "post_money"


# --- either post-money reading beside an existing pool is always disclosed ---------------------------------------
# With unallocated options already in the pool, "X% post-money" is either the pool after the round or only the
# new options, and those are different numbers. Nothing the model writes clears the disclosure: a record of the
# founder's answer that the model writes is satisfied by writing it, so there is none. The answer decides which
# reading is modelled, never whether the other one is shown.

NOT_CONFIRMED = "W_POOL_BASIS_READING_NOT_CONFIRMED"
READ_AS_INCREASE = "W_POOL_BASIS_READ_AS_NEW_OPTIONS_ONLY"


@pytest.mark.parametrize(("basis", "code"), [("post_money", NOT_CONFIRMED), (INCREASE, READ_AS_INCREASE)])
def test_either_post_money_reading_beside_an_existing_pool_is_disclosed(basis: str, code: str) -> None:
    codes = _warning_codes(_solve(basis, _safes(3_000_000)))
    assert code in codes, codes
    assert ({NOT_CONFIRMED, READ_AS_INCREASE} - {code}).isdisjoint(codes), codes


@pytest.mark.parametrize(
    ("basis", "existing"),
    [
        ("post_money", 0),  # no existing pool: the two post-money readings are one number
        (INCREASE, 0),
        ("pre_money", 600_000),
    ],
)
def test_the_reading_is_disclosed_only_where_it_is_ambiguous(basis: str, existing: int) -> None:
    out = _solve(basis, _safes(3_000_000), existing_pool=existing)
    assert not out.get("blockers"), out.get("blockers")
    assert {NOT_CONFIRMED, READ_AS_INCREASE}.isdisjoint(_warning_codes(out))


def test_no_entry_point_takes_a_flag_that_clears_the_disclosure() -> None:
    with pytest.raises(TypeError):
        _solve("post_money", _safes(3_000_000), pool_basis_answered_by_founder=True)
    with pytest.raises(TypeError):
        _fast("post_money", _safes(3_000_000), pool_basis_answered_by_founder=True)
    # A scenario request carrying the old key: run_scenario forwards only the parameters it lists, so the key
    # is dropped and the disclosure stands.
    assert NOT_CONFIRMED in _warning_codes(
        _scenario("post_money", _safes(3_000_000), pool_basis_answered_by_founder=True)
    )


@pytest.mark.parametrize("script", ["quick_assess.py", "priced_round.py"])
def test_the_removed_cli_flag_is_refused(script: str) -> None:
    import subprocess

    # --help exits before argparse checks the required arguments, so it lists every flag the script takes.
    got = subprocess.run([sys.executable, os.path.join(SCRIPTS, script), "--help"], capture_output=True, text=True)
    assert got.returncode == 0 and "--custom-basis-stated-by-founder" in got.stdout, got.stdout  # control
    assert "--pool-basis-answered-by-founder" not in got.stdout


def test_the_new_options_reading_carries_the_whole_pool_figures_through_run_scenario() -> None:
    co = _scenario(INCREASE, _safes(3_000_000))
    assert READ_AS_INCREASE in _warning_codes(co)
    cf = co["pool_sizing_counterfactual"]
    assert cf["other_basis"] == "post_money" and cf["status"] == "computed", cf
    # The comparison is OUR re-solve, so the whole-pool reading's own disclosure does not ride it.
    assert NOT_CONFIRMED not in cf["other_solve_warnings"], cf
    # The new-options-only reading is the one modelled, so there is no second solve of it.
    assert "pool_increase_reading" not in co


@pytest.mark.parametrize(("basis", "code"), [("post_money", NOT_CONFIRMED), (INCREASE, READ_AS_INCREASE)])
def test_fast_assess_shows_the_disclosure_and_claims_no_figure_it_did_not_compute(basis: str, code: str) -> None:
    """Fast-assess calls the solver directly, not through run_scenario -- which is why the disclosure is
    emitted in the solver. It computes no second reading, so it shows no line for one."""
    import _pool_text  # type: ignore[import-not-found]

    out = _fast(basis, _safes(3_000_000))
    assert code in out.get("warnings", [])
    md = out["_report_md"]
    assert WC._SOLVER_WARNING_PROSE[code].split("**")[1] in md
    assert _pool_text.POOL_INCREASE_LINE_LEAD not in md and _pool_text.POOL_CF_LINE_LEAD not in md, md


def test_the_comparison_drops_only_the_reading_disclosures() -> None:
    """A comparison's re-solve is OUR reading, not the founder's, so the two reading codes are dropped from it;
    any other warning on the re-solve still reaches the report."""
    other = {
        "warnings": [
            {"code": NOT_CONFIRMED},
            {"code": READ_AS_INCREASE},
            {"code": "W_MFN_NOT_MOST_FAVORABLE"},
            {"code": "note"},
        ]
    }
    assert run_scenario._comparison_warning_codes(other) == ["W_MFN_NOT_MOST_FAVORABLE"]
    # And the live paths: a pre-money scenario whose comparison is post-money beside an existing pool, and a
    # post-money scenario whose new-options-only re-solve would carry the other reading's code.
    cf = _scenario("pre_money", _safes(3_000_000))["pool_sizing_counterfactual"]
    assert cf["other_basis"] == "post_money" and NOT_CONFIRMED not in cf["other_solve_warnings"], cf
    inc = _scenario("post_money", _safes(3_000_000))["pool_increase_reading"]
    assert inc["status"] == "computed" and READ_AS_INCREASE not in inc["other_solve_warnings"], inc


# --- the pool sentence as evidence: exact or normalized only, so a meaning flip can never pass -----------------

import pool_clause  # type: ignore[import-not-found]  # noqa: E402

_GENUINE = (
    "At the Closing the Company shall reserve such additional Ordinary Shares for the option plan, which "
    "additional shares shall constitute 10.5% of the share capital on a fully diluted basis."
)
# Same sentence with its meaning flipped: the percentage now sizes the TOTAL pool, not the increase.
_FLIPPED = (
    "At the Closing the Company shall reserve such additional Ordinary Shares for the option plan, which "
    "total pool shares shall constitute 10.5% of the share capital on a fully diluted basis."
)
_FILLER = " ".join(f"Clause {i}: the parties agree to the terms set out in the schedules." for i in range(12))
_DOC = f"{_FILLER}\n{_GENUINE}\n{_FILLER}"


def test_a_meaning_flipped_pool_sentence_passes_fuzzy_matching_and_fails_here() -> None:
    import evidence_verifier  # type: ignore[import-not-found]

    # Why this script does not reuse the extraction matcher: that matcher accepts the flip.
    found, kind, _ratio = evidence_verifier.quote_in_doc(_FLIPPED, _DOC)
    assert found and kind.startswith("fuzzy"), kind
    assert pool_clause.check_pool_clause(_FLIPPED, _DOC)["verified"] is False
    assert pool_clause.check_pool_clause(_GENUINE, _DOC) == {"verified": True, "match": "exact", "reason": "found"}


def test_the_flip_fails_under_normalized_matching_too() -> None:
    """The normalizer undoes line breaks, smart quotes and dashes. Applied to both sentences, it lets the
    genuine one through and still refuses the flip."""
    messy = _DOC.replace("reserve such", "reserve\n   such").replace("Ordinary Shares", "Ordinary  Shares")
    genuine = pool_clause.check_pool_clause(_GENUINE, messy)
    assert genuine["verified"] and genuine["match"] == "normalized", genuine
    assert pool_clause.check_pool_clause(_FLIPPED, messy)["verified"] is False


def test_compact_matching_is_not_used_because_it_joins_different_numbers() -> None:
    from _normalize import compact_form  # type: ignore[import-not-found]

    other_number = _GENUINE.replace("10.5%", "105%")
    # The side door: compact form makes the two percentages one string.
    assert compact_form(other_number) in compact_form(_DOC)
    assert pool_clause.check_pool_clause(other_number, _DOC)["verified"] is False


def test_a_fragment_or_an_image_only_document_verifies_nothing() -> None:
    assert pool_clause.check_pool_clause("10.5% of the share", _DOC)["reason"] == "quote_too_short"
    assert pool_clause.check_pool_clause(_GENUINE, _GENUINE)["reason"] == "too_little_text"


def test_the_pool_clause_cli_verifies_and_fails_loudly(tmp_path: Any) -> None:
    import json
    import subprocess

    doc = tmp_path / "term_sheet.txt"
    doc.write_text(_DOC, encoding="utf-8")
    script = os.path.join(SCRIPTS, "pool_clause.py")
    ok = subprocess.run(
        [sys.executable, script, "--doc", str(doc), "--quote", _GENUINE], capture_output=True, text=True
    )
    assert ok.returncode == 0 and json.loads(ok.stdout)["verified"] is True
    out = tmp_path / "verdict.json"
    missing = subprocess.run(
        [sys.executable, script, "--doc", str(tmp_path / "nope.pdf"), "--quote", _GENUINE, "-o", str(out)],
        capture_output=True,
        text=True,
    )
    assert missing.returncode == 1 and missing.stderr.strip()
    assert not out.exists(), "a failure must leave -o untouched"


def test_an_unrecovered_glyph_is_a_barrier_not_a_deletion() -> None:
    """A PDF whose font the reader cannot decode yields `(cid:N)` tokens. Deleting them, as the extraction
    normalizer does, can remove a "not" and verify the opposite sentence."""
    doc = _DOC.replace(
        _GENUINE,
        "Shares issued under this clause shall (cid:81)(cid:82)(cid:87) be counted toward the 10% "
        "post-money pool target.",
    )
    quote = "Shares issued under this clause shall be counted toward the 10% post-money pool target."
    assert pool_clause.check_pool_clause(quote, doc)["verified"] is False


def test_a_quote_cut_short_of_its_qualifier_or_begun_after_a_negation_verifies_nothing() -> None:
    qualified = _GENUINE.rstrip(".") + ", excluding any shares already reserved under the existing plan."
    doc = _DOC.replace(_GENUINE, qualified)
    assert pool_clause.check_pool_clause(_GENUINE.rstrip("."), doc)["verified"] is False  # cut before the qualifier
    negated = _DOC.replace(_GENUINE, "It is not agreed that " + _GENUINE[0].lower() + _GENUINE[1:])
    tail = _GENUINE[0].lower() + _GENUINE[1:]
    assert pool_clause.check_pool_clause(tail, negated)["verified"] is False  # begun after the negation
    # Control: the whole qualified sentence verifies.
    assert pool_clause.check_pool_clause(qualified, doc)["verified"] is True


@pytest.mark.parametrize(
    ("basis", "extra", "other_code"),
    [
        (EXCL, {"excluding_basis_modeled_as": CHOICE}, "W_EXCLUDING_BASIS_MODELED_AS_POST_MONEY"),
        ("custom", {"custom_basis_stated_by_founder": "post_money"}, "W_CUSTOM_BASIS_STATED_BY_FOUNDER"),
    ],
)
def test_a_denominator_disclosure_does_not_answer_what_the_percentage_counts(
    basis: str, extra: dict[str, Any], other_code: str
) -> None:
    """Both substitutions solve plain post-money beside an existing pool, and neither question the founder
    answered asked whether the percentage sizes the whole pool or only the new options."""
    out = _solve(basis, _safes(3_000_000), **extra)
    assert {other_code, NOT_CONFIRMED} <= set(_warning_codes(out)), _warning_codes(out)


def test_the_reading_disclosure_is_stated_once_beside_its_own_scenario_on_every_surface() -> None:
    """report.md, report.html and the explorer each state it once, inside the Option pool section of the scenario
    it applies to -- so a report with several scenarios says which one it touches -- and not again in the global
    callouts. The two surfaces with no pool section, the quick answer and the concise answer, keep it in their
    callouts."""
    import test_cap_table as T  # type: ignore[import-not-found]
    import test_cap_table_pool_text as PT  # type: ignore[import-not-found]

    for basis, code in (("post_money", NOT_CONFIRMED), (INCREASE, READ_AS_INCREASE)):
        lead = WC._SOLVER_WARNING_PROSE[code].split("**")[1]
        _digest, page = T._cf_compose({"target_basis": basis}, available_pool=400_000)
        assert page.count(lead) == 1, (basis, page.count(lead))
        section = page[page.index("**Option pool**") :]
        assert lead in section, basis
        _scenario_, report_html, explorer_html = PT._pages({"target_basis": basis}, available_pool=400_000)
        assert report_html.count(lead) == 1, (basis, report_html.count(lead))
        assert explorer_html.count(lead) == 1, (basis, explorer_html.count(lead))
        assert lead in _fast(basis, _safes(3_000_000))["_report_md"]


def test_the_quick_answer_labels_the_measure_in_the_sections_words() -> None:
    """The quick answer names each measure with the Option pool section's words -- "fully diluted" and, for the
    plain post-money measure only, the one bridge to a term sheet's wording."""
    import _pool_text  # type: ignore[import-not-found]

    for basis, words in (("post_money", "post_money"), ("pre_money", "pre_money"), (INCREASE, INCREASE)):
        md = _fast(basis, _safes(3_000_000))["_report_md"]
        [line] = [ln for ln in md.splitlines() if ln.startswith("- Pool target:")]
        assert _pool_text.TARGET_BASIS_WORDS[words].split(", against ")[-1] in line, line
        assert ("post-money pool" in line) == (basis == "post_money"), line


def test_the_conversion_shares_choice_carries_no_post_money_pool_bridge() -> None:
    """Chosen when the term sheet measures the pool WITHOUT the converting securities: that term sheet does not
    write this pool as a plain "post-money pool", so the bridge would name a pool the founder does not have."""
    import _pool_text  # type: ignore[import-not-found]
    import test_cap_table_pool_text as PT  # type: ignore[import-not-found]

    choice = {"target_basis": EXCL, "excluding_basis_modeled_as": CHOICE}
    sentence = _pool_text.pool_measure_sentence(PT._scenario(choice, available_pool=400_000))
    assert "approximation" in sentence and "post-money pool" not in sentence, sentence
    md = _fast(EXCL, _safes(3_000_000), excluding_basis_modeled_as=CHOICE)["_report_md"]
    # The reading disclosure still fires (it quotes a term sheet's "post-money pool" as one of two readings); the
    # measure's own label is what must carry no bridge.
    [line] = [ln for ln in md.splitlines() if ln.startswith("- Pool target:")]
    assert "post-money pool" not in line and "at your choice" in line, line
    # Control: the plain post-money measure keeps its bridge.
    plain = _pool_text.pool_measure_sentence(PT._scenario({"target_basis": "post_money"}, available_pool=400_000))
    assert "post-money pool" in plain, plain
