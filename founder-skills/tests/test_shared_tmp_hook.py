"""`shared_tmp_check.py`: a Cowork shell command that writes a fixed name directly in /tmp is held.

Every session on a local Cowork machine shares one /tmp, and a file another session left there is not
writable: the redirect fails, the command before it never runs, and reading the name back shows the
other session's output. Exercised through `decide` with synthetic transcripts, through the dispatcher's
POSIX wrapper, and against the commands the skills themselves print.
"""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

PLUGIN = Path(__file__).resolve().parents[1]
SCRIPTS = PLUGIN / "scripts"
WRAPPER = SCRIPTS / "pretooluse-dispatch.sh"
SHELL = "mcp__workspace__bash"
DENY_PREFIX = f"PreToolUse:{SHELL} hook error: "
INSTALLED = "/sessions/s1/mnt/.local-plugins/marketplaces/m/founder-skills"
INCIDENT = 'python3 "$SCRIPTS/compose_report.py" --dir "$D" > /tmp/compose_out.txt 2>&1; tail -5 /tmp/compose_out.txt'


def _load(name: str) -> Any:
    spec = importlib.util.spec_from_file_location(f"{name}_under_test", SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


CHECK = _load("shared_tmp_check")


# --- the decision table: what the command's own text writes -------------------------------------------

DENIED = [
    (INCIDENT, ["/tmp/compose_out.txt"]),
    ('cat > /tmp/x.json <<\'EOF\'\n{"note": "> /tmp/y"}\nEOF\necho done', ["/tmp/x.json"]),
    # A body is text, not commands: the script it writes is not run by this block.
    ("cat > /tmp/x.sh <<'EOF'\necho hi > /tmp/y.txt\nEOF\nsh /tmp/x.sh", ["/tmp/x.sh"]),
    ('cmd >"/tmp/q.txt"', ["/tmp/q.txt"]),
    ("cmd>/tmp/q.txt", ["/tmp/q.txt"]),
    ("cmd 2> /tmp/e.txt", ["/tmp/e.txt"]),
    ("cmd &> /tmp/a.txt", ["/tmp/a.txt"]),
    ("cmd >> /tmp/a.txt", ["/tmp/a.txt"]),
    ("cmd >& /tmp/f.txt", ["/tmp/f.txt"]),
    ("cmd | tee /tmp/t.txt", ["/tmp/t.txt"]),
    ("tee -a /tmp/t.txt", ["/tmp/t.txt"]),
    ("cmd -o /tmp/o.json", ["/tmp/o.json"]),
    ("cmd -o/tmp/o.json", ["/tmp/o.json"]),
    ("cmd --output=/tmp/o.json", ["/tmp/o.json"]),
    ("cmd --output /tmp/o.json", ["/tmp/o.json"]),
    ("cmd --out /tmp/o.json", ["/tmp/o.json"]),
    ("cmd --out=/tmp/o.json", ["/tmp/o.json"]),
    ("dd if=x of=/tmp/d.bin", ["/tmp/d.bin"]),
    ("sed -i 's/a/b/' /tmp/s.txt", ["/tmp/s.txt"]),
    ("truncate -s0 /tmp/z", ["/tmp/z"]),
    ("truncate -s 0 /tmp/z", ["/tmp/z"]),
    ("cp a /tmp/c.json", ["/tmp/c.json"]),
    ("mv a /tmp/m.json", ["/tmp/m.json"]),
    ("cp -t /tmp a.json", ["/tmp/a.json"]),
    ("cp --target-directory=/tmp a.json", ["/tmp/a.json"]),
    ("cp a.json b.json /tmp/", ["/tmp/a.json", "/tmp/b.json"]),
    ('OUT=/tmp/v.txt; cmd > "$OUT"', ["/tmp/v.txt"]),
    ("export OUT=/tmp/e.txt; cmd > $OUT", ["/tmp/e.txt"]),
    ('cmd > "${TMPDIR:-/tmp}/out.txt"', ["/tmp/out.txt"]),
    ('cmd > "${TMPDIR-/tmp}/out.txt"', ["/tmp/out.txt"]),
    ("cmd > /private/tmp/p.txt", ["/tmp/p.txt"]),
    ("cmd > /var/tmp/v.txt", ["/var/tmp/v.txt"]),
    ("cmd > //tmp/x", ["/tmp/x"]),
    ("cmd > /tmp/./x", ["/tmp/x"]),
    ("cd /tmp && cmd > out.txt", ["/tmp/out.txt"]),
    ("cd /private/tmp; cmd -o out.json", ["/tmp/out.json"]),
    ("x=$(cmd 2>/tmp/err.txt)", ["/tmp/err.txt"]),
    ("cmd \\\n  > /tmp/cont.txt", ["/tmp/cont.txt"]),
    ('echo "a | b" > /tmp/pipe.txt', ["/tmp/pipe.txt"]),
    # A `cd` inside a subshell still moves the subshell's own writes.
    ("(cd /tmp && cmd > out.txt)", ["/tmp/out.txt"]),
    # A brace group runs in the block's own shell: its `cd` stays.
    ("{ cd /tmp; ls; }; cmd > out.txt", ["/tmp/out.txt"]),
    # Only the listed commands' `-o` is not an output.
    ("curl -o /tmp/deck.pdf https://example.com/d", ["/tmp/deck.pdf"]),
    # A literal staging folder pasted as text is held by the text alone; the transcript exempts it (below).
    (
        'STAGING_DIR=/tmp/market-sizing-acme.staging.Ab12Cd; cp f "$STAGING_DIR"',
        ["/tmp/market-sizing-acme.staging.Ab12Cd"],
    ),
    # wget's document and its log, in every spelling.
    ("wget -O /tmp/a.html http://x", ["/tmp/a.html"]),
    ("wget --output-document=/tmp/a.html http://x", ["/tmp/a.html"]),
    ("wget --output-document /tmp/a.html http://x", ["/tmp/a.html"]),
    ("wget -O/tmp/a.html http://x", ["/tmp/a.html"]),
    ("wget -q -O /tmp/x u", ["/tmp/x"]),
    ("wget -qO /tmp/x u", ["/tmp/x"]),
    ("wget -qO/tmp/x u", ["/tmp/x"]),
    ("wget -t 3 -O /tmp/x u", ["/tmp/x"]),
    ("wget -o /tmp/log u", ["/tmp/log"]),
    ("wget -a /tmp/log u", ["/tmp/log"]),
    ("wget --output-file=/tmp/log u", ["/tmp/log"]),
    ("wget --append-output /tmp/log u", ["/tmp/log"]),
    # A script's own `-o` after the shell that runs it; the shell's own `-o pipefail` is not a file.
    ("bash script.sh -o /tmp/x", ["/tmp/x"]),
    ("bash -e script.sh -o /tmp/x", ["/tmp/x"]),
    ("sh ./run.sh -o /tmp/x", ["/tmp/x"]),
    ("bash -o pipefail script.sh -o /tmp/x", ["/tmp/x"]),
    ("sh ./run.sh --output=/tmp/r.json", ["/tmp/r.json"]),
    # A script named like a listed command does not inherit that command's switch.
    ("sh zip -o /tmp/x", ["/tmp/x"]),
    # Accepted edge: `extglob` is read as the operand, and the outcome is still right.
    ("bash -O extglob script.sh -o /tmp/x", ["/tmp/x"]),
    ("set -o pipefail; cmd > /tmp/z", ["/tmp/z"]),
    # zip's archive (and its -O); tar's archive under a create or append mode.
    ("zip -r /tmp/acme_data.zip outputs/", ["/tmp/acme_data.zip"]),
    ("zip /tmp/out.zip f", ["/tmp/out.zip"]),
    ("cd /tmp && zip pack.zip f", ["/tmp/pack.zip"]),
    ("zip -O /tmp/new.zip old.zip", ["/tmp/new.zip"]),
    ("tar -czf /tmp/x.tgz d", ["/tmp/x.tgz"]),
    ("tar czf /tmp/x d", ["/tmp/x"]),
    ("tar -cf/tmp/x d", ["/tmp/x"]),
    ("tar -c -f /tmp/x d", ["/tmp/x"]),
    ("tar -f /tmp/x -c d", ["/tmp/x"]),
    ("tar --create --file=/tmp/x d", ["/tmp/x"]),
    ("tar -c --file /tmp/x d", ["/tmp/x"]),
    ("tar -rf /tmp/x more", ["/tmp/x"]),
    # A `case` pattern's `)` is not the end of the subshell around it.
    ("cd /tmp; (case $x in a) echo;; esac; cd /; ) ; echo > o2", ["/tmp/o2"]),
    # A top-level case's `cd` stays (conditional, but the text says it can happen), nested too.
    ("case $x in a|b) cd /tmp;; esac; cmd > out.txt", ["/tmp/out.txt"]),
    ("case $x in a) case $y in b) cd /tmp;; esac;; esac; cmd > out", ["/tmp/out"]),
    ('case "$x" in\n  a) cd /tmp ;;\n  *) true ;;\nesac\ncmd > out', ["/tmp/out"]),
    # RESIDUAL (a false hold): the shared substitution lifter ends the `$(` at the pattern's `)`, so the
    # `cd` is read in the outer block. A fix to the lifter flips this row, deliberately.
    ("x=$(case $y in a) cd /tmp;; esac); cmd > out", ["/tmp/out"]),
    # RESIDUALS (false holds, budget-bounded): a `case` with `in` on the next line or with no pattern is not
    # read as a case, so its parens are read as subshells; `zip -FF X --out Y` holds the X it only reads.
    ("(case $x\nin\n a) true;;\nesac; cd /tmp); cmd > out", ["/tmp/out"]),
    ("case $x in esac; (cd /tmp); echo > o", ["/tmp/o"]),
    ("zip -FF /tmp/x.zip --out /tmp/y.zip", ["/tmp/x.zip", "/tmp/y.zip"]),
]

PASSED = [
    "cmd >&2",
    "cmd 2>&1",
    "cmd > /dev/null",
    "cd /tmp && cmd >&2 2>&1 >&-",  # a descriptor, not a file in the folder
    'mv /tmp/x.json "$OUT/"',
    "cp /tmp/x out/",
    'cmd > "$STAGING_DIR/out.txt"',
    'STAGING_DIR=/tmp/market-sizing-acme.staging.Ab12Cd; cmd > "$STAGING_DIR/out.txt"',
    "cmd > /tmp/$RUN_ID/out.txt",
    'cmd > "/tmp/${RUN_ID}/x"',
    "cmd > /tmp/out_$$.txt",
    'F=$(mktemp); cmd > "$F"',
    'cmd > "$(mktemp)"',
    'cmd > "$TMPDIR/out.txt"',
    "cat /tmp/x.txt",
    "tail -5 /tmp/x.txt",
    "cmd < /tmp/in.txt",
    'cd "$D" && cmd > out.txt',
    "cd /tmp && cd sub && cmd > out.txt",
    "python3 -c \"open('/tmp/py.txt','w')\"",
    'bash -c "cmd > /tmp/b.txt"',
    "mkdir -p /tmp/scratch && cmd > /tmp/scratch/out.txt",
    "find /tmp -name x -o -name y",
    "cd /tmp && unzip -o -q pack.zip -d verify",  # seen in a kept run: `-o` there is a switch
    # For these commands `-o` is a switch or takes a value that is not a file they write.
    'unzip -o /tmp/deck.zip -d "$STAGING_DIR"',
    "grep -o /tmp/foo.txt log",
    "cd /tmp && grep -oE x f",
    "cd /tmp && unzip -oq pack.zip",
    "ps -o pid,comm > /dev/null",
    # A subshell's `cd` and assignments end with it.
    "(cd /tmp && ls); cmd > out.txt",
    "(cd /tmp && ls) ; cmd > out.txt",
    '(OUT=/tmp/x.txt); cmd > "$OUT"',
    "cmd > /tmp/*.txt",
    "cmd > ~/out.txt",
    # wget's `-` is stdout, glued or not; a name the URL chooses is a residual.
    "wget -O- http://x",
    "cd /tmp && wget -O- http://x",
    "cd /tmp && wget -O - http://x",
    "wget --output-document=- http://x",
    "wget -P /tmp u",
    "curl -O http://x/a",
    # A shell's own options; code after `-c` (a residual).
    "bash -o pipefail script.sh",
    'bash -c "x" -o /tmp/y',
    'set -o pipefail; cmd > "$STAGING_DIR/o"',
    "sh /tmp/run.sh",
    # zip: an archive the shell names, stdout, a temp-path value, a read mode, a pattern.
    'zip -r "$STAGING_DIR/a.zip" d',
    'zip - f > "$STAGING_DIR/a.zip"',
    "zip -b /tmp out.zip f",
    "zip -T /tmp/x.zip",
    "zip -sf /tmp/x.zip",
    "zip -r out.zip d -x /tmp/y",
    "unzip -o /tmp/deck.zip -d x",
    # tar: read modes, stdout, -C (the archive is not relative to it).
    "tar -xf /tmp/x.tar",
    "tar xzf /tmp/x.tgz",
    "tar -tf /tmp/x",
    'tar -czf - d > "$STAGING_DIR/x"',
    "tar -C /tmp -czf out.tgz d",
    # A `case` inside a subshell: its pattern `)` does not end the subshell early, and its `cd` ends with it.
    "(case $x in a) true;; esac; cd /tmp); echo hi > out",
    "(case $x in (a) true;; esac; cd /tmp); echo hi > out",
    "(case $x in a) cd /tmp;; esac); cmd > out",
    '(\ncase "$x" in\n  a) cd /tmp ;;\nesac\n)\ncmd > out',
    # RESIDUALS (misses): an archive named after zip's patterns; tar under another name.
    'zip -x "*.git*" -r /tmp/a.zip .',
    "gtar -czf /tmp/x d",
]


def _said(text: str) -> dict[str, Any]:
    """The model's final message as a transcript row."""
    return {"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}}


@pytest.mark.parametrize(("command", "expected"), DENIED, ids=[c[:50] for c, _ in DENIED])
def test_a_fixed_name_written_directly_in_tmp_is_found(command: str, expected: list[str]) -> None:
    assert CHECK.hits(command) == expected


@pytest.mark.parametrize("command", PASSED, ids=[c[:50] for c in PASSED])
def test_a_name_the_shell_decides_a_folder_below_tmp_or_a_read_is_not(command: str) -> None:
    assert CHECK.hits(command) == []


# --- decide: scope, provenance, budget ------------------------------------------------------------------


def _user(text: str, **extra: Any) -> dict[str, Any]:
    return {"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": text}]}, **extra}


