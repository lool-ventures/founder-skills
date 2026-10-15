"""deck-review's CHECKLIST prompt is printed by a script, not copied out of SKILL.md.

`dr_dispatch_prompt.py checklist` prints the prompt from identifiers alone, and only once this run's
`slide_reviews.json` exists with a read token: a CHECKLIST dispatched beside SLIDE_REVIEWS has no printed
prompt to be. It never reads that token: checklist.py's proof that the grader read the slide reviews is
that only a reader of the file has it.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

PLUGIN = Path(__file__).resolve().parents[1]
SCRIPTS = PLUGIN / "skills" / "deck-review" / "scripts"
GEN = SCRIPTS / "dr_dispatch_prompt.py"
HOOK = PLUGIN / "scripts" / "dispatch_prompt_check.py"
GOLDEN = PLUGIN / "tests" / "fixtures" / "dispatch_prompts" / "deck-review.checklist.txt"
SR_FIXTURE = PLUGIN / "tests" / "fixtures" / "deck-review" / "slide_reviews.json"
ROOT_MARK = "@PLUGIN_ROOT@"
END = "Do NOT write any file other than OUTPUT_PATH.\n"
RUN = "R"


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _slide_reviews(review: Path, run_id: str = RUN) -> str:
    """Write `<review>/slide_reviews.json` through the REAL slide_reviews.py and return its token, read back
    from the written file, never recomputed here."""
    review.mkdir(parents=True, exist_ok=True)
    body = json.loads(SR_FIXTURE.read_text(encoding="utf-8"))
    body.pop("metadata", None)
    recon = review / f"sr-reconciliation-{run_id}.json"
    recon.write_text(json.dumps({"status": "checked", "metadata": {"run_id": run_id}}), encoding="utf-8")
    out = review / "slide_reviews.json"
    r = subprocess.run(
        [sys.executable, str(SCRIPTS / "slide_reviews.py"), "--run-id", run_id, "-o", str(out)]
        + ["--reconciliation", str(recon)],
        input=json.dumps(body),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert r.returncode == 0, r.stderr
    token = json.loads(out.read_text(encoding="utf-8"))["metadata"]["read_token"]
    assert isinstance(token, str) and token
    return token


def _review(tmp_path: Path, *, tokened: bool = True) -> Path:
    d = tmp_path / "review"
    d.mkdir(exist_ok=True)
    if tokened:
        _slide_reviews(d)
    return d


def _gen(review: Path, *extra: str, cwd: Path, run_id: str = RUN) -> subprocess.CompletedProcess[str]:
    args = ["checklist", "--run-id", run_id, "--handoff-agent", "/agent/handoff/R", "--review-dir-agent"]
    args += ["/agent/review", "--review-dir", str(review)]
    return subprocess.run(
        [sys.executable, str(GEN), *args, *extra], capture_output=True, text=True, timeout=30, cwd=cwd
    )


def _bind(review: Path, run_id: str, seq: int = 1) -> None:
    ref = review / "handoff" / run_id / "run_ref.json"
    ref.parent.mkdir(parents=True, exist_ok=True)
    ref.write_text(json.dumps({"run_id": run_id, "bound_seq": seq}), encoding="utf-8")


# --- the printed prompt ------------------------------------------------------------------------------


def test_the_prompt_is_the_golden_text(tmp_path: Path) -> None:
    """Off a /sessions tree (CLI, cloud): the golden text, the root placeholder set to the generator's own
    folder. A prompt change is a deliberate re-copy of the fixture; a reviewer diffs it against the Step 5
    template it was moved from (the tail reordered so the closing line is last)."""
    r = _gen(_review(tmp_path), cwd=tmp_path)
    assert r.returncode == 0 and r.stderr == "", r.stderr
    golden = GOLDEN.read_text(encoding="utf-8")
    assert golden.count(ROOT_MARK) == 1
    assert r.stdout == golden.replace(ROOT_MARK, str(PLUGIN))


def test_the_prompt_ends_with_the_hooks_closing_line_once(tmp_path: Path) -> None:
    out = _gen(_review(tmp_path), cwd=tmp_path).stdout
    hook_end = _load(HOOK, "hook_end_dr").END
    assert END.strip() == hook_end
    assert out.endswith(END) and out.count(hook_end) == 1
    assert out.startswith("CONTEXT: CHECKLIST\nOUTPUT_PATH: /agent/handoff/R/checklist_output.json\nRUN_ID: R\n")
    assert "<" + "REVIEW_DIR_AGENT>" not in out and "<RUN_ID>" not in out and "<HANDOFF_AGENT>" not in out
    assert out.splitlines()[0] == _load(GEN, "dr_ctx")._CHECKLIST_CONTEXT


def test_on_a_session_tree_the_reference_is_named_by_its_tail() -> None:
    mod = _load(GEN, "dr_gen_session")
    out = mod.checklist(run_id="R", handoff_agent="/h", review_dir_agent="/a", session_tree=True)
    assert "the file ending skills/deck-review/references/checklist-criteria.md" in out
    assert "/skills/deck-review/references/" not in out
    assert mod._POINTER.strip() in out and mod._FALLBACK.strip() not in out
    assert out.endswith(END)


def test_the_agent_body_carries_the_full_reference_path() -> None:
    """The session-tree pointer sends the sub-agent to the full path its CHECKLIST section gives."""
    text = (PLUGIN / "agents" / "deck-review.md").read_text(encoding="utf-8")
    section = text[text.index("For `CHECKLIST`:") :]
    assert "`${CLAUDE_PLUGIN_ROOT}/skills/deck-review/references/checklist-criteria.md`" in section[:400]


# --- the Step 4 precondition --------------------------------------------------------------------------


def _write(review: Path, value: Any) -> None:
    review.mkdir(parents=True, exist_ok=True)
    text = value if isinstance(value, str) else json.dumps(value)
    (review / "slide_reviews.json").write_text(text, encoding="utf-8")


_NOT_USABLE = {
    "no file": None,
    "bad JSON": "{not json",
    "not an object": [1, 2],
    "a skipped stub": {"skipped": True, "metadata": {"run_id": RUN, "read_token": "abcdef012345"}},
    "another run's": {"reviews": [], "metadata": {"run_id": "OTHER", "read_token": "abcdef012345"}},
    "no token": {"reviews": [], "metadata": {"run_id": RUN}},
}


@pytest.mark.parametrize("case", sorted(_NOT_USABLE))
def test_no_prompt_until_this_runs_slide_reviews_carry_a_token(tmp_path: Path, case: str) -> None:
    review = tmp_path / "review"
    review.mkdir()
    if _NOT_USABLE[case] is not None:
        _write(review, _NOT_USABLE[case])
    r = _gen(review, cwd=tmp_path)
    assert r.returncode == 1, (case, r.stdout, r.stderr)
    data = json.loads(r.stdout)
    assert data["status"] == "rejected" and data["code"] == "SLIDE_REVIEWS_MISSING", data
    assert data["fix"] == _load(GEN, "dr_fix").SLIDE_REVIEWS_MISSING_FIX
    assert "run this generator again" in data["fix"] and "dispatch the CHECKLIST again" not in data["fix"]
    # A refusal must never become a comparand: no context line, no closing line, in either stream.
    for stream in (r.stdout, r.stderr):
        assert "CONTEXT:" not in stream and "OUTPUT_PATH" not in stream, stream
    assert len(r.stderr.strip().splitlines()) == 1


def test_a_tokened_file_is_not_refused(tmp_path: Path) -> None:
    r = _gen(_review(tmp_path), cwd=tmp_path)
    assert r.returncode == 0 and r.stdout.startswith("CONTEXT: CHECKLIST\n")


def test_no_print_and_no_refusal_carries_the_token(tmp_path: Path) -> None:
    review = tmp_path / "review"
    token = _slide_reviews(review)
    outs = [_gen(review, cwd=tmp_path)]
    detail = tmp_path / "producer_rejected.txt"
    detail.write_text("Error (SLIDE_REVIEWS_NOT_READ): the grade does not carry the read token\n", encoding="utf-8")
    outs.append(_gen(review, "--correction", "producer-rejected", "--detail-file", str(detail), cwd=tmp_path))
    outs.append(_gen(review, cwd=tmp_path, run_id="OTHER"))  # refused: another run's slide reviews
    for r in outs:
        assert token not in r.stdout and token not in r.stderr
    assert outs[0].returncode == 0 and outs[2].returncode == 1


def test_the_generator_never_reaches_the_token() -> None:
    """The output test passes a generator that reads the token and merely does not print it; this one does
    not. The generator references `_slide_reviews_file.usable` only, and names `read_token` nowhere outside the
    template's own instruction to the grader."""
    tree = ast.parse(GEN.read_text(encoding="utf-8"))
    attrs = {
        n.attr
        for n in ast.walk(tree)
        if isinstance(n, ast.Attribute) and getattr(n.value, "id", None) == ("_slide_reviews_file")
    }
    assert attrs == {"usable"}
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    assert "token" not in names
    template = _load(GEN, "dr_src")._CHECKLIST_TEMPLATE
    docstrings = {
        id(n.body[0].value)
        for n in ast.walk(tree)
        if isinstance(n, (ast.Module, ast.FunctionDef))
        and n.body
        and isinstance(n.body[0], ast.Expr)
        and isinstance(n.body[0].value, ast.Constant)
    }
    for node in ast.walk(tree):
        if id(node) in docstrings:
            continue
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and "read_token" in node.value:
            assert node.value in template, node.value
        if isinstance(node, ast.Attribute):
            assert "token" not in node.attr or node.attr == "usable", node.attr


