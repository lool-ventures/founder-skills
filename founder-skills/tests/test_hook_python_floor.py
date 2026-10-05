"""The hooks run under Python 3.9.

At the host loop a hook runs host-native on macOS, where `python3` is the system interpreter, 3.9. A
hook module that uses a 3.10 feature raises there, and every hook fails open: a dispatch the check
should hold goes through with one stderr line. The rest of the plugin may use 3.10 (its scripts run
in the session's shell); the hook modules may not.

Two checks: every module a hook loads parses as 3.9 and uses none of the 3.10 constructs a 3.9 parse
does not catch; and, where this machine has a system python3 older than 3.10, each hook gives the
same decision under it as under the development interpreter.
"""

from __future__ import annotations

import ast
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from test_hook_wrappers import _hook_files

PLUGIN = Path(__file__).resolve().parents[1]
SCRIPTS = PLUGIN / "scripts"
HOOK_MODULES = sorted(PLUGIN / rel for rel in _hook_files(PLUGIN) if rel.endswith(".py"))


def test_the_hook_module_list_is_complete() -> None:
    names = {p.name for p in HOOK_MODULES}
    expected = {
        "pretooluse_dispatch.py",
        "dispatch_prompt_check.py",
        "dispatch_type_check.py",
        "two_figures_check.py",
        "stop_handover_check.py",
        "_handover_check.py",
        "_delivery_check.py",
        "review_page_check.py",
    }
    assert expected <= names, names


# Calls and keywords that exist only from 3.10.
_NEW_KEYWORDS = {("zip", "strict"), ("dataclass", "slots"), ("dataclass", "kw_only"), ("field", "kw_only")}
_NEW_ATTRIBUTES = {"pairwise", "bit_count", "aiter", "anext"}
_TYPE_NAMES = {"str", "int", "float", "bool", "bytes", "dict", "list", "set", "tuple", "type", "Any"}


def _call_name(node: ast.Call) -> str:
    f = node.func
    return f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else ""


def _annotation_nodes(tree: ast.AST) -> set[int]:
    """ids of every node inside an annotation (not evaluated under `from __future__ import annotations`)."""
    out: set[int] = set()
    for node in ast.walk(tree):
        anns: list[ast.AST | None] = []
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            anns.append(node.returns)
            a = node.args
            anns += [x.annotation for x in [*a.posonlyargs, *a.args, *a.kwonlyargs]]
            anns += [a.vararg.annotation if a.vararg else None, a.kwarg.annotation if a.kwarg else None]
        elif isinstance(node, ast.AnnAssign):
            anns.append(node.annotation)
        for ann in anns:
            if ann is not None:
                out |= {id(n) for n in ast.walk(ann)}
    return out


def _is_type_operand(node: ast.AST) -> bool:
    if isinstance(node, ast.Constant) and node.value is None:
        return True
    if isinstance(node, ast.Name) and node.id in _TYPE_NAMES:
        return True
    return isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name) and node.value.id in _TYPE_NAMES


def problems(source: str) -> list[str]:
    """The 3.10+ constructs in `source`, for a module that must run under 3.9."""
    found = []
    try:
        tree = ast.parse(source, feature_version=(3, 9))
    except SyntaxError as e:
        return [f"does not parse as 3.9: {e}"]
    future = any(
        isinstance(n, ast.ImportFrom) and n.module == "__future__" and any(a.name == "annotations" for a in n.names)
        for n in tree.body
    )
    if not future:
        found.append("no `from __future__ import annotations` (an `X | None` annotation is evaluated)")
    in_annotation = _annotation_nodes(tree)
    lines = source.splitlines()
    for node in ast.walk(tree):
        if isinstance(node, (ast.With, ast.AsyncWith)) and len(node.items) > 1:
            head = lines[node.lineno - 1].strip()
            if head.split("with", 1)[-1].lstrip().startswith("("):
                found.append(f"line {node.lineno}: parenthesised context managers")
        if isinstance(node, ast.Call):
            for kw in node.keywords:
                if (_call_name(node), kw.arg) in _NEW_KEYWORDS:
                    found.append(f"line {node.lineno}: {_call_name(node)}({kw.arg}=...)")
        if isinstance(node, ast.Attribute) and node.attr in _NEW_ATTRIBUTES:
            found.append(f"line {node.lineno}: .{node.attr}")
        if isinstance(node, ast.Name) and node.id in {"aiter", "anext", "EncodingWarning"}:
            found.append(f"line {node.lineno}: {node.id}")
        if (
            isinstance(node, ast.BinOp)
            and isinstance(node.op, ast.BitOr)
            and id(node) not in in_annotation
            and (_is_type_operand(node.left) or _is_type_operand(node.right))
        ):
            found.append(f"line {node.lineno}: a `|` type union evaluated at runtime")
    return found


@pytest.mark.parametrize("module", HOOK_MODULES, ids=lambda p: p.name)
def test_a_hook_module_uses_nothing_newer_than_3_9(module: Path) -> None:
    assert problems(module.read_text(encoding="utf-8")) == [], module.name


@pytest.mark.parametrize(
    "snippet",
    [
        "from __future__ import annotations\nfor a, b in zip(x, y, strict=True):\n    pass\n",
        "from __future__ import annotations\nmatch x:\n    case 1:\n        pass\n",
        "from __future__ import annotations\nwith (open(a) as f, open(b) as g):\n    pass\n",
        "from __future__ import annotations\nT = str | None\n",
        "from __future__ import annotations\nisinstance(x, int | str)\n",
        "def f(x: str | None) -> None:\n    pass\n",
        "from __future__ import annotations\nimport itertools\nitertools.pairwise(x)\n",
    ],
)
def test_the_check_catches_each_construct(snippet: str) -> None:
    """Seeded negatives: each construct the check exists for is reported."""
    assert problems(snippet), snippet


