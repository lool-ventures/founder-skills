from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from typing import Any

import pytest

SCRIPT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "skills",
    "deck-review",
    "scripts",
    "gate_state.py",
)


def _run(args: list[str], stdin_data: str | None = None) -> tuple[int, str, str]:
    res = subprocess.run([sys.executable, SCRIPT, *args], input=stdin_data, capture_output=True, text=True)
    return res.returncode, res.stdout, res.stderr


def test_gate_state_emit_writes_validated_artifact() -> None:
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "gate_state.json")
        body = {
            "gate_id": "stage_confirmation",
            "question": "Does this stage look right?",
            "options": ["Looks right", "Different stage", "Not sure — proceed anyway"],
            "context_summary": "Detected: Seed",
        }
        rc, _, err = _run(["emit", "--run-id", "r1", "--stage", "seed", "-o", out, "--pretty"], json.dumps(body))
        assert rc == 0, err
        with open(out) as f:
            written = json.load(f)
        assert written["metadata"]["run_id"] == "r1"
        assert written["gate_id"] == "stage_confirmation"
        assert "answer" not in written


def test_gate_state_emit_rejects_unknown_gate_id() -> None:
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "gate_state.json")
        body = {
            "gate_id": "frobnicate",
            "question": "?",
            "options": ["a"],
            "context_summary": "x",
        }
        rc, _, err = _run(["emit", "--run-id", "r1", "--stage", "seed", "-o", out], json.dumps(body))
        assert rc != 0
        assert "gate_id" in err and "enum" in err.lower()


def test_gate_state_answer_updates_existing_file() -> None:
    """Parent calls `gate_state.py answer --file gate_state.json --answer 'Looks right'`."""
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "gate_state.json")
        # Pre-populate as if emit had run
        with open(path, "w") as f:
            json.dump(
                {
                    "metadata": {"run_id": "r1"},
                    "gate_id": "stage_confirmation",
                    "question": "?",
                    "options": ["Looks right", "Different stage"],
                    "context_summary": "x",
                },
                f,
            )
        rc, _, err = _run(["answer", "--file", path, "--answer", "Looks right", "--source", "founder"])
        assert rc == 0, err
        with open(path) as f:
            written = json.load(f)
        assert written["answer"] == "Looks right"


def test_gate_state_answer_handles_corrupt_file_cleanly() -> None:
    """A truncated/corrupt gate_state.json -> clean stderr + exit 1, not a raw traceback."""
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "gate_state.json")
        with open(path, "w") as f:
            f.write('{"metadata": {"run_id": "r1"}, "options": [')  # truncated JSON
        rc, _, err = _run(["answer", "--file", path, "--answer", "Looks right", "--source", "founder"])
        assert rc == 1
        assert "not valid json" in err.lower()
        assert "Traceback" not in err


def test_gate_state_answer_rejects_non_dict_json() -> None:
    """A gate file that is valid JSON but not an object -> clean error, no AttributeError."""
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "gate_state.json")
        with open(path, "w") as f:
            f.write("[1, 2, 3]")
        rc, _, err = _run(["answer", "--file", path, "--answer", "Looks right", "--source", "founder"])
        assert rc == 1
        assert "json object" in err.lower()
        assert "Traceback" not in err


def test_gate_state_answer_pretty_exits_0_and_emits_indented_json() -> None:
    """gate_state.py answer --pretty must exit 0 and emit indented (pretty) JSON receipt."""
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "gate_state.json")
        with open(path, "w") as f:
            json.dump(
                {
                    "metadata": {"run_id": "r1"},
                    "gate_id": "stage_confirmation",
                    "question": "?",
                    "options": ["Looks right", "Different stage"],
                    "context_summary": "x",
                },
                f,
            )
        rc, stdout, err = _run(["answer", "--file", path, "--answer", "Looks right", "--source", "founder", "--pretty"])
        assert rc == 0, err
        # stdout is the receipt; it must be valid JSON
        receipt = json.loads(stdout)
        assert receipt.get("ok") is True
        # The gate_state.json file itself must be written with indentation
        with open(path) as f:
            raw = f.read()
        assert "\n" in raw and "  " in raw, "answer --pretty should write indented JSON to the artifact file"
        with open(path) as f:
            written = json.load(f)
        assert written["answer"] == "Looks right"


def test_gate_state_answer_rejects_answer_not_in_options() -> None:
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "gate_state.json")
        with open(path, "w") as f:
            json.dump(
                {
                    "metadata": {"run_id": "r1"},
                    "gate_id": "stage_confirmation",
                    "question": "?",
                    "options": ["Looks right", "Different stage"],
                    "context_summary": "x",
                },
                f,
            )
        rc, _, err = _run(["answer", "--file", path, "--answer", "Unicorn", "--source", "founder"])
        assert rc != 0
        assert "Unicorn" in err


# ---------------------------------------------------------------------------
# Answer provenance. A live run showed the gate self-answering "Looks right" with no
# founder input, and the artifact could not distinguish that from a real answer — the
# two are byte-identical once written. `--source` makes the difference recorded.
#
# This is OBSERVABILITY, NOT PROVENANCE, and the distinction is not pedantry: the flag
# is supplied by the same model that would self-answer, so it cannot prove a founder
# spoke. What it does is make the auto-satisfy path state itself, so a run that took it
# is auditable afterwards and a run that recorded nothing is visibly un-auditable.
# ---------------------------------------------------------------------------


def _gate(path: str, gate_id: str = "stage_confirmation", options: list[str] | None = None) -> None:
    with open(path, "w") as f:
        json.dump(
            {
                "metadata": {"run_id": "r1"},
                "gate_id": gate_id,
                "question": "?",
                "options": options or ["Looks right", "Different stage"],
                "context_summary": "x",
            },
            f,
        )


def test_a_founder_answer_records_its_source() -> None:
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "gate_state.json")
        _gate(path)
        rc, _, err = _run(["answer", "--file", path, "--answer", "Looks right", "--source", "founder"])
        assert rc == 0, err
        with open(path) as f:
            assert json.load(f)["answer_source"] == "founder"


def test_the_auto_satisfy_path_records_that_it_was_not_the_founder() -> None:
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "gate_state.json")
        _gate(path)
        rc, _, err = _run(["answer", "--file", path, "--answer", "Looks right", "--source", "auto_satisfied"])
        assert rc == 0, err
        with open(path) as f:
            assert json.load(f)["answer_source"] == "auto_satisfied"


def test_an_out_of_scope_gate_cannot_be_self_answered() -> None:
    """The schema admits three gate_ids and only one has an auto-satisfy rationale.
    Without this restriction the model could self-record "Proceed anyway (best-effort)"
    on a deck it just judged out of scope — the one answer no founder should skip."""
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "gate_state.json")
        _gate(path, "out_of_scope_choice", ["Stop review", "Proceed anyway (best-effort)"])
        rc, _, err = _run(
            ["answer", "--file", path, "--answer", "Proceed anyway (best-effort)", "--source", "auto_satisfied"]
        )
        assert rc != 0
        assert "out_of_scope_choice" in err
        with open(path) as f:
            assert "answer" not in json.load(f), "a refused answer must leave the file untouched"


def test_only_the_confirmation_answer_can_be_self_answered() -> None:
    """Auto-satisfy exists for "the founder already told us the stage and it matches".
    Any other option on the same gate is a decision the founder has not made."""
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "gate_state.json")
        _gate(path)
        rc, _, err = _run(["answer", "--file", path, "--answer", "Different stage", "--source", "auto_satisfied"])
        assert rc != 0
        assert "Different stage" in err
        with open(path) as f:
            assert "answer" not in json.load(f)