def test_lever_the_precondition_removed_from_a_copy_reds_the_refusal(tmp_path: Path) -> None:
    """Without the precondition the generator prints for a folder with no slide reviews: the refusal tests
    above are what notice."""
    copy = tmp_path / "copy"
    shutil.copytree(SCRIPTS, copy)
    src = (copy / "dr_dispatch_prompt.py").read_text(encoding="utf-8")
    needle = "    if not ok:\n        _refuse_missing(slide_reviews, problem)\n"
    assert src.count(needle) == 1
    (copy / "dr_dispatch_prompt.py").write_text(src.replace(needle, ""), encoding="utf-8")
    review = tmp_path / "review"
    review.mkdir()
    args = ["checklist", "--run-id", RUN, "--handoff-agent", "/h", "--review-dir-agent", "/a"]
    r = subprocess.run(
        [sys.executable, str(copy / "dr_dispatch_prompt.py"), *args, "--review-dir", str(review)],
        capture_output=True,
        text=True,
        timeout=30,
        cwd=tmp_path,
    )
    assert r.returncode == 0 and r.stdout.startswith("CONTEXT: CHECKLIST")  # the lever engaged
    real = _gen(review, cwd=tmp_path)
    assert real.returncode == 1


# --- corrections -------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("correction", "line"),
    [
        (
            "missing-file",
            "Your previous receipt claimed a file at OUTPUT_PATH but none exists; use Write to create exactly "
            "that path.\n",
        ),
        ("receipt-only", "Return ONLY the receipt JSON -- no fences, no prose.\n"),
    ],
)
def test_a_corrective_redo_adds_one_printed_line_before_the_closing_line(
    tmp_path: Path, correction: str, line: str
) -> None:
    review = _review(tmp_path)
    plain = _gen(review, cwd=tmp_path).stdout
    redo = _gen(review, "--correction", correction, cwd=tmp_path)
    assert redo.returncode == 0, redo.stderr
    assert redo.stdout == plain[: -len(END)] + line + END