def _skill(name: str) -> dict[str, Any]:
    use = {"type": "tool_use", "id": "toolu_skill", "name": "Skill", "input": {"skill": name}}
    return {"type": "assistant", "message": {"content": [use]}}


def _shell(call_id: str, command: str, result: str, *, is_error: bool = False, **extra: Any) -> list[dict[str, Any]]:
    use = {"type": "tool_use", "id": call_id, "name": SHELL, "input": {"command": command}}
    res = {"type": "tool_result", "tool_use_id": call_id, "content": result, "is_error": is_error}
    return [
        {"type": "assistant", "message": {"content": [use]}, **extra},
        {"type": "user", "message": {"content": [res]}, **extra},
    ]


def _hold(call_id: str, path: str, **extra: Any) -> list[dict[str, Any]]:
    """A shell call this check held, as the runtime records it."""
    reason = f"{DENY_PREFIX}[shared-tmp][{path}] Held: this command writes {path}."
    return _shell(call_id, f"cmd > {path}", reason, is_error=True, **extra)


def _started() -> list[dict[str, Any]]:
    return [_user("Size my market."), _skill("founder-skills:market-sizing")]


def _payload(
    tmp_path: Path, rows: list[dict[str, Any]] | None, command: str = INCIDENT, **extra: Any
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "hook_event_name": "PreToolUse",
        "tool_name": SHELL,
        "tool_input": {"command": command},
        **extra,
    }
    if rows is not None:
        transcript = tmp_path / "t.jsonl"
        transcript.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
        payload["transcript_path"] = str(transcript)
    return payload


def _held(decision: dict[str, Any] | None) -> str | None:
    if decision is None:
        return None
    out = decision["hookSpecificOutput"]
    assert out["permissionDecision"] == "deny" and out["hookEventName"] == "PreToolUse"
    return str(out["permissionDecisionReason"])


def test_a_started_skills_fixed_tmp_write_is_held_naming_the_path_and_the_fix(tmp_path: Path) -> None:
    reason = _held(CHECK.decide(_payload(tmp_path, _started())))
    assert reason is not None
    assert reason.startswith("[shared-tmp][/tmp/compose_out.txt] Held:")
    assert "$STAGING_DIR" in reason and "compose_result.json" in reason


@pytest.mark.parametrize(
    ("command", "path"),
    [
        ("wget -qO /tmp/page.html https://example.com/p", "/tmp/page.html"),
        ('bash "$SCRIPTS/export.sh" -o /tmp/export.json', "/tmp/export.json"),
        ("zip -r /tmp/acme_working_data.zip outputs/", "/tmp/acme_working_data.zip"),
        ("tar -czf /tmp/acme_working_data.tgz outputs/", "/tmp/acme_working_data.tgz"),
        ("(case $m in a) echo;; esac; cd /); cd /tmp; cmd > notes.txt", "/tmp/notes.txt"),
    ],
    ids=["wget", "script-args", "zip", "tar", "case"],
)
def test_each_new_write_class_reaches_the_deny(tmp_path: Path, command: str, path: str) -> None:
    """Not only `hits`: the hold is the decision the runtime receives, with the path's marker."""
    reason = _held(CHECK.decide(_payload(tmp_path, _started(), command=command)))
    assert reason is not None and reason.startswith(f"[shared-tmp][{path}] Held:")