def test_an_answer_with_no_stated_source_is_refused() -> None:
    """Required, not defaulted. Defaulting to `founder` would mint false provenance for
    exactly the self-answered case this exists to expose; defaulting to nothing leaves
    the artifact as ambiguous as it was. Omitting the flag writes nothing at all, which
    `setup_run.py` then reads as an unanswered gate and re-asks."""
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "gate_state.json")
        _gate(path)
        rc, _, _ = _run(["answer", "--file", path, "--answer", "Looks right"])
        assert rc != 0
        with open(path) as f:
            assert "answer" not in json.load(f)


def test_an_unknown_source_is_refused() -> None:
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "gate_state.json")
        _gate(path)
        rc, _, _ = _run(["answer", "--file", path, "--answer", "Looks right", "--source", "the_founder_probably"])
        assert rc != 0
        with open(path) as f:
            assert "answer" not in json.load(f)


# ---------------------------------------------------------------------------
# `emit` is the OTHER entry point, and the auto-satisfy restriction guarded only one.
#
# The restriction lives in `cmd_answer`, and the schema makes `answer`/`answer_source`
# optional, so `emit` accepted a gate that arrived already answered. Confirmed end to end:
# emitting an `out_of_scope_choice` carrying answer "Proceed anyway (best-effort)" and
# answer_source "auto_satisfied" succeeded and `setup_run.py` then reported resume:true —
# the deck proceeds, self-authorised, on the one answer a founder most needs to give.
#
# An `emit` writes a gate to be ASKED. A gate that already has an answer is not that.
# ---------------------------------------------------------------------------


def test_emit_refuses_a_gate_that_arrives_already_answered() -> None:
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "gate_state.json")
        body = {
            "gate_id": "out_of_scope_choice",
            "question": "?",
            "options": ["Stop review", "Proceed anyway (best-effort)"],
            "context_summary": "x",
            "answer": "Proceed anyway (best-effort)",
        }
        rc, _, err = _run(["emit", "--run-id", "r1", "--stage", "growth", "-o", out], json.dumps(body))
        assert rc != 0, "emit accepted a pre-answered gate"
        assert "answer" in err
        assert not os.path.exists(out), "a refused emit must not write the artifact"


def test_emit_refuses_a_pre_set_answer_source() -> None:
    """The provenance field is written by `answer`, which is where it is checked. Accepting
    it here lets the whole restriction be routed around."""
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "gate_state.json")
        body = {
            "gate_id": "stage_confirmation",
            "question": "?",
            "options": ["Looks right"],
            "context_summary": "x",
            "answer_source": "auto_satisfied",
        }
        rc, _, err = _run(["emit", "--run-id", "r1", "--stage", "seed", "-o", out], json.dumps(body))
        assert rc != 0, "emit accepted a pre-set answer_source"
        assert "answer_source" in err
        assert not os.path.exists(out)


def test_emit_still_writes_an_ordinary_pending_gate() -> None:
    """The counter-test: the normal path must be untouched."""
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "gate_state.json")
        body = {
            "gate_id": "out_of_scope_choice",
            "question": "?",
            "options": ["Stop review", "Different stage", "Proceed anyway (best-effort)"],
            "context_summary": "x",
        }
        rc, _, err = _run(["emit", "--run-id", "r1", "--stage", "growth", "-o", out], json.dumps(body))
        assert rc == 0, err
        with open(out) as f:
            written = json.load(f)
        assert "answer" not in written
        assert "answer_source" not in written


def test_the_restriction_cannot_be_routed_around_by_emitting_then_resuming() -> None:
    """The end-to-end path the review walked: emit a self-answered out-of-scope gate, then
    ask setup_run whether the run may resume on it."""
    import subprocess

    setup = os.path.join(os.path.dirname(SCRIPT), "setup_run.py")
    with tempfile.TemporaryDirectory() as d:
        review_dir = os.path.join(d, "art", "deck-review-acme")
        os.makedirs(review_dir)
        body = {
            "gate_id": "out_of_scope_choice",
            "question": "?",
            "options": ["Stop review", "Proceed anyway (best-effort)"],
            "context_summary": "x",
            "answer": "Proceed anyway (best-effort)",
            "answer_source": "auto_satisfied",
        }
        rc, _, _ = _run(
            ["emit", "--run-id", "r1", "--stage", "growth", "-o", os.path.join(review_dir, "gate_state.json")],
            json.dumps(body),
        )
        assert rc != 0, "emit wrote the self-authorised gate"

        # Belt and braces: even if such a file reaches disk by some other route, an
        # auto_satisfied source on a gate that may not carry one must not resume.
        with open(os.path.join(review_dir, "gate_state.json"), "w") as f:
            json.dump({"metadata": {"run_id": "r1"}, **body}, f)
        res = subprocess.run(
            [sys.executable, setup, "--artifacts-root", os.path.join(d, "art"), "--slug", "acme", "--run-id", "r1"],
            capture_output=True,
            text=True,
        )
        assert res.returncode == 0, res.stderr
        assert json.loads(res.stdout)["resume"] is False, "a self-answered out-of-scope gate was accepted as a resume"


# The shared validator, tested directly. Both callers guard it behind an answered-check,
# so mutating its own answer branch left every caller-level test green — the branch is
# reachable only through the function's public contract, and that contract is what three
# readers now depend on.


