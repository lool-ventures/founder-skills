#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""A shell command that writes a fixed name directly in /tmp is held, and told to use the run's own folder.

THE DEFECT. In a local Cowork session every session runs as its own user and all of them share one
/tmp. A file another session left there is readable and not writable. A run wrote
`compose_report.py ... > /tmp/compose_out.txt 2>&1; tail -5 /tmp/compose_out.txt`: the redirect failed,
so the shell never started the script, and `tail` printed the other session's output, which the model
read as its own success. SKILL.md already says scratch output goes in $STAGING_DIR; that did not hold.

WHAT IS HELD. A write, read from the command's own text, whose target is a fixed name whose parent is
exactly /tmp, /private/tmp or /var/tmp: an output redirect (`>`, `>>`, `>|`, `&>`, `N>`, `>& FILE`),
`tee`, `dd of=`, `truncate`, `sed -i`, the destination of `cp`/`mv`/`install`/`rsync`/`ln` (`-t DIR`
too, and a bare /tmp destination, which writes the source's name there), and any command's
`-o`/`--output`/`--out` value. A name is fixed when nothing in it is left to the shell once the block's
own literal assignments are filled in; `${TMPDIR:-/tmp}` reads as /tmp, since TMPDIR is unset in the
Cowork VM. A relative target counts after an in-block literal `cd /tmp`. Heredoc bodies are not
commands and are skipped; a heredoc this cannot follow leaves every line read as commands.

WHAT IS NOT. A name with anything still to expand (`$STAGING_DIR/x`, bare `$TMPDIR/x`, `$(mktemp)`,
`/tmp/out_$$.txt`), a path below a folder in /tmp (`/tmp/<dir>/<file>`), /dev, every read, a copy or
move OUT of /tmp, a path the transcript shows `mktemp` printed (a staging folder pasted as text), and
code a command runs (`bash -c "..."`, `python3 -c "open(...)"`): KNOWN RESIDUALS, with a fixed folder
under /tmp, a name assigned in an earlier shell call, and a `cd` to a folder it cannot read.

SCOPE. Only a founder-skills run: the transcript's main thread started one of the six analysis skills
(a `Skill` call or a typed `<command-name>`; text a tool returned does not count), or the command runs
one of their scripts from an installed plugin (the cloud lane, where a skill typed as the first message
leaves no such row). A script under a variable the block does not assign, or under this repository's
own checkout, does not count. A call from inside a sub-agent (the hook input's `agent_id`, which the
runtime sets only there) passes with a stderr line: its holds are written to the sub-agent's own
transcript, which this does not count, so a hold there could never end. No transcript: passes.

THE BUDGET. `[shared-tmp][<path>]` per path at the head of the reason, at most two holds per path
(counted on the main thread's rows), then let through with a stderr line: a hook that holds forever can
wedge a run on its own misreading. The Stop hook's delivery ask does not read a call this held as a
failed one.

COST. The hook runs on every shell call. Nothing is loaded and nothing read unless the command text
contains "/tmp"; the transcript is read only once the command itself writes a fixed name there.
"""

from __future__ import annotations

import importlib.util
import os
import re
import shlex
import sys
from typing import Any

MARKER = "[shared-tmp]"
MAX_HOLDS = 2
SKILLS = (
    "cap-table",
    "competitive-positioning",
    "deck-review",
    "financial-model-review",
    "ic-sim",
    "market-sizing",
)
# Anchored at the word's start: `$HOME/.claude/plugins/...` names no root this can read.
_SCRIPT_RE = re.compile(r"^(/[^\s'\"]*?)/skills/(" + "|".join(SKILLS) + r")/scripts/")
# `${TMPDIR:-X}` / `${TMPDIR-X}` with a literal default: TMPDIR is unset in the Cowork VM.
_TMPDIR_DEFAULT_RE = re.compile(r"\$\{TMPDIR:?-([^}$`]*)\}")
_DYNAMIC_RE = re.compile(r"[$`*?\[~]|__SUBST\d+__")
_ASSIGN_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$", re.DOTALL)
_CUTS = frozenset({";", "&&", "||", "|", "&", "(", ")", "{", "}", ";;", "|&"})
_LEADERS = frozenset({"then", "do", "else", "elif", "!", "time", "command", "exec", "nohup", "sudo"})
_COPIERS = frozenset({"cp", "mv", "install", "rsync", "ln"})
# Flags whose next word is a value, not a file the command writes.
_VALUE_FLAGS = {
    "truncate": ("-s", "--size", "-r", "--reference"),
    "sed": ("-e", "-f", "--expression", "--file"),
}
_OTHER_BREAKS = re.compile("[\r\v\f\x1c\x1d\x1e\x85  ]")

_HERE = os.path.dirname(os.path.abspath(__file__))


def _load(name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, os.path.join(_HERE, f"{name}.py"))
    if spec is None or spec.loader is None:
        raise ImportError(name)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _rows(path: str) -> list[dict[str, Any]]:
    """The transcript's rows (one json parse per line): called only once the command is a hit."""
    return list(_load("stop_handover_check").read_transcript(path))


def _is_shell(name: Any) -> bool:
    return isinstance(name, str) and (name == "Bash" or name.endswith("__bash"))


def _tokens(text: str) -> list[str] | None:
    lex = shlex.shlex(text, posix=True, punctuation_chars=True)
    lex.whitespace_split = True
    lex.commenters = "#"
    try:
        return list(lex)
    except ValueError:
        return None


class _Block:
    """One shell block read as text: its assignments, its folder and what it writes, in order."""

    def __init__(self, dp: Any) -> None:
        self.dp = dp
        self.env: dict[str, str] = {}
        self.cwd: str | None = None  # an in-block literal `cd`, or None when unknown
        self.targets: list[str] = []  # fixed absolute paths written, as typed after expansion
        self.dirs: set[str] = set()  # paths the block uses as a folder (`mkdir X`, `X/...`)
        self.words: list[str] = []  # every word, expanded where it can be

    def fill(self, word: str) -> str:
        word = _TMPDIR_DEFAULT_RE.sub(lambda m: m.group(1), word)
        for _ in range(4):
            new = self.dp._VAR_RE.sub(lambda m: self.env.get(m.group(1) or m.group(2), m.group(0)), word)
            if new == word:
                break
            word = new
        return word

    def fixed(self, word: str) -> str | None:
        """The absolute path a target word names, or None when the shell decides it."""
        w = self.fill(word)
        if not w or _DYNAMIC_RE.search(w):
            return None
        if not w.startswith("/"):
            if self.cwd is None:
                return None
            w = os.path.join(self.cwd, w)
        return w

    def segment(self, words: list[str], writes: list[str]) -> None:
        while words and _ASSIGN_RE.match(words[0]):
            name, value = _ASSIGN_RE.match(words[0]).groups()  # type: ignore[union-attr]
            filled = self.fill(value)
            if _DYNAMIC_RE.search(filled):
                self.env.pop(name, None)
            else:
                self.env[name] = filled
            words = words[1:]
        while words and (words[0] in _LEADERS or words[0] == "env"):
            words = words[1:]
            while words and words[0].startswith("-"):
                words = words[1:]
        if words and words[0] in ("export", "local", "declare", "readonly"):
            self.segment([w for w in words[1:] if not w.startswith("-")], [])
            words = []
        self.words += [self.fill(w) for w in words]
        found = list(writes)
        if words:
            name = os.path.basename(words[0])
            args = words[1:]
            if name == "cd":
                dest = self.fixed(args[0]) if args and args[0] != "-" else None
                self.cwd = self.dp.norm_path(dest) if dest else None
            elif name == "mkdir":
                self.dirs.update(p for p in (self.fixed(a) for a in args if not a.startswith("-")) if p)
            found += self._command_targets(name, args)
        for t in found:
            p = self.fixed(t)
            if p is not None:
                self.targets.append(p)

    def _command_targets(self, name: str, args: list[str]) -> list[str]:
        out: list[str] = []
        operands: list[str] = []
        target_dir: str | None = None
        skip = False
        for i, a in enumerate(args):
            if skip:
                skip = False
                continue
            nxt = args[i + 1] if i + 1 < len(args) else None
            if a in ("-o", "--output", "--out") and nxt is not None:
                if not nxt.startswith("-"):  # `unzip -o -q`: there `-o` is a switch, not an output
                    out.append(nxt)
                skip = True
            elif a.startswith(("--output=", "--out=")):
                out.append(a.split("=", 1)[1])
            elif a.startswith("-o") and not a.startswith("--") and len(a) > 2:
                out.append(a[2:])
            elif name in _COPIERS and a in ("-t", "--target-directory") and nxt is not None:
                target_dir = nxt
                skip = True
            elif name in _COPIERS and a.startswith("--target-directory="):
                target_dir = a.split("=", 1)[1]
            elif name in _COPIERS and a.startswith("-t") and len(a) > 2 and not a.startswith("--"):
                target_dir = a[2:]
            elif nxt is not None and a in _VALUE_FLAGS.get(name, ()):
                skip = True  # the flag's value, not a file it writes
            elif a.startswith("-") and a != "-":
                continue
            else:
                operands.append(a)
        if name == "tee" or name == "truncate":
            out += operands
        elif name == "dd":
            out += [a[3:] for a in args if a.startswith("of=")]
        elif name == "sed" and any(a.startswith("-i") or a.startswith("--in-place") for a in args):
            out += operands
        elif name in _COPIERS:
            if target_dir is not None:
                out += [target_dir.rstrip("/") + "/" + os.path.basename(s.rstrip("/")) for s in operands]
            elif len(operands) >= 2:
                dest = operands[-1]
                path = self.fixed(dest)
                if path is not None and self.dp.norm_path(path) in self.dp._SHARED_TMP:
                    # a bare /tmp destination writes each source under its own name there
                    out += [path.rstrip("/") + "/" + os.path.basename(s.rstrip("/")) for s in operands[:-1]]
                elif not dest.endswith("/"):
                    out.append(dest)
        return out

    def read(self, text: str) -> None:
        """Walk one command: its segments, assignments, folder changes and writes, in order."""
        tokens = _tokens(text)
        if tokens is None:
            return  # a quote never closed: nothing read, nothing claimed
        words: list[str] = []
        writes: list[str] = []
        n = 0
        while n <= len(tokens):
            tok = tokens[n] if n < len(tokens) else ";"
            n += 1
            if tok in _CUTS:
                self.segment(words, writes)
                words, writes = [], []
                continue
            if tok and set(tok) <= set("<>&|") and ("<" in tok or ">" in tok):
                target = tokens[n] if n < len(tokens) else ""
                n += 1
                if ">" in tok and not (tok.endswith("&") and re.fullmatch(r"[0-9-]+", target)):
                    writes.append(target)
                if words and words[-1].isdigit():
                    words.pop()
                continue
            words.append(tok)


def scan(command: str, dp: Any) -> _Block:
    """The block read for writes. Heredoc bodies are skipped; when a heredoc cannot be followed every
    line is read as commands. A `$(...)` is read as a block of its own."""
    lines = command.splitlines()
    bodies = None if _OTHER_BREAKS.search(command) else dp._heredoc_bodies(lines)
    kept = "\n".join(line for i, line in enumerate(lines) if not bodies or i not in bodies)
    kept = re.sub(r"\\\n", " ", kept)
    lifted = dp._lift_substitutions(kept)
    text, subs = lifted if lifted is not None else (kept, [])
    block = _Block(dp)
    for body in subs:
        block.targets += scan(body, dp).targets
    pending: list[str] = []
    for line in text.split("\n"):
        pending.append(line)
        joined = "\n".join(pending)
        if _tokens(joined) is None and len(pending) < 50:
            continue  # a quote still open: the command goes on
        pending = []
        block.read(joined)
    if pending:
        block.read("\n".join(pending))
    return block


def hits(command: str, dp: Any | None = None) -> list[str]:
    """The fixed names the command writes directly in /tmp, /private/tmp or /var/tmp, normalised, in order."""
    dp = dp if dp is not None else _load("dispatch_prompt_check")
    block = scan(command, dp)
    out: list[str] = []
    for t in block.targets:
        p = dp.norm_path(t)
        if p in out or p in block.dirs or any(w.startswith(p + "/") for w in block.words):
            continue  # already named, or used as a folder by the same block
        if os.path.dirname(p) in dp._SHARED_TMP and p not in dp._SHARED_TMP:
            out.append(p)
    return out


def _runs_our_script(command: str, dp: Any) -> bool:
    """The command runs a founder-skills script from an installed plugin, read through its own assignments."""
    for w in scan(command, dp).words:
        for m in _SCRIPT_RE.finditer(w):
            root = m.group(1)
            if "$" in root:  # a variable the block does not assign: not a root this can read
                continue
            r = dp.norm_path(root)
            own_checkout = r == dp.norm_path(dp.HOOK_PLUGIN_ROOT) and not any(
                mark in r + "/" for mark in dp._INSTALL_MARKERS
            )
            if not own_checkout and dp._installed_root(root):
                return True
    return False


def _from_mktemp(rows: list[dict[str, Any]], paths: list[str], dp: Any, dt: Any) -> set[str]:
    """The paths a main-thread shell call running `mktemp` printed (a staging folder pasted as text)."""
    commands: dict[str, str] = {}
    found: set[str] = set()
    for row in rows:
        if row.get("isSidechain"):
            continue
        content = (row.get("message") or {}).get("content")
        if not isinstance(content, list):
            continue
        for b in content:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "tool_use" and _is_shell(b.get("name")):
                cmd = (b.get("input") or {}).get("command")
                if isinstance(cmd, str) and "mktemp" in cmd and isinstance(b.get("id"), str):
                    commands[b["id"]] = cmd
            elif b.get("type") == "tool_result" and b.get("tool_use_id") in commands:
                text = "\n".join(dt.strings(b.get("content")))
                for word in re.findall(r"/[^\s'\"=:;,]+", text):
                    p = dp.norm_path(word.rstrip("/"))
                    if p in paths:
                        found.add(p)
    return found


def _holds(rows: list[dict[str, Any]], path: str, dt: Any) -> int:
    mark = f"{MARKER}[{path}]"
    return sum(
        1
        for row in rows
        if row.get("type") == "user"
        and not row.get("isSidechain")
        and any(mark in t for t in dt.strings(row.get("message")))
    )


def decide(payload: dict[str, Any]) -> dict[str, Any] | None:
    if payload.get("hook_event_name") != "PreToolUse" or not _is_shell(payload.get("tool_name")):
        return None
    tool_input = payload.get("tool_input")
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if not isinstance(command, str) or "/tmp" not in command:
        return None  # nearly every shell call ends here, having loaded nothing
    dp = _load("dispatch_prompt_check")
    found = hits(command, dp)
    if not found:
        return None
    agent = payload.get("agent_id")
    if isinstance(agent, str) and agent:
        print(f"shared_tmp_check: a sub-agent writes {', '.join(found)}; not held", file=sys.stderr)
        return None
    transcript = payload.get("transcript_path")
    ours = _runs_our_script(command, dp)
    if not isinstance(transcript, str) or not os.path.isfile(transcript):
        if ours:
            print(f"shared_tmp_check: {', '.join(found)} written; no transcript, not held", file=sys.stderr)
        return None
    if not ours:
        with open(transcript, encoding="utf-8", errors="replace") as fh:
            raw = fh.read()
        if not any(skill in raw for skill in SKILLS):
            return None  # no founder-skills skill named anywhere: nothing to parse
    rows = _rows(transcript)
    dt = _load("dispatch_type_check")
    if not ours and not dt.invocations(rows):
        return None
    made = _from_mktemp(rows, found, dp, dt)
    held: list[str] = []
    for path in found:
        if path in made:
            continue
        if _holds(rows, path, dt) >= MAX_HOLDS:
            print(f"shared_tmp_check: {path} let through after {MAX_HOLDS} holds", file=sys.stderr)
            continue
        held.append(path)
    if not held:
        return None
    marks = "".join(f"{MARKER}[{p}]" for p in held)
    names = ", ".join(held)
    reason = (
        f"{marks} Held: this command writes {names}, a fixed name directly in /tmp. Other sessions share "
        "/tmp, so the name may already be another session's file: the write then fails, the command before "
        "it never runs, and reading the name back shows that session's output. Write it under $STAGING_DIR "
        "instead (Step 0 printed it; paste its value), or let the script write its own record "
        "(compose_report.py leaves compose_result.json beside the report), and run the command again."
    )
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }
