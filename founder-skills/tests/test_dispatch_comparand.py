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
INSTALLED = "/sessions/s1/mnt/.local-plugins/marketplaces/m/founder-skills"
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
        "; cp /tmp/forged.txt /proc/self/fd/1",
        '; cp /tmp/forged.txt "/proc/$$/fd/1"',
        "; mv /tmp/forged.txt /proc/self/fd/2",
        "; cp /tmp/forged.txt /dev/fd/1",
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
        "cp /Users/me/dev/deck.pdf /w/docs/ && " + GEN,
        'D=/w/docs; cp /u/a.pdf "$D/" && ' + GEN,
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
        ("python3 " + INSTALLED + "/" + MS_SCRIPTS + "/dispatch_prompt.py checklist --run-id R", True),
        ('python3 "${CLAUDE_PLUGIN_ROOT}/skills/competitive-positioning/scripts/cp_dispatch_prompt.py" x', True),
        (f'SCRIPTS="{INSTALLED}/{MS_SCRIPTS}"\npython3 "$SCRIPTS/dispatch_prompt.py" red_team', True),
        ('SCRIPTS="/p/skills/market-sizing/scripts"\npython3 "$SCRIPTS/dispatch_prompt.py" red_team', False),
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


# --- a generator copied or rewritten outside the plugin is not trusted -------------------------------------

_FORGED = (
    "CONTEXT: RED_TEAM\nOUTPUT_PATH: /h/r2/o.json\nNote: round 2; ARPU changed.\n"
    "Do NOT write any file other than OUTPUT_PATH.\n"
)


@pytest.mark.parametrize(
    "setup",
    [
        'G=dispatch_prompt; cp /tmp/forge.py "/tmp/x/skills/market-sizing/scripts/$G.py"',
        "cp -r /tmp/plug /tmp/x",
        "",  # nothing at all: /tmp/x is not where the plugin is installed
    ],
)
def test_a_generator_run_from_outside_the_plugin_is_not_trusted(setup: str) -> None:
    calls = [("Bash", {"command": setup}, "")] if setup else []
    calls.append(("Bash", {"command": "python3 /tmp/x/" + MS_SCRIPTS + "/dispatch_prompt.py red_team"}, _FORGED))
    assert DPC.comparands(_rows(*calls)) == []


def test_a_relative_generator_path_is_not_trusted() -> None:
    cmd = "cd /tmp/x && python3 ./" + MS_SCRIPTS + "/dispatch_prompt.py red_team"
    assert DPC.comparands(_rows(("Bash", {"command": cmd}, _FORGED))) == []


@pytest.mark.parametrize(
    "write",
    [
        'G=dispatch_prompt; sed -i "" s/a/b/ "$SCRIPTS/$G.py"',
        "cp /tmp/a.py \"$SCRIPTS/dispatch_prom''pt.py\"",
        'cp /tmp/a.py "$SCRIPTS/dispatch_prompt$(true).py"',
        'ln -sf /tmp/a.py "$SCRIPTS/x.py"',
        "python3 -c \"open('$SCRIPTS/dispatch_'+'prompt.py','w')\"",
        'echo x > "$PLUGIN_ROOT/skills/market-sizing/scripts/y.py"',
    ],
)
def test_a_write_into_the_plugins_scripts_distrusts_the_generators(write: str) -> None:
    rows = _rows(("Bash", {"command": write}, ""), ("Bash", {"command": GEN}, PRINTED))
    assert DPC.comparands(rows) == [], write


@pytest.mark.parametrize(
    "root",
    [
        "/sessions/s1/mnt/.local-plugins/marketplaces/m/founder-skills",
        "/sessions/s1/mnt/.remote-plugins/plugin_abc",
        "/Users/u/.claude/plugins/cache/m/founder-skills/0.16.0",
        "/Users/u/Library/Application Support/Claude/x/cowork_plugins/cache/m/founder-skills/0.16.0",
        "/mnt/skills/plugins/founder-skills",
        str(Path(__file__).resolve().parents[1]),
    ],
)
def test_a_generator_from_an_installed_plugin_is_trusted(root: str) -> None:
    cmd = f'PLUGIN_ROOT="{root}"\nSCRIPTS="$PLUGIN_ROOT/{MS_SCRIPTS}"\npython3 "$SCRIPTS/dispatch_prompt.py" red_team'
    assert DPC.generator_block(cmd)[0] is True, root