def _import_gate_state() -> Any:
    import importlib.util

    # The script `sys.path`-inserts its own directory at runtime; importing it by path
    # skips that, so the sibling helper it imports has to be reachable first.
    scripts_dir = os.path.dirname(SCRIPT)
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    spec = importlib.util.spec_from_file_location("_gs_probe", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _full_gate(**over: Any) -> dict[str, Any]:
    """A gate as `emit` would write it, including its CANONICAL options.

    The options default to the real ones for whichever gate_id is asked for: they are the
    gate's, not the caller's, and a fixture inventing a shorter list exercises a record no
    writer could produce.
    """
    gs = _import_gate_state()
    gate_id = str(over.get("gate_id", "stage_confirmation"))
    default_options = list(gs.CANONICAL_OPTIONS.get(gate_id, ("Pre-seed", "Seed", "Series A")))
    gate: dict[str, Any] = {
        "metadata": {"run_id": "r1"},
        "gate_id": gate_id,
        "question": "?",
        "options": default_options,
        "context_summary": "x",
        "answer": "Looks right" if gate_id == "stage_confirmation" else default_options[0],
        "answer_source": "founder",
    }
    gate.update(over)
    return gate


def test_validator_accepts_a_legitimate_answered_gate() -> None:
    gs = _import_gate_state()
    assert gs.validate_answered_gate(_full_gate()) == []
    assert gs.validate_answered_gate(_full_gate(answer_source="auto_satisfied")) == []
    assert gs.validate_answered_gate(_full_gate(gate_id="out_of_scope_choice", answer="Stop review")) == []


def test_validator_rejects_each_way_a_gate_can_be_wrong() -> None:
    gs = _import_gate_state()
    cases: dict[str, dict[str, Any]] = {
        "never answered": {"answer": ""},
        "answer outside options": {"answer": "Whatever"},
        "no source": {"answer_source": None},
        "unknown source": {"answer_source": "vibes"},
        "auto-satisfied wrong gate": {
            "gate_id": "out_of_scope_choice",
            "answer": "Looks right",
            "answer_source": "auto_satisfied",
        },
        "auto-satisfied wrong answer": {"answer": "Different stage", "answer_source": "auto_satisfied"},
        "no options to check against": {"options": None},
    }
    for name, over in cases.items():
        gate = _full_gate(**over)
        if over.get("answer_source") is None and "answer_source" in over:
            gate.pop("answer_source")
        if over.get("options") is None and "options" in over:
            gate.pop("options")
        assert gs.validate_answered_gate(gate), f"validator accepted a gate that is {name}"


def test_validator_and_is_answered_split_pending_from_malformed() -> None:
    """A pending gate is not malformed, and the two must not be conflated: one is the
    normal state between emit and answer, the other is a record no writer produced."""
    gs = _import_gate_state()
    pending = _full_gate()
    del pending["answer"]
    del pending["answer_source"]
    assert not gs.is_answered(pending)
    assert gs.is_answered(_full_gate())
    assert not gs.is_answered({"answer": "   "})


# ANSWERED IS NOT AUTHORIZED. `validate_answered_gate` establishes that a record is a
# well-formed answer; it says nothing about whether that answer permits a report to be
# written. Those are different questions and conflating them let three valid answered
# gates compose a clean report: "Stop review" (the founder said do not), "Different stage"
# (a rebuild is owed first) and an intermediate `stage_choice` pick (re-confirmation is
# owed). The worst of the three produced a review for a founder who asked for none.
#
# SKILL.md's own transition table is the authority for which answers continue.


def test_only_terminal_continue_answers_authorize_a_report() -> None:
    gs = _import_gate_state()
    assert gs.gate_action(_full_gate(answer="Looks right")) == "continue"
    # The two "proceed anyway" answers are conditional, not terminal — see
    # test_proceed_anyway_answers_are_conditional_on_the_rebuild.
    assert gs.gate_action(_full_gate(answer="Not sure — proceed anyway")) == "continue_if_rebuilt"
    assert (
        gs.gate_action(_full_gate(gate_id="out_of_scope_choice", answer="Proceed anyway (best-effort)"))
        == "continue_if_rebuilt"
    )


def test_stop_and_rebuild_answers_do_not_authorize_a_report() -> None:
    gs = _import_gate_state()
    assert gs.gate_action(_full_gate(gate_id="out_of_scope_choice", answer="Stop review")) == "stop"

    rebuild = _full_gate(answer="Different stage")
    assert gs.gate_action(rebuild) == "rebuild"

    intermediate = _full_gate(gate_id="stage_choice", answer="Seed", options=["Pre-seed", "Seed", "Series A"])
    assert gs.gate_action(intermediate) == "rebuild"


def test_an_unanswered_gate_is_a_reask_not_a_continue() -> None:
    gs = _import_gate_state()
    pending = _full_gate()
    del pending["answer"]
    del pending["answer_source"]
    assert gs.gate_action(pending) == "reask"
    # And a malformed answered record is likewise not an authorization.
    assert gs.gate_action(_full_gate(answer="Whatever")) == "reask"


# CANONICAL OPTIONS. The validator checked the answer against the caller's OWN option
# list, which makes consent caller-defined: an `out_of_scope_choice` offering only
# "Proceed anyway (best-effort)" validates and authorizes a clean report, with "Stop
# review" simply never presented. A gate whose choices the asker picks is not a gate.


def test_a_gate_cannot_omit_the_option_that_declines() -> None:
    gs = _import_gate_state()
    rigged = _full_gate(
        gate_id="out_of_scope_choice",
        options=["Proceed anyway (best-effort)"],
        answer="Proceed anyway (best-effort)",
    )
    problems = gs.validate_answered_gate(rigged)
    assert problems, "a gate that never offered Stop review was accepted"
    assert any("Stop review" in p or "options" in p for p in problems), problems


def test_the_canonical_options_are_the_only_ones_accepted() -> None:
    gs = _import_gate_state()
    for gate_id in ("stage_confirmation", "out_of_scope_choice"):
        canonical = list(gs.CANONICAL_OPTIONS[gate_id])
        ok = _full_gate(gate_id=gate_id, options=canonical, answer=canonical[0])
        assert gs.validate_answered_gate(ok) == [], (gate_id, gs.validate_answered_gate(ok))
        padded = _full_gate(gate_id=gate_id, options=[*canonical, "Just ship it"], answer=canonical[0])
        assert gs.validate_answered_gate(padded), f"{gate_id} accepted an invented extra option"


def test_stage_choice_options_must_come_from_the_stage_enum() -> None:
    """`stage_choice` is the one gate whose options are chosen at runtime — four of five
    stages, minus the one just rejected — so it cannot have a fixed list. It can still be
    held to the enum."""
    gs = _import_gate_state()
    ok = _full_gate(gate_id="stage_choice", options=["Pre-seed", "Seed", "Series A"], answer="Seed")
    assert gs.validate_answered_gate(ok) == []
    bogus = _full_gate(gate_id="stage_choice", options=["Seed", "Whatever you think"], answer="Seed")
    assert gs.validate_answered_gate(bogus), "stage_choice accepted an option outside the stage enum"


# The two "proceed anyway" answers are NOT terminal. SKILL.md requires the profile to be
# rebuilt at LOW confidence first, so treating them as `continue` authorized a report whose
# stage profile may never have been downgraded — the founder said "not sure" and the review
# was graded as though they had confirmed.


def test_proceed_anyway_answers_are_conditional_on_the_rebuild() -> None:
    gs = _import_gate_state()
    unsure = _full_gate(
        answer="Not sure — proceed anyway",
        options=list(gs.CANONICAL_OPTIONS["stage_confirmation"]),
    )
    assert gs.gate_action(unsure) == "continue_if_rebuilt"
    best_effort = _full_gate(
        gate_id="out_of_scope_choice",
        answer="Proceed anyway (best-effort)",
        options=list(gs.CANONICAL_OPTIONS["out_of_scope_choice"]),
    )
    assert gs.gate_action(best_effort) == "continue_if_rebuilt"
    # The unconditional one is unchanged.
    assert gs.gate_action(_full_gate(options=list(gs.CANONICAL_OPTIONS["stage_confirmation"]))) == "continue"


# A DECLINE MUST SURVIVE THE NEXT EMIT. The gate was one mutable file with no history, so
# the sequence below erased it entirely:
#
#   founder answers "Stop review" -> emit a fresh stage_confirmation over the top ->
#   auto-answer "Looks right" -> compose exits 0
#
# Canonical options did not touch this: every record in that sequence is individually
# valid. What was missing is that the run REMEMBERS. `emit` now carries the prior answered
# state forward, and a stop anywhere in this run's history stays decisive.


def test_emitting_over_an_answered_gate_preserves_it_as_history() -> None:
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "gate_state.json")
        gs = _import_gate_state()
        body = {
            "gate_id": "stage_confirmation",
            "question": "?",
            "options": list(gs.CANONICAL_OPTIONS["stage_confirmation"]),
            "context_summary": "x",
        }
        rc, _, err = _run(["emit", "--run-id", "r1", "--stage", "seed", "-o", path], json.dumps(body))
        assert rc == 0, err
        rc, _, err = _run(["answer", "--file", path, "--answer", "Different stage", "--source", "founder"])
        assert rc == 0, err

        rc, _, err = _run(["emit", "--run-id", "r1", "--stage", "seed", "-o", path], json.dumps(body))
        assert rc == 0, err
        with open(path) as f:
            written = json.load(f)
        assert "answer" not in written, "the re-emitted gate is pending again"
        assert len(written["history"]) == 1, written.get("history")
        assert written["history"][0]["answer"] == "Different stage"


def test_a_decline_cannot_be_erased_by_emitting_another_gate() -> None:
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "gate_state.json")
        gs = _import_gate_state()
        oos = {
            "gate_id": "out_of_scope_choice",
            "question": "?",
            "options": list(gs.CANONICAL_OPTIONS["out_of_scope_choice"]),
            "context_summary": "x",
        }
        _run(["emit", "--run-id", "r1", "--stage", "growth", "-o", path], json.dumps(oos))
        _run(["answer", "--file", path, "--answer", "Stop review", "--source", "founder"])

        stage = {
            "gate_id": "stage_confirmation",
            "question": "?",
            "options": list(gs.CANONICAL_OPTIONS["stage_confirmation"]),
            "context_summary": "x",
        }
        _run(["emit", "--run-id", "r1", "--stage", "seed", "-o", path], json.dumps(stage))
        _run(["answer", "--file", path, "--answer", "Looks right", "--source", "founder"])

        with open(path) as f:
            written = json.load(f)
        assert gs.gate_action(written) == "stop", (
            "a founder's decline was erased by re-emitting a different gate over it"
        )