def test_several_paths_are_held_together_each_with_its_own_marker(tmp_path: Path) -> None:
    reason = _held(CHECK.decide(_payload(tmp_path, _started(), command="a > /tmp/a.txt; b > /tmp/b.txt")))
    assert reason is not None and reason.startswith("[shared-tmp][/tmp/a.txt][shared-tmp][/tmp/b.txt] Held:")


def test_a_command_that_does_not_name_tmp_loads_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The hook runs on every shell call: one with no "/tmp" in its text ends before the parser loads."""
    check = _load("shared_tmp_check")

    def boom(name: str) -> Any:
        raise AssertionError(f"loaded {name}")

    monkeypatch.setattr(check, "_load", boom)
    assert check.decide(_payload(tmp_path, _started(), command="python3 x.py > out.txt")) is None
    with pytest.raises(AssertionError, match="loaded dispatch_prompt_check"):  # lever engaged
        check.decide(_payload(tmp_path, _started()))


def test_a_command_that_writes_nothing_fixed_in_tmp_passes(tmp_path: Path) -> None:
    assert CHECK.decide(_payload(tmp_path, _started(), command='cmd > "$STAGING_DIR/out.txt"')) is None


@pytest.mark.parametrize("tool", ["Agent", "Read", "Write", "AskUserQuestion"])
def test_a_tool_that_is_not_a_shell_is_never_checked(tmp_path: Path, tool: str) -> None:
    payload = _payload(tmp_path, _started(), tool_name=tool)
    payload["tool_input"] = {"command": INCIDENT, "file_path": "/tmp/x.json", "prompt": INCIDENT}
    assert CHECK.decide(payload) is None


@pytest.mark.parametrize("tool_input", [None, "x", {"command": 3}, {}])
def test_a_malformed_input_passes(tmp_path: Path, tool_input: Any) -> None:
    payload = _payload(tmp_path, _started())
    payload["tool_input"] = tool_input
    assert CHECK.decide(payload) is None


def test_a_session_that_started_no_founder_skills_skill_passes_without_parsing_the_transcript(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Another plugin's shell work is not policed, and its transcript (which can be tens of MB) is not
    parsed to find that out."""
    check = _load("shared_tmp_check")
    calls: list[str] = []

    def reader(path: str) -> list[dict[str, Any]]:
        calls.append(path)
        raise AssertionError("the transcript was parsed")

    monkeypatch.setattr(check, "_rows", reader)
    rows = [_user("Tidy my csv files."), _skill("other-plugin:csv-tools")]
    assert check.decide(_payload(tmp_path, rows)) is None
    assert calls == []
    # Lever engaged: the same reader IS reached once a founder-skills skill is named.
    with pytest.raises(AssertionError, match="parsed"):
        check.decide(_payload(tmp_path, _started()))
    assert len(calls) == 1


def test_another_plugins_skill_of_the_same_name_is_not_ours(tmp_path: Path) -> None:
    rows = [_user("Go."), _skill("other-plugin:market-sizing")]
    assert CHECK.decide(_payload(tmp_path, rows)) is None


def test_a_slash_command_starts_the_skill(tmp_path: Path) -> None:
    rows = [_user("<command-name>/founder-skills:market-sizing</command-name>")]
    assert _held(CHECK.decide(_payload(tmp_path, rows))) is not None


def test_a_skill_name_a_tool_returned_does_not_put_the_session_in_scope(tmp_path: Path) -> None:
    """Work on this repository reads SKILL.md files and transcripts full of our skill names; text a tool
    returned is not a skill the session started."""
    rows = [
        _user("Grep the docs."),
        *_shell("toolu_g", "grep -r command-name .", "<command-name>/market-sizing</command-name>"),
    ]
    assert CHECK.decide(_payload(tmp_path, rows)) is None


def test_running_an_installed_plugin_script_puts_the_command_in_scope_with_no_skill_row(tmp_path: Path) -> None:
    """The cloud lane: a skill typed as the first message leaves no Skill row."""
    command = f"python3 {INSTALLED}/skills/ic-sim/scripts/zz_probe_tool.py --dir w7 > /tmp/probe_7.txt"
    assert _held(CHECK.decide(_payload(tmp_path, [_user("Size my market.")], command=command))) is not None
    via_var = f'SCRIPTS="{INSTALLED}/skills/ic-sim/scripts"; python3 "$SCRIPTS/compose_report.py" > /tmp/out.txt'
    assert _held(CHECK.decide(_payload(tmp_path, [_user("Go.")], command=via_var))) is not None


