from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from typing import Any

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
        rc, _, err = _run(["emit", "--run-id", "r1", "-o", out, "--pretty"], json.dumps(body))
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
        rc, _, err = _run(["emit", "--run-id", "r1", "-o", out], json.dumps(body))
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
        rc, _, err = _run(["emit", "--run-id", "r1", "-o", out], json.dumps(body))
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
        rc, _, err = _run(["emit", "--run-id", "r1", "-o", out], json.dumps(body))
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
        rc, _, err = _run(["emit", "--run-id", "r1", "-o", out], json.dumps(body))
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
        rc, _, _ = _run(["emit", "--run-id", "r1", "-o", os.path.join(review_dir, "gate_state.json")], json.dumps(body))
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
        rc, _, err = _run(["emit", "--run-id", "r1", "-o", path], json.dumps(body))
        assert rc == 0, err
        rc, _, err = _run(["answer", "--file", path, "--answer", "Different stage", "--source", "founder"])
        assert rc == 0, err

        rc, _, err = _run(["emit", "--run-id", "r1", "-o", path], json.dumps(body))
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
        _run(["emit", "--run-id", "r1", "-o", path], json.dumps(oos))
        _run(["answer", "--file", path, "--answer", "Stop review", "--source", "founder"])

        stage = {
            "gate_id": "stage_confirmation",
            "question": "?",
            "options": list(gs.CANONICAL_OPTIONS["stage_confirmation"]),
            "context_summary": "x",
        }
        _run(["emit", "--run-id", "r1", "-o", path], json.dumps(stage))
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
        rc, _, err = _run(["emit", "--run-id", "r1", "-o", out], json.dumps(rigged))
        assert rc != 0, "emit wrote a gate that never offers the option to decline"
        assert "Stop review" in err or "options" in err
        assert not os.path.exists(out)

        ok = dict(rigged, options=list(gs.CANONICAL_OPTIONS["out_of_scope_choice"]))
        rc_ok, _, err_ok = _run(["emit", "--run-id", "r1", "-o", out], json.dumps(ok))
        assert rc_ok == 0, err_ok


def test_emit_holds_stage_choice_to_four_stage_options() -> None:
    """`AskUserQuestion` renders at most four, and SKILL.md offers exactly four — the enum
    minus the stage just rejected. Three would hide a stage the founder may want."""
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "gate_state.json")
        body = {"gate_id": "stage_choice", "question": "?", "context_summary": "x"}
        rc, _, err = _run(["emit", "--run-id", "r1", "-o", out], json.dumps({**body, "options": ["Seed"]}))
        assert rc != 0, "a one-option stage_choice was written"
        rc2, _, err2 = _run(
            ["emit", "--run-id", "r1", "-o", out],
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
        _run(["emit", "--run-id", "r1", "-o", path], json.dumps(body))
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
        _run(["emit", "--run-id", "r1", "-o", path], json.dumps(body))
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
        rc, stdout, err = _run(["emit", "--run-id", "r1", "-o", out], json.dumps(body))
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
