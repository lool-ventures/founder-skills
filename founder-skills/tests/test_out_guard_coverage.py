"""Every writer with an output flag calls the output guard with that flag's value, or is exempt with a reason.

The structural half of the `-o` rule (the behavioural half is `test_out_guard_wiring.py`). An AST pass over
every script in the plugin-root `scripts/` and each skill's `scripts/` finds each `add_argument` registering
one of the output flags below, and requires that the script call `refuse_output_onto_input` with that flag's
`args.<dest>` among its outputs. A script that registers `-o` through cap-table's `_emit.add_output_args` and
writes through `emit` is covered by the guard inside `emit`.

`EXEMPT` names (script, flag) pairs that are not an output onto a file the script could read, each with its
reason. It may only shrink.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PLUGIN = REPO_ROOT / "founder-skills"
OUTPUT_FLAGS = {"-o", "--output", "--write-md", "--output-json", "--output-md", "--static"}

EXEMPT: dict[tuple[str, str], str] = {
    ("scripts/run_status.py", "-o"): "the status CLI's receipt; no subcommand that takes -o reads a file named "
    "on its command line (`finish --output` is an input and finish has no -o)",
    ("scripts/run_status.py", "--output"): "`finish --output` names the run's output folder, an input",
    ("scripts/find_artifact.py", "-o"): "takes no file inputs: it only lists paths",
    ("scripts/insert_coaching.py", "-o"): "its own, stricter guard (`_output_onto_input`, OUTPUT_IS_INPUT): it also "
    "protects the report's siblings by name and refuses an existing -o that is not one of its receipts",
    ("skills/deck-review/scripts/gate_state.py", "-o"): "`answer --file/-o` is the gate file it edits in place "
    "by design; `emit -o` reads stdin only",
    ("skills/competitive-positioning/scripts/record_red_team_skip.py", "-o"): "takes no file inputs",
    ("skills/competitive-positioning/scripts/score_moats.py", "-o"): "stdin only: nothing on argv to collide with",
    ("skills/competitive-positioning/scripts/validate_startup_research.py", "-o"): "stdin only",
    ("skills/deck-review/scripts/deck_inventory.py", "-o"): "stdin only",
    ("skills/deck-review/scripts/stage_profile.py", "-o"): "stdin only",
    ("skills/financial-model-review/scripts/validate_inputs.py", "-o"): "stdin only: the documented "
    "`--fix < inputs.json -o inputs.json` in-place fix reads stdin",
    ("skills/financial-model-review/scripts/runway.py", "-o"): "stdin only",
    ("skills/financial-model-review/scripts/unit_economics.py", "-o"): "stdin only",
    ("skills/ic-sim/scripts/score_dimensions.py", "-o"): "stdin only",
    ("skills/ic-sim/scripts/persist_partner.py", "-o"): "stdin only",
    ("skills/ic-sim/scripts/detect_conflicts.py", "-o"): "stdin only",
}
# Each skill's `_compose_result.py` reads compose's own -o / --write-md from its argv to record what compose
# wrote; it writes neither. compose itself guards both.
for _skill in (
    "cap-table",
    "competitive-positioning",
    "deck-review",
    "financial-model-review",
    "ic-sim",
    "market-sizing",
):
    for _flag in ("-o", "--write-md"):
        EXEMPT[(f"skills/{_skill}/scripts/_compose_result.py", _flag)] = (
            "compose's wrapper: it parses compose's argv to record the outputs and writes neither; compose guards both"
        )


def _scripts() -> list[Path]:
    out = sorted((PLUGIN / "scripts").glob("*.py"))
    out += sorted(PLUGIN.glob("skills/*/scripts/*.py"))
    return [p for p in out if not p.name.startswith("test_")]


def _flag_dest(call: ast.Call) -> tuple[list[str], str | None]:
    flags = [a.value for a in call.args if isinstance(a, ast.Constant) and isinstance(a.value, str)]
    dest = None
    for kw in call.keywords:
        if kw.arg == "dest" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
            dest = kw.value.value
    if dest is None:
        longs = [f for f in flags if f.startswith("--")]
        if longs:
            dest = longs[0][2:].replace("-", "_")
        elif flags:
            dest = flags[0].lstrip("-").replace("-", "_")
    return flags, dest


def _registered(tree: ast.AST) -> list[tuple[str, str | None]]:
    """(flag, dest) for each output flag the script registers."""
    out: list[tuple[str, str | None]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "add_argument":
            flags, dest = _flag_dest(node)
            hit = [f for f in flags if f in OUTPUT_FLAGS]
            if hit:
                out.append((hit[0], dest))
    return out


def _guarded_dests(tree: ast.AST) -> set[str] | None:
    """The `<x>.<dest>` attributes named in a refuse_output_onto_input call's outputs; None without a call."""
    found: set[str] | None = None
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", None)
        if name != "refuse_output_onto_input" or not node.args:
            continue
        found = found or set()
        for sub in ast.walk(node.args[0]):
            if isinstance(sub, ast.Attribute):
                found.add(sub.attr)
            elif isinstance(sub, ast.Name):
                found.add(sub.id)
            elif isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                found.add(sub.value)  # getattr(args, "output", None) on a subcommand that may lack it
    return found


def _emit_routed(tree: ast.AST) -> bool:
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    calls = {
        (n.func.id if isinstance(n.func, ast.Name) else getattr(n.func, "attr", ""))
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
    }
    return "add_output_args" in calls and "emit" in (calls | names)


def _findings() -> list[str]:
    problems: list[str] = []
    for path in _scripts():
        rel = path.relative_to(PLUGIN).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        regs = _registered(tree)
        if not regs and _emit_routed(tree):
            continue
        guarded = _guarded_dests(tree)
        for flag, dest in regs:
            if (rel, flag) in EXEMPT:
                continue
            if guarded is None:
                problems.append(f"{rel}: registers {flag} and never calls refuse_output_onto_input")
            elif dest not in guarded:
                problems.append(f"{rel}: {flag} (args.{dest}) is not among the guard's outputs")
    return problems


def test_every_output_flag_is_guarded_or_exempt() -> None:
    assert _findings() == []


def test_every_exemption_is_still_registered() -> None:
    """The map may only shrink: an exemption for a flag the script no longer registers is removed."""
    stale = []
    for rel, flag in EXEMPT:
        path = PLUGIN / rel
        if not path.is_file() or flag not in {f for f, _d in _registered(ast.parse(path.read_text()))}:
            stale.append((rel, flag))
    assert stale == []


def test_the_scan_sees_an_unguarded_writer(tmp_path: Path) -> None:
    """The scan is not vacuous: a writer registering -o with no guard call is reported."""
    src = "import argparse\np = argparse.ArgumentParser()\np.add_argument('-o', '--output')\n"
    tree = ast.parse(src)
    assert _registered(tree) == [("-o", "output")]
    assert _guarded_dests(tree) is None
    guarded = src + "_out_guard.refuse_output_onto_input([args.output], script='x')\n"
    assert _guarded_dests(ast.parse(guarded)) == {"args", "output"}


@pytest.mark.parametrize("flag", sorted(OUTPUT_FLAGS))
def test_each_output_flag_is_recognised(flag: str) -> None:
    tree = ast.parse(f"p.add_argument({flag!r}, dest='x')\n")
    assert _registered(tree) == [(flag, "x")]