@pytest.mark.parametrize(
    "command",
    [
        "python3 scripts/compose_report.py > /tmp/out.txt",  # another repository's script of the same name
        'python3 "$SCRIPTS/compose_report.py" > /tmp/out.txt',  # a variable the block does not assign
        'python3 "$ROOT/skills/market-sizing/scripts/compose_report.py" > /tmp/out.txt',
        # an unassigned variable in front of, or inside, an install path
        'python3 "$HOME/.claude/plugins/cache/m/founder-skills/skills/ic-sim/scripts/compose_report.py" > /tmp/o.txt',
        'python3 "/home/$USER/.claude/plugins/cache/m/founder-skills/skills/ic-sim/scripts/compose_report.py" > /tmp/o',
        f"python3 {SCRIPTS.parent}/skills/market-sizing/scripts/compose_report.py > /tmp/out.txt",  # this checkout
        "python3 /home/u/src/skills/market-sizing/scripts/compose_report.py > /tmp/out.txt",  # not installed
    ],
)
def test_a_script_outside_an_installed_plugin_does_not_put_the_command_in_scope(tmp_path: Path, command: str) -> None:
    assert CHECK.decide(_payload(tmp_path, [_user("Go.")], command=command)) is None


def test_a_path_a_mktemp_call_printed_is_not_held(tmp_path: Path) -> None:
    """A staging folder pasted as text: Step 0 made it with mktemp and printed it."""
    staging = "/tmp/market-sizing-acme.staging.Ab12Cd"
    step0 = _shell(
        "toolu_s0",
        'STAGING_DIR="$(mktemp -d "${TMPDIR:-/tmp}/market-sizing-acme.staging.XXXXXX")"; '
        "printf 'STAGING_DIR=%s\\n' \"$STAGING_DIR\"",
        f"RUN_ID=r1\nSTAGING_DIR={staging}\n",
    )
    pasted = f"cp inputs.json {staging}"
    assert _held(CHECK.decide(_payload(tmp_path, [*_started(), *step0], command=pasted))) is None
    literal = f'STAGING_DIR={staging}; cp f "$STAGING_DIR"'
    assert _held(CHECK.decide(_payload(tmp_path, [*_started(), *step0], command=literal))) is None
    # Without the mktemp call that printed it, the same literal is held.
    assert _held(CHECK.decide(_payload(tmp_path, _started(), command=pasted))) is not None
    # A path some other command printed is not exempt.
    printed_by_echo = _shell("toolu_e", f"echo {staging}", staging)
    assert _held(CHECK.decide(_payload(tmp_path, [*_started(), *printed_by_echo], command=pasted))) is not None


def test_two_holds_per_path_then_it_is_let_through_with_a_stderr_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    once = [*_started(), *_hold("toolu_h1", "/tmp/compose_out.txt")]
    assert _held(CHECK.decide(_payload(tmp_path, once))) is not None
    twice = [*once, *_hold("toolu_h2", "/tmp/compose_out.txt")]
    assert CHECK.decide(_payload(tmp_path, twice)) is None
    assert "let through after 2 holds" in capsys.readouterr().err


def test_one_paths_holds_do_not_spend_anothers(tmp_path: Path) -> None:
    rows = [*_started(), *_hold("toolu_h1", "/tmp/other.txt"), *_hold("toolu_h2", "/tmp/other.txt")]
    assert _held(CHECK.decide(_payload(tmp_path, rows))) is not None


def test_a_marker_in_a_sub_agents_rows_does_not_spend_the_main_threads_holds(tmp_path: Path) -> None:
    side = [*_hold("toolu_h1", "/tmp/compose_out.txt", isSidechain=True)] * 2
    assert _held(CHECK.decide(_payload(tmp_path, [*_started(), *side]))) is not None