def test_a_decline_from_a_different_run_does_not_bind_this_one() -> None:
    """The history is this RUN's. A prior completed review that was declined says nothing
    about a fresh one, and `setup_run.py --clean` removes that file anyway."""
    gs = _import_gate_state()
    gate = _full_gate()
    gate["history"] = [
        {"gate_id": "out_of_scope_choice", "answer": "Stop review", "answer_source": "founder", "run_id": "older-run"}
    ]
    assert gs.gate_action(gate) == "continue"


def test_emit_refuses_a_gate_that_does_not_offer_its_own_options() -> None:
    """Canonical options were enforced only when ANSWERING, so a rigged gate reached the
    founder and was refused afterwards — after they had already been shown a choice that
    omitted "Stop review". The check belongs where the question is written."""
    gs = _import_gate_state()
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "gate_state.json")
        rigged = {
            "gate_id": "out_of_scope_choice",
            "question": "?",
            "options": ["Proceed anyway (best-effort)"],
            "context_summary": "x",
        }
        rc, _, err = _run(["emit", "--run-id", "r1", "--stage", "growth", "-o", out], json.dumps(rigged))
        assert rc != 0, "emit wrote a gate that never offers the option to decline"
        assert "Stop review" in err or "options" in err
        assert not os.path.exists(out)

        ok = dict(rigged, options=list(gs.CANONICAL_OPTIONS["out_of_scope_choice"]))
        rc_ok, _, err_ok = _run(["emit", "--run-id", "r1", "--stage", "growth", "-o", out], json.dumps(ok))
        assert rc_ok == 0, err_ok


def test_emit_holds_stage_choice_to_four_stage_options() -> None:
    """`AskUserQuestion` renders at most four, and SKILL.md offers exactly four — the enum
    minus the stage just rejected. Three would hide a stage the founder may want."""
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "gate_state.json")
        body = {"gate_id": "stage_choice", "question": "?", "context_summary": "x"}
        rc, _, err = _run(
            ["emit", "--run-id", "r1", "--stage", "seed", "-o", out], json.dumps({**body, "options": ["Seed"]})
        )
        assert rc != 0, "a one-option stage_choice was written"
        rc2, _, err2 = _run(
            ["emit", "--run-id", "r1", "--stage", "seed", "-o", out],
            json.dumps({**body, "options": ["Pre-seed", "Seed", "Series A", "Series B"]}),
        )
        assert rc2 == 0, err2


# THE OTHER WRITER. `emit` was taught to carry an answered gate into history; `answer`
# was not, and it overwrites the answer in place. So the erasure closed through one door
# and stayed open through the door next to it:
#
#   answer "Stop review" -> answer again with "Proceed anyway" -> continue_if_rebuilt
#
# This is the same one-of-two-copies shape recorded twice already in this file.


def test_answering_an_already_answered_gate_is_refused() -> None:
    gs = _import_gate_state()
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "gate_state.json")
        body = {
            "gate_id": "out_of_scope_choice",
            "question": "?",
            "options": list(gs.CANONICAL_OPTIONS["out_of_scope_choice"]),
            "context_summary": "x",
        }
        _run(["emit", "--run-id", "r1", "--stage", "growth", "-o", path], json.dumps(body))
        rc, _, err = _run(["answer", "--file", path, "--answer", "Stop review", "--source", "founder"])
        assert rc == 0, err

        rc2, _, err2 = _run(
            ["answer", "--file", path, "--answer", "Proceed anyway (best-effort)", "--source", "founder"]
        )
        assert rc2 != 0, "an answered gate was re-answered in place, erasing the founder's decision"
        assert "already answered" in err2.lower()
        with open(path) as f:
            assert json.load(f)["answer"] == "Stop review", "the original answer was overwritten"


def test_re_answering_with_the_same_answer_is_idempotent() -> None:
    """A retried write must not fail the run: the gate round-trip is re-invoked, and the
    caller cannot always tell whether its previous call landed."""
    gs = _import_gate_state()
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "gate_state.json")
        body = {
            "gate_id": "stage_confirmation",
            "question": "?",
            "options": list(gs.CANONICAL_OPTIONS["stage_confirmation"]),
            "context_summary": "x",
        }
        _run(["emit", "--run-id", "r1", "--stage", "seed", "-o", path], json.dumps(body))
        _run(["answer", "--file", path, "--answer", "Looks right", "--source", "founder"])
        rc, _, err = _run(["answer", "--file", path, "--answer", "Looks right", "--source", "founder"])
        assert rc == 0, err


def test_a_pending_replacement_still_honours_an_earlier_stop() -> None:
    """`gate_action` returned `reask` for a pending gate before it looked at history, so
    re-emitting after a decline read as "just ask again" rather than "they already said no"."""
    gs = _import_gate_state()
    pending = _full_gate()
    del pending["answer"]
    del pending["answer_source"]
    pending["history"] = [
        {"gate_id": "out_of_scope_choice", "answer": "Stop review", "answer_source": "founder", "run_id": "r1"}
    ]
    assert gs.gate_action(pending) == "stop"


def test_emit_returns_the_payload_to_present_verbatim() -> None:
    """The canonical options are enforced on the FILE and the founder sees the PAYLOAD.

    SKILL.md retyped the `needs_input` block by hand, so a file containing "Stop review"
    could sit beside a displayed choice that omitted it — the validation guarantees what
    was recorded, not what was shown. `emit` now returns the payload to present, so the
    thing the founder reads is produced by the same code that validated it.
    """
    gs = _import_gate_state()
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "gate_state.json")
        body = {
            "gate_id": "out_of_scope_choice",
            "question": "This looks out of scope. What should I do?",
            "options": list(gs.CANONICAL_OPTIONS["out_of_scope_choice"]),
            "context_summary": "Detected: growth",
        }
        rc, stdout, err = _run(["emit", "--run-id", "r1", "--stage", "growth", "-o", out], json.dumps(body))
        assert rc == 0, err
        receipt = json.loads(stdout)
        payload = receipt.get("needs_input")
        assert payload, f"emit returned no needs_input payload: {receipt}"
        assert payload["options"] == list(gs.CANONICAL_OPTIONS["out_of_scope_choice"])
        assert payload["question"] == body["question"]
        assert payload["gate_state_path"] == os.path.abspath(out)
        assert payload["gate_id"] == "out_of_scope_choice"


def test_a_stage_pick_that_puts_the_deck_out_of_scope_is_not_confirmed_in_scope() -> None:
    """Choosing Growth at `stage_choice` and then confirming through `stage_confirmation`
    composed a Growth report at high confidence — the out-of-scope question, the only one
    offering `Stop review`, was never asked. The chain is checkable from the history."""
    gs = _import_gate_state()
    gate = _full_gate(answer="Looks right")
    gate["history"] = [{"gate_id": "stage_choice", "answer": "Growth", "answer_source": "founder", "run_id": "r1"}]
    assert gs.gate_action(gate) == "rebuild", (
        "an out-of-scope stage pick was confirmed by the in-scope gate, skipping the decline option"
    )
    # An in-scope pick confirmed the same way is fine.
    ok = _full_gate(answer="Looks right")
    ok["history"] = [{"gate_id": "stage_choice", "answer": "Seed", "answer_source": "founder", "run_id": "r1"}]
    assert gs.gate_action(ok) == "continue"