def test_no_prescribed_shell_block_distrusts_a_generator() -> None:
    """Every bash block a SKILL.md prescribes, run as written, leaves the generators trusted."""
    import re

    skills = Path(__file__).resolve().parents[1] / "skills"
    blocks = []
    for md in sorted(skills.glob("*/SKILL.md")):
        blocks += [
            (md.parent.name, m.group(1)) for m in re.finditer(r"^```bash\n(.*?)^```", md.read_text(), re.M | re.S)
        ]
    assert len(blocks) > 50, len(blocks)
    for skill, block in blocks:
        assert DPC._distrusts(block) == set(), (skill, block[:400])


@pytest.mark.parametrize(
    ("hook_root", "shell_root"),
    [
        ("/private/tmp/p/founder-skills", "/tmp/p/founder-skills"),
        ("/tmp/p/founder-skills", "/private/tmp/p/founder-skills"),
    ],
)
def test_the_hooks_own_folder_matches_under_either_spelling_of_tmp(
    monkeypatch: Any, hook_root: str, shell_root: str
) -> None:
    """macOS spells one folder /tmp and /private/tmp; the hook's own folder is compared the same way."""
    monkeypatch.setattr(DPC, "HOOK_PLUGIN_ROOT", hook_root)
    assert DPC._installed_root(shell_root)
    assert DPC._into_plugin(shell_root + "/skills/x.txt")


def test_the_folder_the_runtime_loaded_our_skill_from_is_trusted() -> None:
    """The runtime's own skill-load row names where it loaded the skill from; a generator there counts."""
    root = "/opt/elsewhere/founder-skills"
    meta = {
        "type": "user",
        "isMeta": True,
        "message": {
            "content": [{"type": "text", "text": f"Base directory for this skill: {root}/skills/market-sizing\n"}]
        },
    }
    cmd = f"python3 {root}/{MS_SCRIPTS}/dispatch_prompt.py red_team"
    assert DPC.comparands([meta, *_rows(("Bash", {"command": cmd}, PRINTED))]) == [PRINTED]
    assert DPC.comparands(_rows(("Bash", {"command": cmd}, PRINTED))) == []
    # Only a row the runtime marks as its own, and only for one of our skills.
    typed = {**meta, "isMeta": False}
    assert DPC.comparands([typed, *_rows(("Bash", {"command": cmd}, PRINTED))]) == []


@pytest.mark.parametrize(
    "block",
    [
        "cat > \"$SCRIPTS/dispatch_prompt.py\" <<'EOF'\nprint('x')\nEOF",
        "python3 - <<'PY'\nopen('/x/skills/market-sizing/scripts/dispatch_prompt.py', 'w').write('x')\nPY",
        'for f in a; do cp /tmp/a.py "$SCRIPTS/$f.py"; done',
    ],
)
def test_a_block_the_parser_cannot_read_that_writes_into_the_plugin_distrusts(block: str) -> None:
    rows = _rows(("Bash", {"command": block}, ""), ("Bash", {"command": GEN}, PRINTED))
    assert DPC.comparands(rows) == [], block