def test_a_sub_agents_call_is_let_through_with_a_stderr_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The runtime sets `agent_id` only for a call made inside a sub-agent. Its holds land in the
    sub-agent's own transcript, which the budget does not count, so a hold could never end."""
    assert CHECK.decide(_payload(tmp_path, _started(), agent_id="a1b2c3")) is None
    assert "sub-agent" in capsys.readouterr().err
    assert _held(CHECK.decide(_payload(tmp_path, _started(), agent_id=""))) is not None


def test_no_transcript_passes_with_a_stderr_line_only_for_our_scripts(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    command = f"python3 {INSTALLED}/skills/market-sizing/scripts/compose_report.py > /tmp/out.txt"
    assert CHECK.decide(_payload(tmp_path, None, command=command)) is None
    assert "no transcript" in capsys.readouterr().err
    assert CHECK.decide(_payload(tmp_path, None)) is None
    assert capsys.readouterr().err == ""


# --- through the dispatcher ----------------------------------------------------------------------------


def _wrapper(payload: dict[str, Any]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["sh", str(WRAPPER)], input=json.dumps(payload), capture_output=True, text=True, timeout=30)


def test_the_wrapper_holds_the_incident_command(tmp_path: Path) -> None:
    r = _wrapper(_payload(tmp_path, _started()))
    assert r.returncode == 0, r
    out = json.loads(r.stdout)["hookSpecificOutput"]
    assert out["permissionDecision"] == "deny"
    assert out["permissionDecisionReason"].startswith("[shared-tmp][/tmp/compose_out.txt]")


def test_the_wrapper_is_silent_on_a_shell_call_that_does_not_name_tmp(tmp_path: Path) -> None:
    r = _wrapper(_payload(tmp_path, _started(), command="ls -la"))
    assert r.returncode == 0 and r.stdout == "" and r.stderr == "", r


def _record_loads(monkeypatch: pytest.MonkeyPatch, payload: dict[str, Any]) -> list[str]:
    dispatch = _load("pretooluse_dispatch")
    loaded: list[str] = []

    class _Pass:
        @staticmethod
        def decide(_payload: dict[str, Any]) -> None:
            return None

    def fake(name: str) -> Any:
        loaded.append(name)
        return _Pass

    monkeypatch.setattr(dispatch, "_load", fake)
    monkeypatch.setattr(sys, "stdin", __import__("io").StringIO(json.dumps(payload)))
    with pytest.raises(SystemExit):
        dispatch.main()
    return loaded


@pytest.mark.parametrize("tool", [SHELL, "Bash"])
def test_a_shell_call_runs_only_the_shell_check(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tool: str) -> None:
    assert _record_loads(monkeypatch, _payload(tmp_path, None, tool_name=tool)) == ["shared_tmp_check"]


@pytest.mark.parametrize("tool", ["Agent", "Task", "AskUserQuestion"])
def test_a_dispatch_or_question_never_runs_the_shell_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tool: str
) -> None:
    loaded = _record_loads(monkeypatch, _payload(tmp_path, None, tool_name=tool))
    assert "shared_tmp_check" not in loaded and loaded[0] == "dispatch_type_check" and len(loaded) == 6


def test_a_check_that_raises_fails_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    dispatch = _load("pretooluse_dispatch")

    class _Boom:
        @staticmethod
        def decide(_payload: dict[str, Any]) -> None:
            raise RuntimeError("boom")

    monkeypatch.setattr(dispatch, "_load", lambda _name: _Boom)
    monkeypatch.setattr(sys, "stdin", __import__("io").StringIO(json.dumps(_payload(tmp_path, _started()))))
    with pytest.raises(SystemExit) as e:
        dispatch.main()
    assert e.value.code == 0
    out = capsys.readouterr()
    assert out.out == "" and "shared_tmp_check: RuntimeError: boom" in out.err


# --- the Stop hook reads a held call as one that never ran ----------------------------------------------

STOP_WRAPPER = SCRIPTS / "stop-handover-check.sh"
COMPOSE = 'python3 "$SCRIPTS/compose_report.py" --dir "$ANALYSIS_DIR" -o "$ANALYSIS_DIR/report.json"'
LINKED = "Here is your review: [the written report](computer:///sessions/x/mnt/outputs/Review.md).\n"