def test_a_producer_rejected_redo_quotes_the_saved_message_line_by_line(tmp_path: Path) -> None:
    review = _review(tmp_path)
    detail = tmp_path / "producer_rejected.txt"
    detail.write_text(
        "Error (SLIDE_REVIEWS_NOT_READ): the grade does not carry the read token; it was left unchanged\nsecond line\n",
        encoding="utf-8",
    )
    plain = _gen(review, cwd=tmp_path).stdout
    redo = _gen(review, "--correction", "producer-rejected", "--detail-file", str(detail), cwd=tmp_path)
    assert redo.returncode == 0, redo.stderr
    added = (
        "The producer rejected your previous file. Its message, quoted:\n"
        "> Error (SLIDE_REVIEWS_NOT_READ): the grade does not carry the read token; it was left unchanged\n"
        "> second line\n"
        "Write a corrected file to OUTPUT_PATH.\n"
    )
    assert redo.stdout == plain[: -len(END)] + added + END
    assert redo.stdout.endswith(END) and redo.stdout.count(END.strip()) == 1


def test_a_producer_rejected_redo_needs_a_saved_message(tmp_path: Path) -> None:
    review = _review(tmp_path)
    assert _gen(review, "--correction", "producer-rejected", cwd=tmp_path).returncode == 2
    empty = tmp_path / "empty.txt"
    empty.write_text("  \n", encoding="utf-8")
    r = _gen(review, "--correction", "producer-rejected", "--detail-file", str(empty), cwd=tmp_path)
    assert r.returncode == 2 and r.stdout == ""