# A block the parser cannot read (a loop, multi-line inline code) that runs the generator and saves its
# output OUTSIDE the plugin. Such a block writes nothing into the plugin, so a later print still counts.
_SYNCED = "/root/.claude/plugins/synced/plug0001/founder-skills"
_MS_A = "/home/claude/artifacts/market-sizing-acme"
_RT_ARGS = '--run-id "$RUN_ID" --analysis-dir "$A" --handoff-dir "$H" --analysis-dir-agent "$A" --handoff-agent "$H"'
_LOOPED = (
    f"P={_SYNCED}; SH=$P/scripts; SC=$P/{MS_SCRIPTS}\n"
    f"A={_MS_A}; RUN_ID=20990101T000000Z; H=$A/handoff/$RUN_ID\n"
    "for s in sensitivity checklist; do\n"
    'printf \'%s\' "{\\"status\\": \\"complete\\", \\"output_path\\": \\"$H/${s}_output.json\\"}" | '
    'python3 $SH/check_handoff.py "$H/${s}_output.json" --agent-path "$H/${s}_output.json" --receipt-json - '
    '>/dev/null; echo "gate_$s=$?"; done\n'
    'cat $H/sensitivity_output.json | python3 $SC/sensitivity.py --pretty --run-id "$RUN_ID" '
    '--sizing "$A/sizing.json" --inputs "$A/inputs.json" -o "$A/sensitivity.json"; echo "sens=$?"\n'
    'cat $H/checklist_output.json | python3 $SC/checklist.py --pretty --run-id "$RUN_ID" '
    '--sizing "$A/sizing.json" -o "$A/checklist.json"; echo "chk=$?"\n'
    'python3 -c "\n'
    "import json\n"
    "s=json.load(open('$A/sensitivity.json')); print('most_sensitive',s.get('most_sensitive'))\n"
    "c=json.load(open('$A/checklist.json')); print({k:v for k,v in c['summary'].items() if k!='failed_items'})\n"
    "for i in c['summary']['failed_items']: print('-',i['id'],':',i['notes'])\"\n"
    "# docs mirror + OCR + red-team prompt\n"
    "mkdir -p $H/docs && cp /root/.claude/uploads/up0001/0000abcd-synthetic-deck-scanned.pdf $H/docs/\n"
    'python3 $SC/ocr_uploads.py --uploads-dir "$H/docs" --out "$H/ocr"; echo "ocr=$?"\n'
    f"python3 $SC/dispatch_prompt.py red_team {_RT_ARGS} > /tmp/market-sizing-acme.staging.AAAA01/redteam_prompt.txt; "
    'echo "rt_prompt=$?"; wc -c /tmp/market-sizing-acme.staging.AAAA01/redteam_prompt.txt'
)
_STANDALONE = (
    f"P={_SYNCED}; SC=$P/{MS_SCRIPTS}\n"
    f"A={_MS_A}; RUN_ID=20990101T000000Z; H=$A/handoff/$RUN_ID\n"
    f"python3 $SC/dispatch_prompt.py red_team {_RT_ARGS}"
)
_RT_OUTPUT = f"{_MS_A}/handoff/20990101T000000Z/redteam_output.json"
_RT_PRINTED = (
    f"CONTEXT: RED_TEAM\nOUTPUT_PATH: {_RT_OUTPUT}\nRUN_ID: 20990101T000000Z\n\nRead the documents.\n"
    "Do NOT write any file other than OUTPUT_PATH.\n"
)


def test_an_unreadable_block_that_saves_the_generators_output_elsewhere_keeps_it_trusted(tmp_path: Path) -> None:
    assert DPC._parse_block(_LOOPED) is None  # the raw fallback is what decides this block
    assert DPC._distrusts(_LOOPED) == set()
    rows = _rows(
        ("Bash", {"command": _LOOPED}, "gate_sensitivity=0\n"), ("Bash", {"command": _STANDALONE}, _RT_PRINTED)
    )
    assert DPC.latest_printed(rows, "CONTEXT: RED_TEAM", _RT_OUTPUT) == _RT_PRINTED.rstrip("\n")
    transcript = tmp_path / "t.jsonl"
    transcript.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    tool_input = {"subagent_type": "founder-skills:market-sizing-redteam", "description": "d", "prompt": _RT_PRINTED}
    payload = {"hook_event_name": "PreToolUse", "tool_name": "Agent", "transcript_path": str(transcript)}
    assert DPC.decide({**payload, "tool_input": tool_input}) is None


# Writes the raw check misses: the target names the plugin only through a variable it does not resolve.
def _missed(write: str) -> Any:
    return pytest.param(write, marks=pytest.mark.xfail(strict=True, reason="target named only via a variable"))


_RAW_WRITES = [
    "cat x > $SC/dispatch_prompt.py",
    'cp /tmp/evil.py "$P/skills/market-sizing/scripts/dispatch_prompt.py"',
    "sed -i 's/a/b/' $SC/dispatch_prompt.py",
    "python3 -c \"open('$SC/dispatch_prompt.py','w')\"",
    "echo x | tee $SC/dispatch_prompt.py",
    "python3 - <<'PY'\nopen('" + _SYNCED + "/" + MS_SCRIPTS + "/x.py', 'w').write('x')\nPY",
    "dd if=/tmp/evil.py of=$SC/dispatch_prompt.py",
    "python3 $SC/dispatch_prompt.py red_team > $SC/dispatch_prompt.py",
    'python3 "$SC/dispatch_prompt.py" x; cp /tmp/e $SC/cp_dispatch_prompt.py',
    "python3 $SC/dispatch_prompt.py x > /tmp/y; cp /tmp/e " + _SYNCED + "/" + MS_SCRIPTS + "/checklist.py",
    'python3 -c "print(1)" $SC/dispatch_prompt.py > /tmp/y',
]
_RAW_MISSED = [
    "cat <<'EOF' > $SC/x.py\nprint('x')\nEOF",
    "echo x > $P/scripts/x.py",
    "cp /tmp/evil.py $SC/",
    'bash -c "cp /tmp/evil.py $SC/x.py"',
    'echo "# not a comment" > $SC/x.py',
]