def _stop(tmp_path: Path, rows: list[dict[str, Any]]) -> subprocess.CompletedProcess[str]:
    transcript = tmp_path / "stop.jsonl"
    transcript.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    payload = {
        "session_id": "s",
        "transcript_path": str(transcript),
        "cwd": str(tmp_path / "outputs"),
        "hook_event_name": "Stop",
        "stop_hook_active": False,
    }
    return subprocess.run(
        ["sh", str(STOP_WRAPPER)], input=json.dumps(payload), capture_output=True, text=True, timeout=30
    )


def _built(*after: dict[str, Any]) -> list[dict[str, Any]]:
    snapshot = {
        "type": "attachment",
        "entrypoint": "local-agent",
        "attachment": {
            "type": "prompt_snapshot",
            "tools": [{"name": n} for n in (SHELL, "mcp__cowork__present_files")],
        },
    }
    return [snapshot, _user("Review this deck."), *_shell("toolu_c", COMPOSE, "{}"), *after]


def test_a_shell_call_held_for_tmp_after_the_report_does_not_stop_the_delivery_ask(tmp_path: Path) -> None:
    rows = _built(
        *_hold("toolu_h", "/tmp/notes.txt"),
        {"type": "assistant", "message": {"content": [{"type": "text", "text": LINKED}]}},
    )
    out = json.loads(_stop(tmp_path, rows).stdout)
    assert out["decision"] == "block" and "mcp__cowork__present_files" in out["reason"]


def test_any_other_failed_shell_call_after_the_report_still_does(tmp_path: Path) -> None:
    """Negative control: the exemption is the marker, not every hook error."""
    failed = _shell("toolu_f", "cmd > /tmp/notes.txt", f"{DENY_PREFIX}[dispatch-check] Held.", is_error=True)
    rows = _built(*failed, {"type": "assistant", "message": {"content": [{"type": "text", "text": LINKED}]}})
    assert _stop(tmp_path, rows).stdout == ""


def test_a_held_closing_call_run_again_is_judged_on_the_rerun(tmp_path: Path) -> None:
    from test_stop_handover_hook import CLOSING_CMD, OWN_VERDICT, PRINTED

    held = _shell(
        "toolu_c1", f"{CLOSING_CMD} | tee /tmp/h.txt", f"{DENY_PREFIX}[shared-tmp][/tmp/h.txt] Held.", is_error=True
    )
    rerun = _shell("toolu_c2", CLOSING_CMD, PRINTED)
    rows = [_user("Example Co asks for the market-sizing skill on its seed deck."), *held, *rerun]
    verdict = _said(OWN_VERDICT)
    out = json.loads(_stop(tmp_path, [*rows, verdict]).stdout)
    assert out["decision"] == "block" and PRINTED.rstrip() in out["reason"]
    carried = _said("Done.\n\n" + PRINTED)
    assert _stop(tmp_path, [*rows, carried]).stdout == ""


# --- the skills' own commands write no fixed name in /tmp -----------------------------------------------

_FENCE_RE = re.compile(r"^```(?:bash|sh|shell)?[ \t]*\n(.*?)^```", re.MULTILINE | re.DOTALL)


def _skill_commands() -> list[tuple[str, str]]:
    files = sorted(PLUGIN.glob("skills/*/SKILL.md")) + sorted(PLUGIN.glob("skills/*/references/**/*.md"))
    files += sorted((PLUGIN / "references").rglob("*.md"))
    return [(str(f.relative_to(PLUGIN)), m.group(1)) for f in files for m in _FENCE_RE.finditer(f.read_text("utf-8"))]


def test_no_skill_command_writes_a_fixed_name_in_tmp() -> None:
    """Our own hook would hold such a command at run time."""
    blocks = _skill_commands()
    # Non-vacuity: the extraction reaches the commands, including the staging folder's own /tmp line.
    assert len(blocks) > 100
    assert any("mktemp" in b and "/tmp" in b for _f, b in blocks)
    found = [(f, h) for f, b in blocks for h in CHECK.hits(b)]
    assert found == []


def test_the_skill_command_scan_finds_a_seeded_write() -> None:
    """Positive control: the same extraction and classifier find a fixed /tmp write placed in a fence."""
    seeded = 'Run:\n\n```bash\npython3 "$SCRIPTS/compose_report.py" > /tmp/seed.txt\n```\n'
    blocks = [m.group(1) for m in _FENCE_RE.finditer(seeded)]
    assert [h for b in blocks for h in CHECK.hits(b)] == ["/tmp/seed.txt"]