# ---------------------------------------------------------------------------
# THE WRITER MATRIX. Six review rounds closed the same class one path at a time —
# `emit`, then `answer`, then a hand-written file — because each fix was verified against
# the writer that had just been reported. §0.0 wrote down the remedy ("enumerate every
# writer and every reader") and the very next round fixed `emit` without checking
# `cmd_answer`, the only other writer in the same file.
#
# This is that enumeration, executable — but it is NOT the full cross-product, and calling
# it "every invariant against every writer" (as this comment first did) was an overclaim
# worth correcting rather than quietly satisfying. What it actually is:
#
#   * every invariant × one constructed record  (the parametrized refusal table below)
#   * one invariant × every writer              (emit+answer / hand-written / truncate+emit)
#
# The full product is not the goal, and mechanically generating
# `stage × confidence × gate × answer × source × history × run × writer` would produce
# thousands of cases, nearly all meaningless, and bury the rule set it is meant to expose.
# What makes the rule set reviewable is that `authorize()` is deny-by-default with a short
# allow list: a case nobody enumerated REFUSES. The writer axis is crossed against the one
# invariant where the writer genuinely varies the outcome — whether the record reached disk
# through the CLI at all — because the reader is the chokepoint either way.
# ---------------------------------------------------------------------------

_CANON_CONFIRM = ["Looks right", "Different stage", "Not sure — proceed anyway"]
_CANON_OOS = ["Stop review", "Different stage", "Proceed anyway (best-effort)"]


def _gs() -> Any:
    import importlib.util

    scripts = os.path.dirname(SCRIPT)
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    spec = importlib.util.spec_from_file_location("_gs_auth", os.path.join(scripts, "gate_state.py"))
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _record(**over: object) -> dict:
    """A gate as `emit` writes it, INCLUDING `confirmed_stage`.

    The gate now records which stage it was asked about, because nothing tied the two
    together: confirming Seed, rebuilding the profile to Series A, and composing against the
    original gate produced a clean Series A report. A fixture omitting it is a record no
    emitter makes.
    """
    rec: dict = {
        "metadata": {"run_id": "r1"},
        "gate_id": "stage_confirmation",
        "question": "?",
        "options": list(_CANON_CONFIRM),
        "context_summary": "x",
        "answer": "Looks right",
        "answer_source": "founder",
        "confirmed_stage": "seed",
    }
    rec.update(over)
    return rec


def _profile_for(stage: str = "seed", confidence: str = "high", run_id: str = "r1") -> dict:
    return {"metadata": {"run_id": run_id}, "detected_stage": stage, "confidence": confidence}


def test_authorize_permits_the_ordinary_confirmed_run() -> None:
    gs = _gs()
    verdict = gs.authorize(_record(), _profile_for(), "r1")
    assert verdict.permitted, verdict.reason


@pytest.mark.parametrize(
    ("label", "record", "profile"),
    [
        ("never answered", _record(answer=None), _profile_for()),
        ("answer outside the gate's options", _record(answer="Ship it"), _profile_for()),
        ("options the gate does not own", _record(options=["Looks right"]), _profile_for()),
        ("no answer_source", _record(answer_source=None), _profile_for()),
        (
            "auto-satisfied on a gate that may not be",
            _record(
                gate_id="out_of_scope_choice",
                options=list(_CANON_OOS),
                answer="Proceed anyway (best-effort)",
                answer_source="auto_satisfied",
            ),
            _profile_for(),
        ),
        (
            "the founder declined",
            _record(gate_id="out_of_scope_choice", options=list(_CANON_OOS), answer="Stop review"),
            _profile_for(),
        ),
        (
            "a decline earlier in this run",
            _record(
                history=[
                    {
                        "gate_id": "out_of_scope_choice",
                        "answer": "Stop review",
                        "answer_source": "founder",
                        "run_id": "r1",
                    }
                ]
            ),
            _profile_for(),
        ),
        ("an intermediate answer", _record(answer="Different stage"), _profile_for()),
        (
            "an intermediate stage pick",
            _record(gate_id="stage_choice", options=["Pre-seed", "Seed", "Series A", "Series B"], answer="Seed"),
            _profile_for(),
        ),
        (
            "proceed-anyway without the rebuild",
            _record(answer="Not sure — proceed anyway"),
            _profile_for(confidence="high"),
        ),
        (
            "proceed-anyway with a prior run's low profile",
            _record(answer="Not sure — proceed anyway"),
            _profile_for(confidence="low", run_id="older"),
        ),
        ("a gate from another run", _record(metadata={"run_id": "older"}), _profile_for()),
        # THE LIVE DEFECT this consolidation was written for: an out-of-scope deck confirmed
        # through the in-scope gate. `stage_confirmation` never offers "Stop review", so the
        # founder is told their deck is out of scope by a question giving them no way to
        # decline — and self-answering it needs no founder at all.
        ("out-of-scope deck confirmed by the in-scope gate", _record(), _profile_for(stage="growth")),
        (
            "out-of-scope deck self-confirmed",
            _record(answer_source="auto_satisfied"),
            _profile_for(stage="series_b"),
        ),
    ],
)
def test_authorize_refuses_every_way_a_gate_can_fail(label: str, record: dict, profile: dict) -> None:
    gs = _gs()
    clean = {k: v for k, v in record.items() if v is not None}
    verdict = gs.authorize(clean, profile, "r1")
    assert not verdict.permitted, f"authorize permitted a gate that is {label}"
    assert verdict.reason, f"{label}: refused with no reason"


@pytest.mark.parametrize("writer", ["emit_then_answer", "hand_written", "truncated_then_emitted"])
def test_the_reader_refuses_an_out_of_scope_confirmation_however_it_was_written(writer: str) -> None:
    """One invariant, every writer. The point is that the answer does not depend on which
    path produced the file — including a path that bypasses the CLI entirely."""
    gs = _gs()
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "gate_state.json")
        body = {
            "gate_id": "stage_confirmation",
            "question": "?",
            "options": list(_CANON_CONFIRM),
            "context_summary": "Detected: growth",
        }
        if writer == "emit_then_answer":
            _run(["emit", "--run-id", "r1", "--stage", "seed", "-o", path], json.dumps(body))
            _run(["answer", "--file", path, "--answer", "Looks right", "--source", "auto_satisfied"])
        elif writer == "hand_written":
            with open(path, "w") as f:
                json.dump(
                    {**body, "metadata": {"run_id": "r1"}, "answer": "Looks right", "answer_source": "founder"}, f
                )
        else:
            # A truncated prior is now REFUSED by `emit` rather than treated as absent (see
            # test_a_truncated_gate_file_does_not_erase_a_decline), so this writer reaches
            # the reader by writing the whole record directly — which is the case the matrix
            # is actually about.
            with open(path, "w") as f:
                f.write("{ truncated")
            with open(path, "w") as f:
                json.dump(
                    {
                        **body,
                        "metadata": {"run_id": "r1"},
                        "confirmed_stage": "growth",
                        "answer": "Looks right",
                        "answer_source": "founder",
                    },
                    f,
                )

        with open(path) as f:
            record = json.load(f)
        verdict = gs.authorize(record, _profile_for(stage="growth"), "r1")
        assert not verdict.permitted, (
            f"a {writer} out-of-scope confirmation was authorized; the founder was never offered a decline"
        )