def _unreadable(write: str) -> str:
    return f"P={_SYNCED}; SC=$P/{MS_SCRIPTS}\nfor s in a; do echo $s; done\n{write}"


@pytest.mark.parametrize("write", [*_RAW_WRITES, *map(_missed, _RAW_MISSED)])
def test_an_unreadable_block_that_writes_into_the_plugin_still_distrusts(write: str) -> None:
    block = _unreadable(write)
    assert DPC._parse_block(block) is None, write
    assert DPC._distrusts(block) == set(DPC.GENERATORS), write


_ATTACK_HEAD = f"P={_SYNCED}; SCRIPTS=$P/{MS_SCRIPTS}\n"
_LOOP = "for s in a; do echo $s; done\n"
_RUN = "python3 $SCRIPTS/dispatch_prompt.py red_team"
_ATTACKS = [
    _ATTACK_HEAD + _LOOP + f'O=$SCRIPTS/_params.py\n{_RUN} > "$O"\nO=/tmp/o',
    _ATTACK_HEAD + _LOOP + f'O=$SCRIPTS/_params.py\nO=/tmp/x {_RUN} > "$O"',
    _ATTACK_HEAD + _LOOP + f'O=$SCRIPTS/_params.py\n{_RUN} > "$O"\ncat > /tmp/n <<EOF\nO=/tmp/o\nEOF',
    _ATTACK_HEAD + f'O=$SCRIPTS/_params.py\nfor i in 1 2; do\n{_RUN} > "$O"\nO=/tmp/o; done',
    _ATTACK_HEAD + _LOOP + f"PYTHONPATH=/tmp/evil {_RUN} > /tmp/o",
    _ATTACK_HEAD + _LOOP + f"PATH=/tmp/evil:$PATH {_RUN} > /tmp/o",
    _ATTACK_HEAD + _LOOP + "python3 /tmp/evil/dispatch_prompt.py red_team > /tmp/o",
    _ATTACK_HEAD + _LOOP + "python3 ./dispatch_prompt.py red_team > /tmp/o",
    _ATTACK_HEAD + _LOOP + f"{_RUN} --handoff-dir $SCRIPTS > /tmp/o",
    _ATTACK_HEAD + _LOOP + f"{_RUN} > /tmp/o; cat /tmp/e $SCRIPTS/dispatch_prompt.py",
    _ATTACK_HEAD + "cd /tmp\n" + _LOOP + f"{_RUN} > /tmp/x/redteam_prompt.txt",
    _ATTACK_HEAD + f'if false; then\nO=/tmp/o\nfi\n{_RUN} > "$O"',
]


@pytest.mark.parametrize("block", _ATTACKS)
def test_a_generator_run_whose_write_cannot_be_settled_still_distrusts(block: str) -> None:
    assert DPC._parse_block(block) is None, block
    assert DPC._distrusts(block) == set(DPC.GENERATORS), block


def test_a_trusted_generator_run_saved_to_tmp_is_no_write() -> None:
    block = _ATTACK_HEAD + _LOOP + f"{_RUN} > /tmp/x/redteam_prompt.txt"
    assert DPC._parse_block(block) is None
    assert DPC._distrusts(block) == set()


def _raw_writes_as_before(command: str) -> bool:
    """The raw check before a generator's own run was set aside."""
    for line in command.splitlines():
        if not DPC._RAW_WRITE_RE.search(line.replace("2>&1", "").replace(">/dev/null", "")):
            continue
        if DPC._into_plugin(line) or "dispatch_" in line or "prompt.py" in line:
            return True
    return False


# The only lines decided differently: a generator run, its output saved outside the plugin.
_SAVED = 'python3 "$SC/dispatch_prompt.py" x > "$H/p.txt"; echo "EXIT=$?"; wc -c "$H/p.txt"'
_RUN_SAVED_ELSEWHERE = {
    _LOOPED.splitlines()[-1],
    _SAVED,
    "python3 $SCRIPTS/dispatch_prompt.py red_team > /tmp/x/redteam_prompt.txt",
}
_SAVED_BLOCK = f"P={_SYNCED}; SC=$P/{MS_SCRIPTS}; H={_MS_A}/handoff/R1\nfor s in a; do :; done\n{_SAVED}"


def test_a_generator_run_saved_elsewhere_is_no_write() -> None:
    assert DPC._parse_block(_SAVED_BLOCK) is None
    assert DPC._distrusts(_SAVED_BLOCK) == set()