def test_annotations_and_plain_bit_or_are_not_reported() -> None:
    ok = (
        "from __future__ import annotations\n"
        "def f(x: str | None, y: dict[str, int] | None) -> int | None:\n    return 3 | 4\n"
    )
    assert problems(ok) == []


# --- under this machine's system python3, when it is older than 3.10 ----------------------------------

_SYSTEM = shutil.which("python3", path="/usr/bin")


def _system_version() -> tuple[int, int] | None:
    if _SYSTEM is None:
        return None
    r = subprocess.run([_SYSTEM, "-c", "import sys; print(sys.version_info[0], sys.version_info[1])"],
                       capture_output=True, text=True, timeout=30)  # fmt: skip
    if r.returncode != 0:
        return None
    major, minor = r.stdout.split()
    return int(major), int(minor)


OLD = _system_version()
needs_old = pytest.mark.skipif(
    OLD is None or OLD >= (3, 10), reason="no system python3 older than 3.10 on this machine"
)


def _both(script: Path, payload: dict[str, Any]) -> tuple[str, str]:
    outs = []
    for py in (sys.executable, _SYSTEM):
        assert py is not None
        r = subprocess.run([py, str(script)], input=json.dumps(payload), capture_output=True, text=True, timeout=30)
        assert r.returncode == 0, (py, r.stderr)
        assert "Error" not in r.stderr and "Traceback" not in r.stderr, (py, r.stderr)
        outs.append(r.stdout)
    return outs[0], outs[1]


_GEN = (
    "CONTEXT: RED_TEAM\nOUTPUT_PATH: /h/r2/redteam_output.json\nRead docs.\n"
    "Do NOT write any file other than OUTPUT_PATH.\n"
)


def _dispatch_transcript(tmp_path: Path) -> Path:
    use = {
        "type": "tool_use",
        "id": "t1",
        "name": "Bash",
        "input": {"command": 'python3 "$SCRIPTS/dispatch_prompt.py" r'},
    }
    rows = [
        {"type": "assistant", "message": {"content": [use]}},
        {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t1", "content": _GEN}]}},
    ]
    path = tmp_path / "t.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return path


@needs_old
@pytest.mark.parametrize(
    ("prompt", "agent", "held"),
    [
        (_GEN.replace("Read docs.\n", "Read docs.\nNote: round 2.\n"), "founder-skills:market-sizing-redteam", True),
        (_GEN, "general-purpose", True),
        (_GEN, "founder-skills:market-sizing-redteam", False),
    ],
)
def test_the_dispatch_hook_decides_the_same_under_the_system_python(
    tmp_path: Path, prompt: str, agent: str, held: bool
) -> None:
    payload = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Agent",
        "transcript_path": str(_dispatch_transcript(tmp_path)),
        "tool_input": {"prompt": prompt, "subagent_type": agent, "description": "d"},
    }
    dev, system = _both(SCRIPTS / "pretooluse_dispatch.py", payload)
    assert dev == system
    assert bool(dev) is held


@needs_old
def test_the_stop_hook_decides_the_same_under_the_system_python(tmp_path: Path) -> None:
    from test_stop_handover_hook import OWN_VERDICT, _assistant_text, _handover, _rows_after_call

    _handover(tmp_path)
    rows = _rows_after_call(_assistant_text(OWN_VERDICT))
    transcript = tmp_path / "t.jsonl"
    transcript.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    payload = {
        "session_id": "s",
        "transcript_path": str(transcript),
        "cwd": str(tmp_path / "outputs"),
        "hook_event_name": "Stop",
        "stop_hook_active": False,
        "last_assistant_message": OWN_VERDICT,
    }
    dev, system = _both(SCRIPTS / "stop_handover_check.py", payload)
    assert dev == system
    assert json.loads(dev)["decision"] == "block"


def test_every_hook_module_is_linted_as_3_9() -> None:
    """pyproject.toml's per-file target lists exactly the hook modules, so ruff never suggests a 3.10
    construct in one of them."""
    import re

    text = (PLUGIN.parent / "pyproject.toml").read_text(encoding="utf-8")
    section = text.split("[tool.ruff.per-file-target-version]", 1)[1].split("\n[", 1)[0]
    listed = set(re.findall(r'^"founder-skills/scripts/([A-Za-z0-9_]+\.py)" = "py39"$', section, re.MULTILINE))
    assert listed == {p.name for p in HOOK_MODULES}


@needs_old
@pytest.mark.parametrize("sent", [False, True])
def test_the_question_check_decides_the_same_under_the_system_python(tmp_path: Path, sent: bool) -> None:
    from test_review_page_hook import PAGE, _built, _deliver, _payload

    rows = _built(*_deliver("toolu_d", PAGE)) if sent else _built()
    dev, system = _both(SCRIPTS / "pretooluse_dispatch.py", _payload(tmp_path, rows))
    assert dev == system
    assert bool(dev) is not sent


@needs_old
@pytest.mark.parametrize("answered", [False, True])
def test_the_two_figures_check_reads_a_question_form_the_same_under_the_system_python(
    tmp_path: Path, answered: bool
) -> None:
    """The form is parsed with `html.parser`; the hold and its release must not depend on the interpreter."""
    from test_two_figures_hook import _ALL_PILLS, _SHOWN, _answer, _asked, _form_outputs, _payload, _widget

    _form_outputs(tmp_path)
    rows = _asked(_widget(*_ALL_PILLS), _SHOWN, *([_answer()] if answered else []))
    dev, system = _both(SCRIPTS / "pretooluse_dispatch.py", _payload(tmp_path, rows))
    assert dev == system
    assert bool(dev) is not answered