def test_an_out_of_scope_profile_is_never_the_thing_being_graded() -> None:
    """REWRITTEN twice, and the second correction is the instructive one.

    The rule is about the profile the report is GRADED on, not about what the gate asked.
    An out-of-scope gate is legitimate and necessary — it is how the founder is offered
    "Stop review" — and its "Proceed anyway" answer resolves to series_a/low. What must
    never happen is a REPORT graded at series_b or growth.

    The previous version of this test asserted that an `out_of_scope_choice` gate cannot
    authorize anything, using a fabricated in-scope `confirmed_stage`. That conflated the
    question asked with the stage graded, and the rule it pinned refused the documented
    flow outright.
    """
    gs = _gs()
    for stage in ("growth", "series_b"):
        # A confirmation gate asked about an out-of-scope stage is refused at the writer,
        # and refused here too if one reaches the reader by another route.
        assert not gs.authorize(_asked(stage), _prof(stage, "high"), "r1").permitted
        # And the out-of-scope gate does not authorize a report still graded out of scope.
        assert not gs.authorize(_asked(stage, "out_of_scope_choice"), _prof(stage, "low"), "r1").permitted, (
            f"a report graded at {stage} was authorized"
        )


def test_a_pending_gate_replaced_by_another_emit_leaves_a_trace() -> None:
    """`emit` carried only ANSWERED priors into history, so a pending out-of-scope question
    replaced by a different emit vanished without trace. That is the one genuinely log-like
    property the record lacked: what the founder was ASKED is part of the history, not only
    what they answered."""
    gs = _gs()
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "gate_state.json")
        oos = {
            "gate_id": "out_of_scope_choice",
            "question": "This looks out of scope. What should I do?",
            "options": list(gs.CANONICAL_OPTIONS["out_of_scope_choice"]),
            "context_summary": "x",
        }
        _run(["emit", "--run-id", "r1", "--stage", "growth", "-o", path], json.dumps(oos))
        confirm = {
            "gate_id": "stage_confirmation",
            "question": "?",
            "options": list(gs.CANONICAL_OPTIONS["stage_confirmation"]),
            "context_summary": "x",
        }
        _run(["emit", "--run-id", "r1", "--stage", "seed", "-o", path], json.dumps(confirm))
        with open(path) as f:
            written = json.load(f)
        history = written.get("history", [])
        assert len(history) == 1, history
        assert history[0]["gate_id"] == "out_of_scope_choice"
        assert history[0].get("answer") is None
        assert history[0].get("superseded") is True, history[0]


# ---------------------------------------------------------------------------
# DENY BY DEFAULT. `authorize` was built permissive-with-refusals: it walked a list of
# ways to say no and permitted whatever fell through. That shape is why a PRESENCE check
# slipped in — "an out_of_scope_choice appears in history" was written where "the founder
# answered it, and said proceed" was meant, and nothing failed, because falling through is
# the success path.
#
# The table below is the whole allow list. Anything not in it is refused, so the next
# missing predicate costs a refusal rather than a bypass.
# ---------------------------------------------------------------------------


def _oos_history(answer: str | None, source: str | None = "founder", **extra: object) -> list[dict]:
    entry: dict = {"gate_id": "out_of_scope_choice", "run_id": "r1"}
    if answer is not None:
        entry["answer"] = answer
    if source is not None:
        entry["answer_source"] = source
    entry.update(extra)
    return [entry]


@pytest.mark.parametrize(
    ("label", "history"),
    [
        ("pending, superseded by another emit", _oos_history(None, None, superseded=True)),
        ("pending with no answer at all", _oos_history(None, None)),
        ("answered 'Different stage' — a rebuild, not consent", _oos_history("Different stage")),
        ("answered 'Stop review' — the opposite of consent", _oos_history("Stop review")),
        ("self-answered 'Proceed anyway'", _oos_history("Proceed anyway (best-effort)", "auto_satisfied")),
        ("consent recorded with no source", _oos_history("Proceed anyway (best-effort)", None)),
        (
            "consent from a different run",
            [
                {
                    "gate_id": "out_of_scope_choice",
                    "answer": "Proceed anyway (best-effort)",
                    "answer_source": "founder",
                    "run_id": "older",
                }
            ],
        ),
    ],
)
def test_only_an_answered_founder_proceed_satisfies_out_of_scope_consent(label: str, history: list[dict]) -> None:
    """`emit` deliberately writes PENDING superseded gates into history, so "an
    out_of_scope_choice is present" and "the founder consented" diverged the moment both
    features landed — in the same commit."""
    gs = _gs()
    record = _record(history=history)
    verdict = gs.authorize(record, _profile_for(stage="growth"), "r1")
    assert not verdict.permitted, f"out-of-scope consent was inferred from: {label}"


def test_the_profile_must_belong_to_this_run_for_an_ordinary_confirmation_too() -> None:
    """Run parity was checked only on the rebuild branch, so an ordinary `Looks right`
    composed happily against a stage profile left by an earlier review."""
    gs = _gs()
    foreign = {"metadata": {"run_id": "older"}, "detected_stage": "seed", "confidence": "high"}
    assert not gs.authorize(_record(), foreign, "r1").permitted


def test_auto_satisfy_needs_the_confident_detection_it_claims() -> None:
    """SKILL.md's auto-satisfy branch requires the founder's Step 1 answer to MATCH a
    confident detection. Whether they answered Step 1 is not in the artifact and cannot be
    checked — but the detection's confidence is, and it was not being checked. Enforce the
    checkable half rather than neither."""
    gs = _gs()
    low = {"metadata": {"run_id": "r1"}, "detected_stage": "seed", "confidence": "low"}
    assert not gs.authorize(_record(answer_source="auto_satisfied"), low, "r1").permitted
    # A founder answering the same gate on the same profile is fine: they were asked.
    assert gs.authorize(_record(answer_source="founder"), low, "r1").permitted


def test_a_hand_written_superseded_consent_is_still_refused() -> None:
    """`emit` marks an entry superseded only when it is UNANSWERED, so the superseded
    check is subsumed by the answer check for anything the CLI produces — mutation showed
    that by removing it with the suite still green. It is reachable through the writer
    the matrix exists for: a file written directly, carrying both an answer and the
    superseded mark. That record is not something any emitter made, and the reader is
    where that has to be caught."""
    gs = _gs()
    record = _record(
        history=[
            {
                "gate_id": "out_of_scope_choice",
                "answer": "Proceed anyway (best-effort)",
                "answer_source": "founder",
                "run_id": "r1",
                "superseded": True,
            }
        ]
    )
    assert not gs.authorize(record, _profile_for(stage="growth"), "r1").permitted


def test_an_unrecognised_gate_action_denies(monkeypatch: pytest.MonkeyPatch) -> None:
    """A future `gate_action` value must refuse rather than fall through.

    I removed this guard on the reasoning that the allow table subsumed it. It does not: the
    table keys on (gate_id, answer), so an unrecognised ACTION falls straight through to a
    matching row — verified by probe, which is why the branch is back. The table constrains
    what the answer IS; the action allowlist constrains what the run may DO with it.
    """
    gs = _gs()
    monkeypatch.setattr(gs, "gate_action", lambda _gate: "provisionally_fine")
    verdict = gs.authorize(_record(), _profile_for(), "r1")
    assert not verdict.permitted, "an unrecognised action was treated as permission"


# ---------------------------------------------------------------------------
# THE CLOSED TABLE. The previous version was still refusal-predicates-then-permit, and a
# probe refuted the claim that "a case nobody enumerated now refuses": a hand-written
# `gate_id: frobnicate` carrying the globally-recognised answer "Not sure — proceed anyway"
# authorized a clean report. `gate_action` classified the ANSWER without reference to the
# gate, and the bottom of `authorize` was an unconditional permit.
#
# So the permitted set is now written out. Three rows, each a (gate_id, answer) pair with
# the profile state it requires. Nothing else authorizes anything.
#
# `_out_of_scope_consent` is GONE, not fixed. Every legitimate path through SKILL.md either
# exits on "Stop review" or rebuilds to series_a at low confidence (SKILL.md:531-533), so an
# out-of-scope profile reaching compose is always wrong regardless of what history says.
# Requiring the composed profile to be in scope replaces a four-property consent search
# with one check, and closes the case where historical consent skipped its own rebuild.
# ---------------------------------------------------------------------------