@pytest.mark.parametrize("flag", ["--run-id", "--handoff-agent", "--review-dir-agent", "--review-dir"])
def test_an_empty_identifier_is_refused(tmp_path: Path, flag: str) -> None:
    review = _review(tmp_path)
    values = {"--run-id": RUN, "--handoff-agent": "/h", "--review-dir-agent": "/a", "--review-dir": str(review)}
    values[flag] = ""
    args = ["checklist"] + [x for k, v in values.items() for x in (k, v)]
    r = subprocess.run([sys.executable, str(GEN), *args], capture_output=True, text=True, timeout=30, cwd=tmp_path)
    assert r.returncode == 2 and r.stdout == "" and flag in r.stderr


def test_every_option_takes_a_value() -> None:
    """The hook steps over every option as taking a value; a store-true flag would make it read the next word
    as the subcommand, and the print would count for no context."""
    tree = ast.parse(GEN.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "attr", None) == "add_argument":
            for kw in node.keywords:
                if kw.arg == "action":
                    raise AssertionError(f"an option with an action: {ast.unparse(node)}")


# --- a folder that belongs to a run --------------------------------------------------------------------


def test_in_a_bound_folder_another_runs_slide_reviews_are_refused_first(tmp_path: Path) -> None:
    review = tmp_path / "review"
    _slide_reviews(review, run_id="OTHER")
    _bind(review, RUN)
    r = _gen(review, cwd=tmp_path)
    assert r.returncode == 1
    assert json.loads(r.stdout)["code"] == "ARTIFACT_OTHER_RUN"


@pytest.mark.parametrize("name", ["stage_profile.json", "deck_inventory.json", "reconciliation.json"])
def test_in_a_bound_folder_another_runs_input_refuses_the_print(tmp_path: Path, name: str) -> None:
    """A re-review of the same company that reused an earlier run's file is refused at the print, earlier
    than the checklist pipe would have."""
    review = _review(tmp_path)
    _bind(review, RUN)
    assert _gen(review, cwd=tmp_path).returncode == 0
    (review / name).write_text(json.dumps({"metadata": {"run_id": "OTHER"}}), encoding="utf-8")
    r = _gen(review, cwd=tmp_path)
    assert r.returncode == 1 and json.loads(r.stdout)["code"] == "ARTIFACT_OTHER_RUN"
    assert name in r.stdout


def test_in_a_bound_folder_an_unbound_run_is_refused(tmp_path: Path) -> None:
    review = _review(tmp_path)
    _bind(review, "OTHER")
    r = _gen(review, cwd=tmp_path)
    assert r.returncode == 1 and json.loads(r.stdout)["code"] == "RUN_NOT_BOUND"
