"""competitive-positioning's recorded gates, through the real scripts.

Gate 1's question is printed by `open`, naming every competitor the independent search found that the set
lacks; the deferral of the rest is a script call that refuses until Gate 1 is answered. Step 4's additions
question offers only the form the open slots allow. The scoring prompts are not printed until the questions
they rest on are recorded, and take the recorded scoring basis. Compose re-opens a delivered run as a new
revision. Every company name, slug and figure here is invented.
"""

from __future__ import annotations

import importlib.util
import inspect
import json
import re
import shutil
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gate_run_helpers as h  # noqa: E402

CP = "competitive-positioning"
SCRIPTS = h.SKILLS / CP / "scripts"
SKILL_MD = h.SKILLS / CP / "SKILL.md"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / CP
FIXTURE_RUN = "fixture-competitive-positioning-001"


def _load(name: str, path: Path | None = None) -> ModuleType:
    if path is None and name in sys.modules:
        return sys.modules[name]
    if str(h.SHARED) not in sys.path:
        sys.path.append(str(h.SHARED))
    spec = importlib.util.spec_from_file_location(name, path or h.SHARED / f"{name}.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    if path is None:
        sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


rs = _load("_run_status")
g = _load("_gates")


def _out(proc: Any) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(proc.stdout.strip().splitlines()[-1])
    return data


def _ok(proc: Any) -> Any:
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return proc


def _comp(slug: str, name: str, category: str = "direct") -> dict[str, Any]:
    return {"slug": slug, "name": name, "category": category, "description": "d", "key_differentiators": ["k"]}


def _cand(i: int, **extra: Any) -> dict[str, Any]:
    return {
        "slug": f"newco-{i}",
        "name": f"Newco {i}",
        "why_considered": "same buyer, same job",
        "sources": [f"https://example.org/{i}"],
        **extra,
    }


def _run(tmp: Path, *, comps: int = 6, unmatched: list[dict[str, Any]] | None = None) -> tuple[Path, str, Path]:
    root, rid, rd = h.start_bound(tmp, CP)
    rd.mkdir(parents=True, exist_ok=True)
    draft = {
        "competitors": [_comp(f"rival-{i}", f"Rival {i}") for i in range(comps)],
        "candidate_axes": [{"x": "speed", "y": "depth"}],
        "_produced_by": "persist_agent_artifact",
        "metadata": {"run_id": rid},
    }
    _write(rd / "landscape_draft.json", draft)
    ver = {
        "summary": {
            "challenge_slugs": ["rival-1"],
            "category_disagreements": [
                {"slug": "rival-2", "draft_category": "adjacent", "verdict": "genuine", "direction": "upgrade"}
            ],
        },
        "recall_gaps": {"unmatched": [_cand(0, possible_overlap_with="rival-0"), _cand(1), _cand(2)]}
        if unmatched is None
        else {"unmatched": unmatched},
        "metadata": {"run_id": rid},
    }
    _write(rd / "competitor_verification.json", ver)
    return root, rid, rd


def _write(path: Path, doc: Any) -> None:
    path.write_text(json.dumps(doc), encoding="utf-8")


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _needs(proc: Any) -> dict[str, Any]:
    out = _out(proc)
    needs: dict[str, Any] = (out.get("needs_input") or [{}])[0]
    return needs


def _research(rd: Path, rid: str, comps: int, suggestions: int) -> None:
    hand = rd / "handoff" / rid
    hand.mkdir(parents=True, exist_ok=True)
    _write(
        hand / "landscape_research_output.json",
        {
            "competitors": [_comp(f"rival-{i}", f"Rival {i}") for i in range(comps)],
            "suggested_additions": [
                {"slug": f"extra-{i}", "name": f"Extra {i}", "merged": False} for i in range(suggestions)
            ],
        },
    )


# --- Gate 1: the printed question (O2) --------------------------------------------------------------------


def test_gate1_names_every_recall_candidate_and_prints_one_line_each(tmp_path: Path) -> None:
    root, rid, _rd = _run(tmp_path)
    needs = _needs(_ok(h.record(root, rid, "open", "--gate", "cp_gate1_landscape")))
    template = g.GATES["cp_gate1_landscape"]["question"]
    filled = {
        "<N>": "6",
        "<names>": "Rival 1",
        "<upgraded names>": "Rival 2",
        "<recall names>": "Newco 0, Newco 1, Newco 2",
    }
    for slot, value in filled.items():
        template = template.replace(slot, value)
    assert needs["question"] == template
    lines = needs["context_lines"]
    assert lines[0] == "• Newco 0 — same buyer, same job (https://example.org/0) (may already be covered by Rival 0)"
    assert len(lines) == 3


def test_a_removed_competitor_is_never_named_and_no_slug_reaches_the_question(tmp_path: Path) -> None:
    root, rid, rd = _run(tmp_path, unmatched=[_cand(0, possible_overlap_with="rival-1")])
    draft = _read(rd / "landscape_draft.json")
    draft["competitors"] = [c for c in draft["competitors"] if c["slug"] not in ("rival-1", "rival-2")]
    _write(rd / "landscape_draft.json", draft)
    needs = _needs(_ok(h.record(root, rid, "open", "--gate", "cp_gate1_landscape")))
    text = needs["question"] + " ".join(needs["context_lines"])
    assert "rival-" not in text and "Rival 1" not in text and "Rival 2" not in text
    assert "challenge" not in needs["question"] and "covered by" not in text


def test_another_runs_verification_leaves_the_question_worded_from_the_draft(tmp_path: Path) -> None:
    root, rid, rd = _run(tmp_path)
    ver = _read(rd / "competitor_verification.json")
    ver["metadata"]["run_id"] = "20260101T000000Z-aaaaaa"
    _write(rd / "competitor_verification.json", ver)
    proc = _ok(h.record(root, rid, "open", "--gate", "cp_gate1_landscape"))
    assert _needs(proc)["question"] == "Found 6 competitors — does this set look right?"
    assert "context_lines" not in _needs(proc)
    assert "read as absent" in proc.stderr


def test_another_runs_draft_makes_the_question_undecidable(tmp_path: Path) -> None:
    root, rid, rd = _run(tmp_path)
    draft = _read(rd / "landscape_draft.json")
    draft["metadata"]["run_id"] = "20260101T000000Z-aaaaaa"
    _write(rd / "landscape_draft.json", draft)
    before = h.snapshot(root, rid)
    proc = h.record(root, rid, "open", "--gate", "cp_gate1_landscape")
    assert proc.returncode == 2 and _out(proc)["code"] == "GATE_UNDECIDABLE"
    assert h.snapshot(root, rid) == before


def test_an_empty_reason_drops_its_dash(tmp_path: Path) -> None:
    root, rid, _rd = _run(tmp_path, unmatched=[_cand(0, why_considered="  ")])
    lines = _needs(_ok(h.record(root, rid, "open", "--gate", "cp_gate1_landscape")))["context_lines"]
    assert lines == ["• Newco 0 (https://example.org/0)"]


def test_a_candidate_added_under_a_suffixed_slug_is_not_named_again(tmp_path: Path) -> None:
    gap = {"slug": "newco", "name": "Newco, Inc.", "why_considered": "x", "sources": ["https://example.org/n"]}
    root, rid, rd = _run(tmp_path, unmatched=[gap])
    draft = _read(rd / "landscape_draft.json")
    draft["competitors"].append(_comp("newco-inc", "Newco Inc"))
    _write(rd / "landscape_draft.json", draft)
    q = _needs(_ok(h.record(root, rid, "open", "--gate", "cp_gate1_landscape")))["question"]
    assert "Newco" not in q


def test_the_cap_line_says_how_many_fit(tmp_path: Path) -> None:
    root, rid, _rd = _run(tmp_path, comps=6, unmatched=[_cand(i) for i in range(9)])
    lines = _needs(_ok(h.record(root, rid, "open", "--gate", "cp_gate1_landscape")))["context_lines"]
    assert lines[-1] == "I found 9 more, but at most 4 more fit (the set holds 10) — which matter most?"
    root2, rid2, _ = _run(tmp_path / "full", comps=10, unmatched=[_cand(0)])
    lines2 = _needs(_ok(h.record(root2, rid2, "open", "--gate", "cp_gate1_landscape")))["context_lines"]
    assert lines2[-1] == "I found 1 more, but the set is full at 10 — which matter most?"


def test_a_request_answer_still_prints_the_lines_under_context(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    root.mkdir()
    rid = h.start_ok(root, CP, "FS_HOST_ANSWER cp_gate1_landscape=no_changes\n")
    rd = root / "competitive-positioning-example-co"
    _ok(h.bind(root, rid, rd, "example-co"))
    _write(rd / "landscape_draft.json", {"competitors": [_comp("rival-0", "Rival 0")], "metadata": {"run_id": rid}})
    _write(rd / "competitor_verification.json", {"recall_gaps": {"unmatched": [_cand(4)]}, "metadata": {"run_id": rid}})
    out = _out(_ok(h.record(root, rid, "open", "--gate", "cp_gate1_landscape")))
    assert out["applied"] == "pre_answer"
    assert out["context"]["cp_gate1_landscape"]["context_lines"] == [
        "• Newco 4 — same buyer, same job (https://example.org/4)"
    ]


def test_a_change_leaves_gate1_open_and_the_next_answer_records(tmp_path: Path) -> None:
    root, rid, rd = _run(tmp_path)
    _ok(
        h.record(
            root, rid, "answer", "--gate", "cp_gate1_landscape", "--answer-id", "missing", "--value", "add Newco 0"
        )
    )
    assert h.status(root, rid)["status"] == "waiting"
    draft = _read(rd / "landscape_draft.json")
    draft["competitors"].append(_comp("newco-0", "Newco 0"))
    _write(rd / "landscape_draft.json", draft)
    q = _needs(_ok(h.record(root, rid, "open", "--gate", "cp_gate1_landscape")))["question"]
    assert "Newco 0" not in q and "Newco 1" in q
    _ok(h.record(root, rid, "answer", "--gate", "cp_gate1_landscape", "--answer-id", "no_changes"))
    assert h.status(root, rid)["status"] == "running"


def test_the_deferral_never_reopens_gate1_and_a_changed_set_does(tmp_path: Path) -> None:
    root, rid, rd = _run(tmp_path)
    _ok(h.record(root, rid, "answer", "--gate", "cp_gate1_landscape", "--answer-id", "no_changes"))
    _ok(_deferral(rd, rid))
    assert [c["slug"] for c in _read(rd / "landscape_draft.json")["deferred_recall_candidates"]] == [
        "newco-0",
        "newco-1",
        "newco-2",
    ]
    assert h.record(root, rid, "require", "--gate", "cp_gate1_landscape").returncode == 0
    draft = _read(rd / "landscape_draft.json")
    draft["candidate_axes"] = [{"x": "price", "y": "reach"}]
    _write(rd / "landscape_draft.json", draft)
    assert h.record(root, rid, "require", "--gate", "cp_gate1_landscape").returncode == 0
    draft["competitors"].pop()
    _write(rd / "landscape_draft.json", draft)
    assert h.record(root, rid, "require", "--gate", "cp_gate1_landscape").returncode == 10


def test_change_options_cannot_be_sent_ahead(tmp_path: Path) -> None:
    proc = h.start(tmp_path, CP, "FS_HOST_ANSWER cp_gate1_landscape=missing\n")
    assert proc.returncode == 1 and "PRE_ANSWER_INVALID" in proc.stdout


# --- the deferral writer: O2's glue, and the check before Step 4 ---------------------------------------------


def _deferral(rd: Path, rid: str | None, *extra: str) -> Any:
    argv: list[Any] = [SCRIPTS / "record_deferred_recall.py", "--draft", str(rd / "landscape_draft.json")]
    argv += ["--from-verification", str(rd / "competitor_verification.json")]
    if rid is not None:
        argv += ["--run-id", rid]
    return h.run(*argv, *extra)


def test_the_deferral_waits_for_gate1(tmp_path: Path) -> None:
    root, rid, rd = _run(tmp_path)
    before = (rd / "landscape_draft.json").read_bytes()
    proc = _deferral(rd, rid)
    assert proc.returncode == 10 and _out(proc)["blocked_by_gate"] == "cp_gate1_landscape"
    _ok(h.record(root, rid, "answer", "--gate", "cp_gate1_landscape", "--answer-id", "missing", "--value", "x"))
    assert _deferral(rd, rid).returncode == 10
    assert (rd / "landscape_draft.json").read_bytes() == before


def test_the_deferral_refuses_another_runs_verification_and_needs_the_run_id(tmp_path: Path) -> None:
    root, rid, rd = _run(tmp_path)
    _ok(h.record(root, rid, "answer", "--gate", "cp_gate1_landscape", "--answer-id", "no_changes"))
    ver = _read(rd / "competitor_verification.json")
    ver["metadata"]["run_id"] = "20260101T000000Z-aaaaaa"
    _write(rd / "competitor_verification.json", ver)
    before = (rd / "landscape_draft.json").read_bytes()
    assert _deferral(rd, rid).returncode == 1
    no_id = _deferral(rd, None)
    assert no_id.returncode == 1 and _out(no_id)["code"] == "RUN_ID_REQUIRED"
    assert (rd / "landscape_draft.json").read_bytes() == before


def test_without_a_ledger_the_deferral_skips_the_adopted(tmp_path: Path) -> None:
    rd = tmp_path / "plain"
    rd.mkdir()
    _write(rd / "landscape_draft.json", {"competitors": [_comp("newco-1", "Newco 1")], "metadata": {"run_id": "r1"}})
    _write(
        rd / "competitor_verification.json",
        {"recall_gaps": {"unmatched": [_cand(0), _cand(1)]}, "metadata": {"run_id": "r1"}},
    )
    out = _out(_ok(_deferral(rd, "r1")))
    assert out["added"] == ["newco-0"] and out["skipped_already_competitors"] == ["newco-1"]
    _write(rd / "competitor_verification.json", {"metadata": {"run_id": "r1"}})
    assert _out(_ok(_deferral(rd, "r1")))["added"] == []


# --- Step 4: the additions question --------------------------------------------------------------------------


def test_partial_fit_offers_top_and_refuses_another_form_by_its_code(tmp_path: Path) -> None:
    root, rid, rd = _run(tmp_path, comps=8)
    _research(rd, rid, 8, 3)
    needs = _needs(_ok(h.record(root, rid, "open", "--gate", "cp_research_additions")))
    assert [o["label"] for o in needs["options"]] == ["Include top 2", "Include some", "No changes — skip these"]
    assert needs["question"] == g._CP_ADDITIONS_QUESTIONS[1].format(n=3, slots=2)
    proc = h.record(root, rid, "answer", "--gate", "cp_research_additions", "--answer-id", "include_all")
    assert proc.returncode == 1 and _out(proc)["code"] == "OPTION_UNLISTED"
    assert "open slots: 2" in _out(proc)["message"]


def test_a_request_line_for_another_form_waits(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    root.mkdir()
    rid = h.start_ok(root, CP, "FS_HOST_ANSWER cp_research_additions=include_all\n")
    rd = root / "competitive-positioning-example-co"
    _ok(h.bind(root, rid, rd, "example-co"))
    _research(rd, rid, 8, 3)
    _ok(h.record(root, rid, "open", "--gate", "cp_research_additions"))
    st = h.status(root, rid)
    assert (st["status"], st["code"]) == ("waiting", "PRE_ANSWER_UNLISTED")


def test_include_some_reaches_every_candidate_and_caps_the_picks(tmp_path: Path) -> None:
    root, rid, rd = _run(tmp_path, comps=8)
    _research(rd, rid, 8, 5)
    _ok(h.record(root, rid, "answer", "--gate", "cp_research_additions", "--answer-id", "include_some"))
    needs = _needs(_ok(h.record(root, rid, "open", "--gate", "cp_research_pick")))
    assert [o["id"] for o in needs["options"]] == ["extra-0", "extra-1", "extra-2", "extra-3"]
    # Founder-facing lines carry names only; the ids a typed name records under are apart from them.
    assert needs["context_lines"] == [
        "At most 2 more fit. Every company research found: Extra 0, Extra 1, Extra 2, Extra 3, Extra 4."
    ]
    assert {"id": "extra-4", "label": "Extra 4"} in needs["recordable"]
    assert "[,<option_id>" in needs["answer_command"]
    three = h.record(root, rid, "answer", "--gate", "cp_research_pick", "--answer-id", "extra-0,extra-1,extra-2")
    assert three.returncode == 1 and "only 2 more fit" in _out(three)["message"]
    _ok(h.record(root, rid, "answer", "--gate", "cp_research_pick", "--answer-id", "extra-4"))


def test_few_candidates_leave_room_for_none_of_these(tmp_path: Path) -> None:
    root, rid, rd = _run(tmp_path, comps=4)
    _research(rd, rid, 4, 3)
    _ok(h.record(root, rid, "answer", "--gate", "cp_research_additions", "--answer-id", "include_some"))
    ids = [o["id"] for o in _needs(_ok(h.record(root, rid, "open", "--gate", "cp_research_pick")))["options"]]
    assert ids == ["extra-0", "extra-1", "extra-2", "none_of_these"]


def test_include_top_asks_no_pick(tmp_path: Path) -> None:
    root, rid, rd = _run(tmp_path, comps=8)
    _research(rd, rid, 8, 3)
    _ok(h.record(root, rid, "answer", "--gate", "cp_research_additions", "--answer-id", "include_top"))
    assert h.record(root, rid, "open", "--gate", "cp_research_pick").returncode == 11


def test_a_full_set_asks_only_while_a_merger_is_undecided(tmp_path: Path) -> None:
    root, rid, rd = _run(tmp_path, comps=10)
    _research(rd, rid, 10, 2)
    assert h.record(root, rid, "open", "--gate", "cp_research_additions").returncode == 11
    _ok(h.record(root, rid, "open", "--gate", "cp_consolidation_merge.rival-1+rival-2"))
    ids = [o["id"] for o in _needs(_ok(h.record(root, rid, "open", "--gate", "cp_research_additions")))["options"]]
    assert ids == ["skip", "free_slot_by_merging"]


def test_a_merger_kept_separate_is_never_offered_again(tmp_path: Path) -> None:
    root, rid, rd = _run(tmp_path, comps=10)
    _research(rd, rid, 10, 2)
    _ok(h.record(root, rid, "open", "--gate", "cp_consolidation_merge.rival-1+rival-2"))
    _ok(
        h.record(
            root, rid, "answer", "--gate", "cp_consolidation_merge.rival-1+rival-2", "--answer-id", "keep_separate"
        )
    )
    assert h.record(root, rid, "open", "--gate", "cp_research_additions").returncode == 11


def test_the_merge_pick_names_companies_and_is_asked_only_for_several(tmp_path: Path) -> None:
    root, rid, rd = _run(tmp_path, comps=10)
    _research(rd, rid, 10, 2)
    _ok(h.record(root, rid, "open", "--gate", "cp_consolidation_merge.rival-1+rival-2"))
    _ok(h.record(root, rid, "answer", "--gate", "cp_research_additions", "--answer-id", "free_slot_by_merging"))
    assert h.record(root, rid, "open", "--gate", "cp_merge_pick").returncode == 11
    root2, rid2, rd2 = _run(tmp_path / "two", comps=10)
    _research(rd2, rid2, 10, 2)
    for pair in ("rival-1+rival-2", "rival-3+rival-4"):
        _ok(h.record(root2, rid2, "open", "--gate", f"cp_consolidation_merge.{pair}"))
    _ok(h.record(root2, rid2, "answer", "--gate", "cp_research_additions", "--answer-id", "free_slot_by_merging"))
    labels = [o["label"] for o in _needs(_ok(h.record(root2, rid2, "open", "--gate", "cp_merge_pick")))["options"]]
    assert labels == ["Rival 1 and Rival 2", "Rival 3 and Rival 4"]


def test_the_research_gates_hold_the_landscape(tmp_path: Path) -> None:
    root, rid, rd = _run(tmp_path, comps=8)
    _ok(h.record(root, rid, "answer", "--gate", "cp_gate1_landscape", "--answer-id", "no_changes"))
    _research(rd, rid, 8, 3)
    body = _read(rd / "handoff" / rid / "landscape_research_output.json")
    argv: list[Any] = [SCRIPTS / "validate_landscape.py", "--run-id", rid, "-o", str(rd / "landscape.json")]
    proc = h.run(*argv, stdin=json.dumps(body))
    assert proc.returncode == 10 and _out(proc)["blocked_by_gate"] == "cp_research_additions"
    assert not (rd / "landscape.json").exists()
    no_id = h.run(SCRIPTS / "validate_landscape.py", "-o", str(rd / "landscape.json"), stdin=json.dumps(body))
    assert no_id.returncode == 1 and _out(no_id)["code"] == "RUN_ID_REQUIRED"


# --- the scoring basis and Gate 3 -------------------------------------------------------------------------------


def _scores(rd: Path, rid: str, fired: bool = True) -> None:
    view = {
        "view_id": "v1",
        "startup_x_rank": 10 if fired else 3,
        "startup_y_rank": 3,
        "competitor_count": 10,
        "x_axis_vanity_flag": False,
        "y_axis_vanity_flag": False,
        "x_axis_name": "speed",
        "y_axis_name": "depth",
    }
    _write(
        rd / "positioning_scores.json", {"views": [view], "overall_differentiation": 60.0, "metadata": {"run_id": rid}}
    )


def test_a_second_basis_change_is_recordable(tmp_path: Path) -> None:
    root, rid, rd = _run(tmp_path)
    _ok(h.record(root, rid, "answer", "--gate", "cp_gate2_axes", "--answer-id", "change_scoring_basis"))
    assert h.status(root, rid)["waiting_on"] == "cp_scoring_basis"
    _ok(h.record(root, rid, "answer", "--gate", "cp_scoring_basis", "--answer-id", "roadmap_12mo"))
    _scores(rd, rid)
    _ok(h.record(root, rid, "open", "--gate", "cp_gate3_position"))
    _ok(h.record(root, rid, "answer", "--gate", "cp_gate3_position", "--answer-id", "change_scoring_basis"))
    assert h.status(root, rid)["waiting_on"] == "cp_scoring_basis"
    _ok(h.record(root, rid, "answer", "--gate", "cp_scoring_basis", "--answer-id", "mixed"))
    assert h.record(root, rid, "require", "--gate", "cp_scoring_basis").returncode == 0


def test_gate3_is_owed_by_the_scores_and_undecidable_on_another_runs(tmp_path: Path) -> None:
    root, rid, rd = _run(tmp_path)
    _scores(rd, rid, fired=False)
    assert h.record(root, rid, "open", "--gate", "cp_gate3_position").returncode == 11
    _scores(rd, rid)
    scores = _read(rd / "positioning_scores.json")
    scores["metadata"]["run_id"] = "20260101T000000Z-aaaaaa"
    _write(rd / "positioning_scores.json", scores)
    proc = h.record(root, rid, "require", "--gate", "cp_gate3_position")
    assert proc.returncode == 2 and _out(proc)["code"] == "GATE_UNDECIDABLE"


# --- the prompt generator ----------------------------------------------------------------------------------------


def _gen(rd: Path, rid: str, context: str, *extra: str) -> Any:
    hand = rd / "handoff" / rid
    hand.mkdir(parents=True, exist_ok=True)
    argv: list[Any] = [SCRIPTS / "cp_dispatch_prompt.py", context, "--run-id", rid, "--analysis-dir", str(rd)]
    argv += ["--analysis-dir-agent", str(rd), "--handoff-agent", str(hand)]
    if context == "red_team":
        argv += ["--handoff-dir", str(hand)]
    return h.run(*argv, *extra)


def _assert_no_prompt(proc: Any) -> None:
    for line in proc.stdout.splitlines():
        assert not re.match(r"\s*(CONTEXT|OUTPUT_PATH|RUN_ID):", line), line
        assert "Do NOT write any file other than OUTPUT_PATH" not in line


def _fixture_run(tmp: Path) -> tuple[Path, str, Path]:
    root, rid, rd = h.start_bound(tmp, CP, lines=f"FS_HOST_RUN_ID={FIXTURE_RUN}\n")
    rd.mkdir(parents=True, exist_ok=True)
    for f in FIXTURES.iterdir():
        if f.suffix == ".json":
            shutil.copy(f, rd / f.name)
    return root, rid, rd


def _answer_all(root: Path, rid: str, rd: Path) -> None:
    keys = [f"cp_product_profile.{f}" for f in ("product", "customers", "differentiation")]
    keys.append("cp_product_availability")
    args = [a for k in keys for a in ("--gate", k)]
    _ok(h.record(root, rid, "not-applicable", *args, "--reason", "the deck states it"))
    _ok(h.record(root, rid, "answer", "--gate", "cp_gate1_landscape", "--answer-id", "no_changes"))
    _ok(h.record(root, rid, "answer", "--gate", "cp_gate2_axes", "--answer-id", "no_changes"))
    gate3 = h.record(root, rid, "open", "--gate", "cp_gate3_position")
    if gate3.returncode == 0 and _out(gate3).get("needs_input"):
        _ok(h.record(root, rid, "answer", "--gate", "cp_gate3_position", "--answer-id", "no_changes"))


def test_the_generator_prints_nothing_until_its_gates_are_recorded(tmp_path: Path) -> None:
    root, rid, rd = _fixture_run(tmp_path)
    for context in ("startup_research", "moat_scoring", "checklist", "red_team"):
        proc = _gen(rd, rid, context)
        assert proc.returncode == 10, (context, proc.stdout + proc.stderr)
        _assert_no_prompt(proc)
    _answer_all(root, rid, rd)
    for context in ("startup_research", "moat_scoring", "positioning_scoring", "checklist", "red_team"):
        assert _gen(rd, rid, context).returncode == 0, context
    _ok(h.record(root, rid, "open", "--gate", "cp_upload_path"))
    held = _gen(rd, rid, "red_team")
    assert held.returncode == 10 and _out(held)["blocked_by_gate"] == "cp_upload_path"
    _assert_no_prompt(held)


def test_the_positioning_prompt_takes_the_recorded_basis(tmp_path: Path) -> None:
    root, rid, rd = _fixture_run(tmp_path)
    _answer_all(root, rid, rd)
    mixed = _gen(rd, rid, "positioning_scoring", "--scoring-basis", "mixed")
    assert mixed.returncode == 1 and _out(mixed)["code"] == "GATE_RECORD_MISMATCH"
    _assert_no_prompt(mixed)
    plain = h.run(
        SCRIPTS / "cp_dispatch_prompt.py",
        "positioning_scoring",
        "--run-id",
        rid,
        "--analysis-dir",
        str(tmp_path / "nowhere"),
        "--analysis-dir-agent",
        str(rd),
        "--handoff-agent",
        str(rd / "handoff" / rid),
        "--scoring-basis",
        "shipped",
    )
    assert _ok(_gen(rd, rid, "positioning_scoring")).stdout.replace(str(rd), "") == plain.stdout.replace(
        str(tmp_path / "nowhere"), ""
    ).replace(str(rd), "")


# --- the product questions, compose and the delivered run ------------------------------------------------------


def _persist(rd: Path, rid: str, artifact: str) -> Any:
    body = _read(FIXTURES / artifact)
    body.pop("_produced_by", None)
    argv: list[Any] = [
        SCRIPTS / "persist_agent_artifact.py",
        "--artifact",
        artifact,
        "-o",
        str(rd / artifact),
        "--run-id",
        rid,
    ]
    return h.run(*argv, stdin=json.dumps(body))


def test_the_product_profile_waits_for_its_questions_and_a_delivered_run_is_not_started_again(tmp_path: Path) -> None:
    root, rid, rd = _fixture_run(tmp_path)
    (rd / "product_profile.json").unlink()
    proc = _persist(rd, rid, "product_profile.json")
    assert proc.returncode == 10 and not (rd / "product_profile.json").exists()
    _answer_all(root, rid, rd)
    _ok(_persist(rd, rid, "product_profile.json"))
    rs.update(rs.run_paths(str(root), rid), lambda s: (s.update(coaching="inserted"), rs.mark_complete(s)))
    for artifact in ("product_profile.json", "landscape_draft.json"):
        refused = _persist(rd, rid, artifact)
        assert refused.returncode == 1 and _out(refused)["code"] == "RUN_FINISHED", artifact
    _ok(_persist(rd, rid, "positioning.json"))


def _profile(rd: Path, rid: str, availability: str | None) -> Any:
    body = _read(FIXTURES / "product_profile.json")
    body.pop("_produced_by", None)
    if availability is not None:
        body.update(product_availability=availability, availability_quote="invented quote")
    argv = ["--artifact", "product_profile.json", "-o", str(rd / "product_profile.json"), "--run-id", rid]
    return h.run(SCRIPTS / "persist_agent_artifact.py", *argv, stdin=json.dumps(body))


def _three_stated(root: Path, rid: str) -> None:
    keys = [f"cp_product_profile.{f}" for f in ("product", "customers", "differentiation")]
    _ok(h.record(root, rid, "not-applicable", *[a for k in keys for a in ("--gate", k)], "--reason", "stated"))


def test_whether_the_product_ships_is_a_recorded_question_the_profile_carries(tmp_path: Path) -> None:
    root, rid, rd = _fixture_run(tmp_path)
    (rd / "product_profile.json").unlink()
    _three_stated(root, rid)
    waiting = _profile(rd, rid, "pilot")
    assert waiting.returncode == 10 and _out(waiting)["blocked_by_gate"] == "cp_product_availability"
    assert not (rd / "product_profile.json").exists()
    labels = [o["label"] for o in _out(waiting)["needs_input"][0]["options"]]
    assert "Pilot or private beta" in labels and len(labels) == 4
    _ok(h.record(root, rid, "answer", "--gate", "cp_product_availability", "--answer-id", "pilot"))
    for other in ("shipping", None):
        refused = _profile(rd, rid, other)
        assert refused.returncode == 1 and "cp_product_availability" in refused.stdout, other
        assert not (rd / "product_profile.json").exists()
    _ok(_profile(rd, rid, "pilot"))


def test_an_unsure_answer_leaves_availability_out_and_a_stated_one_is_the_materials(tmp_path: Path) -> None:
    root, rid, rd = _fixture_run(tmp_path)
    (rd / "product_profile.json").unlink()
    _three_stated(root, rid)
    _ok(h.record(root, rid, "answer", "--gate", "cp_product_availability", "--answer-id", "not_sure"))
    assert _profile(rd, rid, "shipping").returncode == 1
    _ok(_profile(rd, rid, None))
    root2, rid2, rd2 = _fixture_run(tmp_path / "stated")
    _three_stated(root2, rid2)
    _ok(h.record(root2, rid2, "not-applicable", "--gate", "cp_product_availability", "--reason", "slide 3"))
    _ok(_profile(rd2, rid2, "shipping"))


def test_a_request_that_says_not_to_ask_takes_unsure_for_availability(tmp_path: Path) -> None:
    root, rid, _rd = h.start_bound(tmp_path, CP, lines=f"FS_HOST_RUN_ID={FIXTURE_RUN}\nFS_HOST_NO_ASK\n")
    proc = h.record(root, rid, "open", "--gate", "cp_product_availability")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    cur = h.ledger(root, rid)["gates"]["cp_product_availability"]["current"]
    assert (cur["answer_id"], cur["resolution"]) == ("not_sure", "default_taken")


def test_unattended_the_materials_availability_survives_the_batched_open_and_ranks_today(tmp_path: Path) -> None:
    """Under FS_HOST_NO_ASK the batched open takes `not_sure` at once; the materials' value, recorded after it in
    one batch with the product questions, replaces it, the profile keeps `shipping`, and today's point is ranked."""
    from test_competitive_positioning import _make_valid_positioning_input

    root, rid, rd = h.start_bound(tmp_path, CP, lines=f"FS_HOST_RUN_ID={FIXTURE_RUN}\nFS_HOST_NO_ASK\n")
    rd.mkdir(parents=True, exist_ok=True)
    keys = [
        *[f"cp_product_profile.{f}" for f in ("product", "customers", "differentiation")],
        "cp_product_availability",
    ]
    gates = [a for k in keys for a in ("--gate", k)]
    h.record(root, rid, "open", *gates)  # exits 12 for the product questions; availability takes its default
    assert h.ledger(root, rid)["gates"]["cp_product_availability"]["current"]["answer_id"] == "not_sure"
    _ok(h.record(root, rid, "not-applicable", *gates, "--reason", "slide 3 says it is in use"))
    assert all(h.ledger(root, rid)["gates"][k]["state"] == "not_owed" for k in keys)
    _ok(_profile(rd, rid, "shipping"))
    payload = _make_valid_positioning_input()
    pt = next(p for p in payload["views"][0]["points"] if p["competitor"] == "_startup")
    pt.update(x=10, y=10, planned_x=90, planned_y=90)
    scored = h.run(
        SCRIPTS / "score_positioning.py",
        "--product-profile",
        str(rd / "product_profile.json"),
        stdin=json.dumps(payload),
    )
    assert scored.returncode == 0, scored.stderr
    assert json.loads(scored.stdout)["views"][0]["today"]["ranked"] is True


def _compose(rd: Path, *extra: str) -> Any:
    argv: list[Any] = [SCRIPTS / "compose_report.py", "--dir", str(rd), "-o", str(rd / "report.json")]
    return h.run(*argv, "--write-md", str(rd / "report.md"), *extra)


def test_compose_requires_every_question_and_never_opens_the_documents_one(tmp_path: Path) -> None:
    root, rid, rd = _fixture_run(tmp_path)
    proc = _compose(rd)
    assert proc.returncode == 10 and not (rd / "report.json").exists()
    _answer_all(root, rid, rd)
    _ok(_compose(rd))
    assert "cp_upload_path" not in h.ledger(root, rid)["gates"]
    assert h.status(root, rid)["coaching"] == "pending"


def test_an_open_documents_question_stops_compose_and_a_skipped_review_closes_it(tmp_path: Path) -> None:
    root, rid, rd = _fixture_run(tmp_path)
    _answer_all(root, rid, rd)
    _ok(h.record(root, rid, "open", "--gate", "cp_upload_path"))
    proc = _compose(rd)
    assert proc.returncode == 10 and _out(proc)["code"] == "GATE_UNRESOLVED"
    argv: list[Any] = [SCRIPTS / "record_red_team_skip.py", "--reason", "founder_declined", "--run-id", rid]
    _ok(h.run(*argv, "-o", str(rd / "red_team_skip.json")))
    assert h.ledger(root, rid)["gates"]["cp_upload_path"]["state"] == "not_owed"
    _ok(_compose(rd))


def test_a_report_scored_on_another_basis_is_refused(tmp_path: Path) -> None:
    root, rid, rd = _fixture_run(tmp_path)
    _answer_all(root, rid, rd)
    pos = _read(rd / "positioning.json")
    pos["scoring_basis"] = "mixed"
    _write(rd / "positioning.json", pos)
    proc = _compose(rd)
    assert proc.returncode == 1 and _out(proc)["code"] == "GATE_RECORD_MISMATCH"


def test_a_recompose_after_delivery_is_a_new_revision(tmp_path: Path) -> None:
    root, rid, rd = _fixture_run(tmp_path)
    _answer_all(root, rid, rd)
    _ok(_compose(rd))
    paths = rs.run_paths(str(root), rid)
    rs.complete_after_coaching(paths, str(rd / "report.md"), str(rd / "report.json"))
    for key, name in (("report_html", "report.html"), ("explorer_html", "explore.html")):
        (rd / name).write_text("<html><head></head></html>", encoding="utf-8")
        rs.add_deliverable(paths, key, str(rd / name), rs.file_sha256(str(rd / name)), "test")
    st = h.status(root, rid)
    assert (st["status"], st["deliverables_status"], st["revision"]) == ("complete", "final", 0)
    again = _ok(_compose(rd))
    assert "composed again as revision 1" in again.stderr
    st = h.status(root, rid)
    assert (st["status"], st["revision"], st["deliverables"], st["coaching"]) == ("running", 1, None, "pending")
    assert st["resumed_from"] == {"gate": None, "step": "7", "reason": "reopened"}
    rs.complete_after_coaching(paths, str(rd / "report.md"), str(rd / "report.json"))
    assert h.status(root, rid)["status"] == "complete"


def test_a_trigger_the_override_newly_fires_is_asked_not_refused(tmp_path: Path) -> None:
    root, rid, rd = _fixture_run(tmp_path)
    _scores(rd, rid, fired=False)
    _answer_all(root, rid, rd)
    _ok(_compose(rd))
    rs.update(rs.run_paths(str(root), rid), lambda s: (s.update(coaching="inserted"), rs.mark_complete(s)))
    scores = _read(rd / "positioning_scores.json")
    _scores(rd, rid, fired=True)
    proc = _compose(rd)
    assert proc.returncode == 10 and _out(proc)["blocked_by_gate"] == "cp_gate3_position", proc.stdout
    assert scores != _read(rd / "positioning_scores.json")


def test_the_closer_stamps_the_hand_over(tmp_path: Path) -> None:
    root, rid, rd = _fixture_run(tmp_path)
    _answer_all(root, rid, rd)
    _ok(_compose(rd))
    report = _read(rd / "report.json")
    report["verdict"] = "Example Co leads its map on one axis of two."
    _write(rd / "report.json", report)
    argv: list[Any] = [SCRIPTS / "cp_closing_message.py", "--report", str(rd / "report.json"), "--link", "path"]
    _ok(h.run(*argv, "--deliverable", f"the written report={rd}/report.md"))
    assert h.status(root, rid)["handed_over_at"]


@pytest.mark.parametrize("script", ["score_moats.py", "score_positioning.py", "checklist.py"])
def test_a_scorer_into_a_run_dir_names_its_run(tmp_path: Path, script: str) -> None:
    _root, _rid, rd = _fixture_run(tmp_path)
    proc = h.run(SCRIPTS / script, "-o", str(rd / "out.json"), stdin="{}")
    assert proc.returncode == 1 and _out(proc)["code"] == "RUN_ID_REQUIRED"
    assert not (rd / "out.json").exists()


# --- held equal ---------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "open_ledger_or_exit",
        "require_or_exit",
        "_why",
        "refuse_without_run_id",
        "refuse_open_gates",
        "coaching_pending",
        "stamp_handed_over",
    ],
)
def test_the_helpers_are_market_sizings_word_for_word(name: str) -> None:
    cp = _load("_cp_gates_pin", SCRIPTS / "_cp_gates.py")
    ms = _load("_ms_gates_pin3", h.SKILLS / "market-sizing" / "scripts" / "_ms_gates.py")
    assert inspect.getsource(getattr(cp, name)) == inspect.getsource(getattr(ms, name))


def test_the_set_cap_is_one_number() -> None:
    vl = _load("_cp_vl_pin", SCRIPTS / "validate_landscape.py")
    view = _load("_cp_view_pin", SCRIPTS / "_cp_view.py")
    assert g.CP_MAX_COMPETITORS == vl.MAX_COMPETITORS == view.MAX_COMPETITORS


def test_the_slug_rule_is_the_recall_diffs() -> None:
    vc = _load("_cp_vc_pin", SCRIPTS / "verify_competitors.py")
    for name in ("Newco, Inc.", "Example Labs LLC", "rival-1"):
        assert g.cp_slug(name) == vc.normalize_competitor_slug(name)


def test_each_gates_step_names_a_skill_md_heading() -> None:
    """`resume_step` is what a resumed run reads first: each CP gate's step is a heading SKILL.md has."""
    text = SKILL_MD.read_text(encoding="utf-8")
    heading = {"gate1": "### Gate 1:", "gate2": "### Gate 2:", "gate3": "### Gate 3:"}
    for gid, gate in g.GATES.items():
        if gate["skill"] != CP:
            continue
        step = gate["step"]
        anchor = heading.get(step) or f"### Step {step}:"
        assert anchor in text, (gid, step)


def test_the_shared_option_check_names_no_skills_helper() -> None:
    """A variant gate's refusal reason comes from its own entry in `VARIANT_NOTES`, never a skill helper."""
    assert "_cp_" not in inspect.getsource(g._resolve_options)
    assert "cp_research_additions" in g.VARIANT_NOTES


def test_the_contract_says_a_recompose_reopen_has_no_gate() -> None:
    contract = json.loads((h.SHARED.parent / "data" / "host-contract.json").read_text(encoding="utf-8"))
    assert "`gate` null" in json.dumps(contract)


def test_only_a_script_built_gate_lists_recordable_ids(tmp_path: Path) -> None:
    """A hidden option of a fixed gate (financial-model-review's host-only answer) is never listed."""
    root, rid, _rd = h.start_bound(tmp_path, "financial-model-review")
    paths = rs.run_paths(str(root), rid)
    out = g.transact(paths, lambda ctx, led, st: g.needs_input(ctx, led, "fmr_extracted_values"))
    assert "recordable" not in out
