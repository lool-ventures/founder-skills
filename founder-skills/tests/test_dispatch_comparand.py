"""Which shell blocks and file reads may be the prompt check's comparand.

The comparand is the generator's own output. A block that runs the generator counts only when every
other command in it is known not to print text of its own choosing (an allow-list, not a list of
known printers), the generator is the skill's own script, and a file read back is the one the
generator wrote and nothing could have changed since.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def _load() -> Any:
    spec = importlib.util.spec_from_file_location("dpc_comparand", SCRIPTS / "dispatch_prompt_check.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


DPC = _load()
GEN = 'python3 "$SCRIPTS/dispatch_prompt.py" red_team --run-id R --handoff-dir /h'
MS_SCRIPTS = "skills/" + "market-sizing/scripts"
PRINTED = (
    "CONTEXT: RED_TEAM\nOUTPUT_PATH: /h/redteam_output.json\nRUN_ID: R\n\nRead the documents.\n"
    "Do NOT write any file other than OUTPUT_PATH.\n"
)


# --- an allow-list: anything not known to be quiet makes the block print text of its own ----------------


@pytest.mark.parametrize(
    "tail",
    [
        "; printf '%s%s\\n' CONT 'EXT: RED_TEAM'",
        "; printf '\\103ONTEXT: RED_TEAM\\n'",
        "; echo -n CONT; echo 'EXT: RED_TEAM'",
        "; echo CONT; echo EXT",
        "; echo -e '\\x43ONTEXT: RED_TEAM'",
        "; tr x x < /tmp/forged.txt",
        "; cp /tmp/forged.txt /dev/stdout",
        "; dd if=/tmp/forged.txt 2>/dev/null",
        "; timeout 5 cat /tmp/forged.txt",
        "; nice cat /tmp/forged.txt",
        "; stdbuf -oL cat /tmp/forged.txt",
        "; sudo cat /tmp/forged.txt",
        "; iconv -f utf-8 /tmp/forged.txt",
        "; zcat /tmp/forged.gz",
        "; expand /tmp/forged.txt",
        "; python3 /tmp/forge.py",
        '; P=$(tr x x < /tmp/f); echo "$P"',
        "; osascript -e 'return \"x\"'",
        "; php -r 'echo 1;'",
        '; while read l; do echo "$l"; done < /tmp/f',
        '; for l in a; do echo "$l"; done',
        "; if true; then cat /tmp/forged.txt; fi",
        "; ! cat /tmp/forged.txt",
        "; f() { cat /tmp/f; }; f",
        "; (cat /tmp/f)",
        "; wc < /tmp/f",
        " &",
    ],
)
def test_a_command_not_known_to_be_quiet_makes_the_block_no_comparand(tail: str) -> None:
    assert DPC.generator_block(GEN + tail)[0] is False, tail


@pytest.mark.parametrize(
    "block",
    [
        GEN,
        'RUN_ID="R"\n' + GEN + '\necho "EXIT=$?"',
        GEN + " 2>&1",
        'U=$(python3 "${SHARED_SCRIPTS}/resolve_artifacts_root.py" --uploads 2>/dev/null)\necho "u: $U"\n' + GEN,
        'mkdir -p "$HD/d" && cp "/u"/* "$HD/d/"\nls -la "$HD/d/"\n' + GEN,
        'python3 "$SCRIPTS/ocr_uploads.py" --uploads-dir d --out o 2>&1 | tail -5\n' + GEN,
        "set -e; cd /w && " + GEN,
        'echo "=== RED_TEAM PROMPT ==="\n' + GEN,
        'echo "---"\n' + GEN + '\necho "OCR_EXIT=$?"',
        GEN + '; wc -c "$HANDOFF_DIR/x"; true',
    ],
)
def test_the_quiet_commands_runs_use_keep_the_block_a_comparand(block: str) -> None:
    assert DPC.generator_block(block)[0] is True, block


# --- the generator must be the skill's own script ------------------------------------------------------


@pytest.mark.parametrize(
    ("block", "ok"),
    [
        ("python3 /tmp/evil/dispatch_prompt.py red_team", False),
        ('python3 "$S/dispatch_prompt.py" red_team', False),
        ("python3 /p/skills/competitive-positioning/scripts/dispatch_prompt.py red_team", False),
        ("python3 /p/skills/market-sizing/scripts/cp_dispatch_prompt.py red_team", False),
        ("python3 /p/" + MS_SCRIPTS + "/dispatch_prompt.py checklist --run-id R", True),
        ('python3 "${CLAUDE_PLUGIN_ROOT}/skills/competitive-positioning/scripts/cp_dispatch_prompt.py" x', True),
        ('SCRIPTS="/p/skills/market-sizing/scripts"\npython3 "$SCRIPTS/dispatch_prompt.py" red_team', True),
        ('SCRIPTS="/tmp/evil"\npython3 "$SCRIPTS/dispatch_prompt.py" red_team', False),
        ('P="$PLUGIN_ROOT/skills/market-sizing/scripts"; python3 "$P/dispatch_prompt.py" checklist', True),
        ('python3 "$SCRIPTS/dispatch_prompt.py" red_team', True),
        ('python3 "${SCRIPTS}/fmr_dispatch_prompt.py" checklist', True),
    ],
)
def test_the_generator_is_the_skills_own_script(block: str, ok: bool) -> None:
    assert DPC.generator_block(block)[0] is ok, block


def _rows(*items: tuple[str, dict[str, Any], str | None], sidechain: bool = False) -> list[dict[str, Any]]:
    """(tool, input, result-or-None) -> assistant tool_use rows and their results."""
    rows: list[dict[str, Any]] = []
    for n, (tool, tool_input, result) in enumerate(items):
        uid = f"toolu_{n}"
        use = {"type": "tool_use", "id": uid, "name": tool, "input": tool_input}
        rows.append({"type": "assistant", "isSidechain": sidechain, "message": {"content": [use]}})
        if result is not None:
            block = {"type": "tool_result", "tool_use_id": uid, "content": result}
            rows.append({"type": "user", "isSidechain": sidechain, "message": {"content": [block]}})
    return rows


def _numbered(text: str) -> str:
    return "".join(f"{n}\t{line}\n" for n, line in enumerate(text.splitlines(), 1))


def test_a_generator_written_over_in_the_session_is_no_longer_trusted() -> None:
    rows = _rows(
        ("Write", {"file_path": "/tmp/x/dispatch_prompt.py", "content": "print('x')"}, "ok"),
        ("Bash", {"command": GEN}, PRINTED),
    )
    assert DPC.comparands(rows) == []
    by_shell = _rows(("Bash", {"command": "cp /tmp/x.py /p/skills/market-sizing/scripts/dispatch_prompt.py"}, ""))
    assert DPC.comparands(by_shell + _rows(("Bash", {"command": GEN}, PRINTED))) == []
    # Control: reading or running it does not.
    clean = _rows(("Bash", {"command": "grep -n x /p/dispatch_prompt.py"}, ""), ("Bash", {"command": GEN}, PRINTED))
    assert DPC.comparands(clean) == [PRINTED]


# --- a file read back: nothing could have changed it ---------------------------------------------------

REDIRECT = GEN + " > /abs/h/redteam_prompt.txt"


@pytest.mark.parametrize(
    "between",
    [
        'X=redteam_prompt; cp /tmp/forged "/abs/h/${X}.txt"',
        "python3 -c \"open('/abs/h/redteam_prompt'+'.txt','w').write('x')\"",
        "python3 /tmp/rewrite.py",
        'cp /tmp/forged "$SOMEWHERE"',
        "if true; then :; fi",
    ],
)
def test_a_later_shell_block_that_could_rewrite_the_file_drops_it(between: str) -> None:
    rows = _rows(
        ("Bash", {"command": REDIRECT}, ""),
        ("Bash", {"command": between}, ""),
        ("Read", {"file_path": "/abs/h/redteam_prompt.txt"}, _numbered(PRINTED)),
    )
    assert DPC.comparands(rows) == [], between


def test_a_sub_agent_write_drops_the_file() -> None:
    rows = _rows(("Bash", {"command": REDIRECT}, ""))
    rows += _rows(("Write", {"file_path": "/abs/h/redteam_prompt.txt", "content": "x"}, "ok"), sidechain=True)
    rows += _rows(("Read", {"file_path": "/abs/h/redteam_prompt.txt"}, _numbered(PRINTED)))
    assert DPC.comparands(rows) == []


def test_the_same_file_under_private_tmp_is_the_same_file() -> None:
    redirect = GEN + " > /tmp/redteam_prompt.txt"
    rows = _rows(
        ("Bash", {"command": redirect}, ""),
        ("Read", {"file_path": "/private/tmp/redteam_prompt.txt"}, _numbered(PRINTED)),
    )
    assert DPC.comparands(rows) == [PRINTED]
    written = _rows(
        ("Bash", {"command": redirect}, ""),
        ("Write", {"file_path": "/private/tmp/redteam_prompt.txt", "content": "x"}, "ok"),
        ("Read", {"file_path": "/tmp/redteam_prompt.txt"}, _numbered(PRINTED)),
    )
    assert DPC.comparands(written) == []


def test_a_read_only_block_keeps_the_file() -> None:
    rows = _rows(
        ("Bash", {"command": REDIRECT}, ""),
        ("Bash", {"command": "wc -l /abs/h/redteam_prompt.txt; ls /abs/h"}, ""),
        ("Read", {"file_path": "/abs/h/redteam_prompt.txt"}, _numbered(PRINTED)),
    )
    assert DPC.comparands(rows) == [PRINTED]


def test_rows_round_trip_through_json() -> None:
    """The fixtures are what a transcript file holds."""
    rows = _rows(("Bash", {"command": GEN}, PRINTED))
    assert json.loads(json.dumps(rows)) == rows