_IN_SCOPE = {"metadata": {"run_id": "r1"}, "detected_stage": "seed", "confidence": "high"}


def _bound(stage: str = "seed", **over: object) -> dict:
    """A gate that records which stage it confirmed — see `confirmed_stage`."""
    return _record(confirmed_stage=stage, **over)


@pytest.mark.parametrize(
    ("label", "gate", "profile"),
    [
        (
            "stage_confirmation / Looks right",
            _bound(),
            {"metadata": {"run_id": "r1"}, "detected_stage": "seed", "confidence": "high"},
        ),
        (
            "stage_confirmation / Not sure — proceed anyway, after the low rebuild",
            _bound(answer="Not sure — proceed anyway"),
            {"metadata": {"run_id": "r1"}, "detected_stage": "seed", "confidence": "low"},
        ),
        (
            # CORRECTED: this fabricated `confirmed_stage="series_a"` on an
            # `out_of_scope_choice` gate — a record no writer can produce, since that gate
            # is emitted only for out-of-scope stages. It made a rule that refused the
            # documented flow look correct. The gate asks about the OUT-OF-SCOPE stage; the
            # profile is what the answer rebuilt it to.
            "out_of_scope_choice asked about growth / Proceed anyway, rebuilt to series_a low",
            _record(
                gate_id="out_of_scope_choice",
                options=["Stop review", "Different stage", "Proceed anyway (best-effort)"],
                answer="Proceed anyway (best-effort)",
                confirmed_stage="growth",
            ),
            {"metadata": {"run_id": "r1"}, "detected_stage": "series_a", "confidence": "low"},
        ),
    ],
)
def test_the_allow_table_is_exactly_these_rows(label: str, gate: dict, profile: dict) -> None:
    gs = _gs()
    verdict = gs.authorize(gate, profile, "r1")
    assert verdict.permitted, f"a permitted row was refused ({label}): {verdict.reason}"


@pytest.mark.parametrize(
    ("label", "gate", "profile"),
    [
        # THE PROBE THAT REFUTED THE PREVIOUS CLAIM.
        (
            "an unknown gate_id riding a recognised answer",
            _bound(gate_id="frobnicate", answer="Not sure — proceed anyway"),
            {"metadata": {"run_id": "r1"}, "detected_stage": "seed", "confidence": "low"},
        ),
        # The composed profile is out of scope, whatever the history says.
        (
            "an out-of-scope profile with historical consent",
            _bound(
                stage="growth",
                history=[
                    {
                        "gate_id": "out_of_scope_choice",
                        "answer": "Proceed anyway (best-effort)",
                        "answer_source": "founder",
                        "run_id": "r1",
                    }
                ],
            ),
            {"metadata": {"run_id": "r1"}, "detected_stage": "growth", "confidence": "high"},
        ),
        # The gate confirmed a different stage than the one being graded.
        (
            "the profile was rebuilt after the gate confirmed it",
            _bound(stage="seed"),
            {"metadata": {"run_id": "r1"}, "detected_stage": "series_a", "confidence": "high"},
        ),
        (
            "a gate that records no stage at all",
            {k: v for k, v in _record().items() if k != "confirmed_stage"},
            _IN_SCOPE,
        ),
        # Right pair, wrong profile state.
        (
            "'Not sure' without the low rebuild",
            _bound(answer="Not sure — proceed anyway"),
            {"metadata": {"run_id": "r1"}, "detected_stage": "seed", "confidence": "high"},
        ),
        (
            "out-of-scope proceed left on a non-series_a stage",
            _record(
                gate_id="out_of_scope_choice",
                options=["Stop review", "Different stage", "Proceed anyway (best-effort)"],
                answer="Proceed anyway (best-effort)",
                confirmed_stage="seed",
            ),
            {"metadata": {"run_id": "r1"}, "detected_stage": "seed", "confidence": "low"},
        ),
        # Answers that are not in the table at all.
        ("'Different stage' is not a terminal row", _bound(answer="Different stage"), _IN_SCOPE),
        (
            "a stage_choice pick is not a terminal row",
            _record(
                gate_id="stage_choice",
                options=["Pre-seed", "Seed", "Series A", "Series B"],
                answer="Seed",
                confirmed_stage="seed",
            ),
            _IN_SCOPE,
        ),
    ],
)
def test_everything_outside_the_allow_table_is_refused(label: str, gate: dict, profile: dict) -> None:
    gs = _gs()
    verdict = gs.authorize(gate, profile, "r1")
    assert not verdict.permitted, f"authorize permitted a row that is not in the table: {label}"
    assert verdict.reason


def test_history_reduces_in_order_so_a_corrected_stage_is_not_held_against_the_run() -> None:
    """`gate_action` scanned history existentially, so an out-of-scope pick the founder
    later CORRECTED still forced a rebuild forever — a multi-round correction could never
    finish. Transitions are ordered; the last stage pick is the operative one."""
    gs = _gs()
    corrected = _bound(
        history=[
            {"gate_id": "stage_choice", "answer": "Growth", "answer_source": "founder", "run_id": "r1"},
            {"gate_id": "stage_choice", "answer": "Seed", "answer_source": "founder", "run_id": "r1"},
        ]
    )
    assert gs.gate_action(corrected) == "continue", "a corrected stage pick still forced a rebuild"
    # And the reverse order still refuses: the LAST pick is out of scope.
    reversed_order = _bound(
        history=[
            {"gate_id": "stage_choice", "answer": "Seed", "answer_source": "founder", "run_id": "r1"},
            {"gate_id": "stage_choice", "answer": "Growth", "answer_source": "founder", "run_id": "r1"},
        ]
    )
    assert gs.gate_action(reversed_order) == "rebuild"


def test_a_stop_is_absorbing_whatever_follows_it() -> None:
    """Ordered reduction must not let a later answer overwrite a decline."""
    gs = _gs()
    declined = _bound(
        history=[
            {"gate_id": "out_of_scope_choice", "answer": "Stop review", "answer_source": "founder", "run_id": "r1"},
            {"gate_id": "stage_choice", "answer": "Seed", "answer_source": "founder", "run_id": "r1"},
        ]
    )
    assert gs.gate_action(declined) == "stop"


def test_the_gate_id_enum_is_validated_at_read_time() -> None:
    gs = _gs()
    problems = gs.validate_answered_gate(_bound(gate_id="frobnicate"))
    assert any("frobnicate" in p for p in problems), problems


# ---------------------------------------------------------------------------
# TRANSITIONS, NOT TERMINAL PAIRS. The table keyed on (gate_id, answer) plus the FINAL
# profile, and required the stage the gate asked about to equal the stage being graded.
# That is wrong for the one path where the answer's whole purpose is to CHANGE the stage:
# an out-of-scope gate asks about growth, and "Proceed anyway" rebuilds to series_a. So the
# documented flow was refused — I shipped a false refusal on a working path, and my own
# positive tests hid it by fabricating `confirmed_stage="series_a"` on an
# `out_of_scope_choice` gate, a record that cannot exist because that gate is only emitted
# for out-of-scope stages.
#
# A row is therefore (asked stage, answer, source) -> (resulting stage, confidence).
# ---------------------------------------------------------------------------


def _asked(stage: str, gate_id: str = "stage_confirmation", **over: Any) -> dict[str, Any]:
    options = _CANON_OOS if gate_id == "out_of_scope_choice" else _CANON_CONFIRM
    base: dict[str, Any] = {
        "metadata": {"run_id": "r1"},
        "gate_id": gate_id,
        "question": "?",
        "options": list(options),
        "context_summary": "x",
        "answer": "Looks right" if gate_id == "stage_confirmation" else "Proceed anyway (best-effort)",
        "answer_source": "founder",
        "confirmed_stage": stage,
    }
    base.update(over)
    return base


