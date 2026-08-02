from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

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
            "options": ["Looks right", "Different stage"],
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
        rc, _, err = _run(["answer", "--file", path, "--answer", "Looks right"])
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
        rc, _, err = _run(["answer", "--file", path, "--answer", "Looks right"])
        assert rc == 1
        assert "not valid json" in err.lower()
        assert "Traceback" not in err


def test_gate_state_answer_rejects_non_dict_json() -> None:
    """A gate file that is valid JSON but not an object -> clean error, no AttributeError."""
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "gate_state.json")
        with open(path, "w") as f:
            f.write("[1, 2, 3]")
        rc, _, err = _run(["answer", "--file", path, "--answer", "Looks right"])
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
        rc, stdout, err = _run(["answer", "--file", path, "--answer", "Looks right", "--pretty"])
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
        rc, _, err = _run(["answer", "--file", path, "--answer", "Unicorn"])
        assert rc != 0
        assert "Unicorn" in err