@pytest.mark.parametrize(
    "block",
    [
        *map(_unreadable, _RAW_WRITES + _RAW_MISSED),
        *_ATTACKS,
        _SAVED_BLOCK,
        "cat > \"$SCRIPTS/dispatch_prompt.py\" <<'EOF'\nprint('x')\nEOF",
        'for f in a; do cp /tmp/a.py "$SCRIPTS/$f.py"; done',
        "for f in a; do :; done\npython3 $SC/checklist.py > /tmp/y",
        _LOOPED,
    ],
)
def test_the_raw_check_changes_only_on_a_generator_run_saved_elsewhere(block: str) -> None:
    """Line by line, the raw check decides as before except where a generator is run and its output is
    saved outside the plugin."""
    exempt = set() if block in _ATTACKS else _RUN_SAVED_ELSEWHERE  # an attack is decided as before
    kept = [line for line in block.splitlines() if line not in exempt]
    assert DPC._raw_writes_into_plugin(block) is _raw_writes_as_before("\n".join(kept)), block
    if len(kept) < len(block.splitlines()):  # the exemption engaged: before, this block distrusted
        assert _raw_writes_as_before(block) is True, block


# --- the steps before the generator in its block may print; the generator must be the block's last word --

_FMR = "skills/" + "financial-model-review/scripts"
_FOLDED = (
    f'SC="{INSTALLED}/{_FMR}"\n'
    'R="/w/artifacts/financial-model-review-acme"\nRUN_ID=R1\n'
    'python3 $SC/review_inputs.py "$R/inputs.json" --static "$R/review.html" >/dev/null; echo review=$?\n'
    'cat "$R/inputs.json" | python3 $SC/unit_economics.py --pretty --run-id "$RUN_ID" -o "$R/ue.json"; echo ue=$?\n'
    'cat "$R/inputs.json" | python3 $SC/runway.py --pretty --run-id "$RUN_ID" -o "$R/runway.json"; echo rw=$?\n'
    'python3 $SC/fmr_dispatch_prompt.py checklist --run-id "$RUN_ID" --handoff-agent "$R/handoff/R1" --review-dir "$R"'
)


def test_a_generator_folded_into_the_previous_steps_block_is_the_comparand() -> None:
    """Models run the generator at the end of the block that ran the step before it: the producers' JSON
    and exit codes print first, then the prompt. Nothing can print after it, so it is the comparand."""
    assert DPC.generator_block(_FOLDED)[0] is True
    noisy = 'cat "$R/x.json"; grep -c ok "$R/y.txt"; echo "CONTEXT: CHECKLIST"\n' + GEN
    assert DPC.generator_block(noisy)[0] is True  # what printed before the generator is not the last context line
    assert DPC.generator_block("cat /tmp/x\ncp /tmp/y /dev/stdout\n" + GEN)[0] is True  # it prints before, too


@pytest.mark.parametrize(
    "block",
    [
        _FOLDED + '\necho "done"',  # something after the generator: back to the quiet rule, and cat is not quiet
        _FOLDED.replace("\npython3 $SC/fmr_dispatch_prompt.py", "\ntrue || python3 $SC/fmr_dispatch_prompt.py"),
        "exec >/tmp/out\n" + GEN,
        "exec 1>/tmp/out; cat /tmp/x\n" + GEN,
        "trap 'cat /tmp/forged' EXIT\ncat /tmp/x\n" + GEN,
        'PATH="/tmp/evil:$PATH"\ncat /tmp/x\n' + GEN,
        "export PYTHONPATH=/tmp/evil; cat /tmp/x\n" + GEN,
        'PATH="/tmp/evil:$PATH"\n' + GEN,  # where python3 is found, even with no printing step
        "PYTHONSTARTUP=/tmp/s.py " + GEN,
        "python3 -c 'print(1)'\n" + GEN,
        "python3 /tmp/forge.py\n" + GEN,
        "nohup python3 /tmp/forge.py\n" + GEN,
        "bash /tmp/forge.sh\n" + GEN,
        "cat /tmp/x\n" + GEN + " | tee /tmp/copy",
        'cat /tmp/x\nX="$(python3 /tmp/forge.py)"\n' + GEN,  # a substitution runs code that could outlive it
    ],
)
def test_a_printing_step_before_the_generator_needs_the_generator_last_and_nothing_that_outlives_it(block: str) -> None:
    assert DPC.generator_block(block)[0] is False, block


def test_ls_after_the_generator_is_not_quiet() -> None:
    """File names are chosen by whoever made the files; listed after the generator, one per line, they
    could stand in for a prompt's lines."""
    assert DPC.generator_block(GEN + "\nls -t /tmp/made")[0] is False
    assert DPC.generator_block("ls -t /tmp/made\n" + GEN)[0] is True