def _prof(stage: str, confidence: str, run_id: str = "r1") -> dict:
    return {"metadata": {"run_id": run_id}, "detected_stage": stage, "confidence": confidence}


@pytest.mark.parametrize("asked", ["growth", "series_b"])
def test_the_documented_out_of_scope_path_is_authorized(asked: str) -> None:
    """The regression this block exists for. SKILL.md:535 rebuilds to series_a at low
    confidence after the founder says proceed; the gate necessarily asked about the
    out-of-scope stage, because that is the only stage for which it is emitted."""
    gs = _gs()
    gate = _asked(asked, "out_of_scope_choice")
    verdict = gs.authorize(gate, _prof("series_a", "low"), "r1")
    assert verdict.permitted, f"the documented out-of-scope path was refused: {verdict.reason}"


def test_the_out_of_scope_answer_must_land_on_the_stage_it_promises() -> None:
    """The transition is the check: proceed-anyway resolves to series_a/low and nothing
    else, so the rebuild cannot quietly land somewhere more favourable."""
    gs = _gs()
    for stage, confidence in (("seed", "low"), ("series_a", "high"), ("growth", "low")):
        verdict = gs.authorize(_asked("growth", "out_of_scope_choice"), _prof(stage, confidence), "r1")
        assert not verdict.permitted, f"out-of-scope proceed landed on {stage}/{confidence}"


def test_an_out_of_scope_gate_about_an_in_scope_stage_is_incoherent() -> None:
    """The record my own tests fabricated. `out_of_scope_choice` is emitted only for
    series_b/growth, so one claiming to have asked about seed was never produced by any
    writer and must not be treated as evidence of anything."""
    gs = _gs()
    assert not gs.authorize(_asked("seed", "out_of_scope_choice"), _prof("series_a", "low"), "r1").permitted


def test_an_in_scope_confirmation_still_requires_the_stage_to_be_unchanged() -> None:
    """The binding that closed the round-eight defect stays for the gates whose answer does
    NOT change the stage: confirming Seed cannot authorize a Series A report."""
    gs = _gs()
    assert gs.authorize(_asked("seed"), _prof("seed", "high"), "r1").permitted
    assert not gs.authorize(_asked("seed"), _prof("series_a", "high"), "r1").permitted


def test_an_out_of_scope_gate_cannot_be_emitted_for_an_in_scope_stage() -> None:
    """Refused at the writer too, so the incoherent record is never produced."""
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "gate_state.json")
        body = {
            "gate_id": "out_of_scope_choice",
            "question": "?",
            "options": list(_CANON_OOS),
            "context_summary": "x",
        }
        rc, _, err = _run(["emit", "--run-id", "r1", "--stage", "seed", "-o", out], json.dumps(body))
        assert rc != 0, "an out-of-scope gate was emitted about an in-scope stage"
        assert "seed" in err


def test_the_presented_payload_states_the_stage_it_will_authorize() -> None:
    """`--stage` was a hidden token: the founder saw a caller-written `context_summary` and
    the artifact carried something else. Probed — emitting `--stage series_a` while showing
    "Detected stage: Seed" let a `Looks right` authorize a Series A report.

    The payload now carries the stage, and the producer states it, so the thing the founder
    reads and the thing that authorizes cannot disagree."""
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "gate_state.json")
        body = {
            "gate_id": "stage_confirmation",
            "question": "Does this stage detection look right?",
            "options": list(_CANON_CONFIRM),
            "context_summary": "Detected stage: Seed",
        }
        rc, stdout, err = _run(["emit", "--run-id", "r1", "--stage", "series_a", "-o", out], json.dumps(body))
        assert rc == 0, err
        payload = json.loads(stdout)["needs_input"]
        assert payload["confirmed_stage"] == "series_a"
        assert "series_a" in payload["context_summary"], (
            f"the founder-visible summary does not state the stage being confirmed: {payload['context_summary']!r}"
        )


def test_an_unanswered_out_of_scope_question_does_not_become_consent_by_rebuilding() -> None:
    """The supported sequence: emit the out-of-scope question, never answer it, rebuild to
    series_a/low anyway, emit a confirmation, answer that. The unanswered question is
    recorded as superseded and skipped by reduction, so a founder who was never given
    "Stop review" ends up with a report.

    Reaching series_a/low from an out-of-scope deck is only legitimate BECAUSE the founder
    said proceed, so the run has to show that they did."""
    gs = _gs()
    gate = _asked(
        "series_a",
        history=[{"gate_id": "out_of_scope_choice", "run_id": "r1", "superseded": True}],
    )
    verdict = gs.authorize(gate, _prof("series_a", "low"), "r1")
    assert not verdict.permitted, "an unanswered out-of-scope question was rebuilt past"
    assert "never answered" in verdict.reason or "declin" in verdict.reason, verdict.reason


def test_an_answered_out_of_scope_question_permits_the_rebuilt_run() -> None:
    """The counter-test: once they actually answered, the follow-up confirmation is fine."""
    gs = _gs()
    gate = _asked(
        "series_a",
        history=[
            {
                "gate_id": "out_of_scope_choice",
                "answer": "Proceed anyway (best-effort)",
                "answer_source": "founder",
                "run_id": "r1",
            }
        ],
    )
    assert gs.authorize(gate, _prof("series_a", "low"), "r1").permitted


def test_a_truncated_gate_file_does_not_erase_a_decline() -> None:
    """Gate writes truncate and rewrite in place, and `_read_existing` treats unparseable
    JSON as absent — deliberately, so a corrupt file cannot strand a run. Together that is
    an erasure path: Stop review, truncate, emit fresh, answer, authorized.

    The write is atomic now, so a truncated file is not a state the writer produces; and a
    record that IS unreadable is no longer silently treated as a clean slate."""
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "gate_state.json")
        oos = {
            "gate_id": "out_of_scope_choice",
            "question": "?",
            "options": list(_CANON_OOS),
            "context_summary": "x",
        }
        _run(["emit", "--run-id", "r1", "--stage", "growth", "-o", path], json.dumps(oos))
        _run(["answer", "--file", path, "--answer", "Stop review", "--source", "founder"])
        with open(path, "w") as f:
            f.write("{ truncated")
        confirm = {
            "gate_id": "stage_confirmation",
            "question": "?",
            "options": list(_CANON_CONFIRM),
            "context_summary": "x",
        }
        rc, _, err = _run(["emit", "--run-id", "r1", "--stage", "seed", "-o", path], json.dumps(confirm))
        assert rc != 0, "a truncated gate file was emitted over, erasing the decline it held"
        assert "unreadable" in err.lower() or "corrupt" in err.lower(), err


def test_stage_choice_options_must_be_four_distinct_stages() -> None:
    """Membership plus a length of four accepted four duplicate `Seed`s — a gate that hides
    every alternative while satisfying every check."""
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "gate_state.json")
        body = {"gate_id": "stage_choice", "question": "?", "context_summary": "x"}
        rc, _, err = _run(
            ["emit", "--run-id", "r1", "--stage", "seed", "-o", out],
            json.dumps({**body, "options": ["Seed", "Seed", "Seed", "Seed"]}),
        )
        assert rc != 0, "four duplicate options were accepted"
        assert "distinct" in err.lower() or "duplicate" in err.lower(), err
        rc_ok, _, err_ok = _run(
            ["emit", "--run-id", "r1", "--stage", "seed", "-o", out],
            json.dumps({**body, "options": ["Pre-seed", "Seed", "Series A", "Series B"]}),
        )
        assert rc_ok == 0, err_ok
