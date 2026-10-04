#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""A generated dispatch prompt is sent as the generator printed it: the red team's, and the checklist's.

THE DEFECT. In round 2 of both live runs that reached it, the main thread ran market-sizing's
`dispatch_prompt.py`, then sent the red team a different prompt: lines naming the revision and what
to look for ("Note: this is a round-2 review after a revision. In round 1, the ARPU input was changed
from $X/month…"). The reviewer repeated it to the founder ("the revised $Y…"). Round 1 matched
both times. SKILL.md says to paste the printed text unchanged; that held 0/2 in round 2. The review
exists to look at the analysis without the constructor's framing, and this is the framing.

THE COMPARAND. The generator's output as the transcript recorded it (a tool result), against the
prompt the Agent call carries. Compared with whitespace squashed, as the e2e lane does. A tool result
counts only when the call that produced it is paired by tool id and is one of:
  * a shell call running a prompt generator (`dispatch_prompt.py`, `cp_dispatch_prompt.py`,
    `fmr_dispatch_prompt.py`) whose output reaches the result, in a block with no command that prints
    text of its own (`cat`, `echo`, `printf`, `tee`, `sed`, `head`, `python3 -c`, a heredoc, ...). The
    search takes the LAST context line in a result, so a trailing `cat forged.txt` would otherwise win.
    Allowed beside it: an `echo`/`printf` whose variables are `$?` or set in the same block and which
    names no context or closing line ("EXIT=$?"), and a `head`/`tail` reading another command's pipe
    (`ocr_uploads.py ... | tail -5`). The kept runs use all three;
  * a Read, or a `cat`/`head`/`tail`, of the file a generator's stdout was redirected into
    (`> "$HANDOFF_DIR/prompt.txt"`, the block's own `NAME="..."` assignments expanded), or of the file
    the runtime saved an oversized generator result to ("Full output saved to: ..."), while no later
    call could have changed it (a Write or Edit of it, or a shell command naming it that is not
    read-only).
A Read of any other file, a sub-agent's reply, or a block that also prints text is never the
comparand. Residual: the generator's arguments are typed by the model, and a script the model wrote
itself and runs as `python3 <file>` is not recognised as printing text.

THE CONTEXT LINE. A dispatch is compared only when its first non-blank line IS a registered context
line, and the comparand's context must be a line of its own. A hand-written repair
("CONTEXT: CHECKLIST (repair)") is not the printed prompt and is not compared; `dispatch_type_check.py`,
which runs first, still holds it to its own agent.

THE BUDGET. A round is held at most twice, then let through with one stderr line: a hook that holds
forever can wedge a run on its own bug. Counted per OUTPUT_PATH, i.e. per round -- the only real user
prompts in a run are its first and its last, so a count per prompt would let round 1's holds spend
round 2's. No disclosure code is written from here: compose reading a marker the hook wrote would
make the report depend on the hook, and a missing marker would read as clean. The agent check shares
the marker, so its holds and these count against one budget per OUTPUT_PATH.

NO PRINTED PROMPT. Held, with "run the prompt generator": the only way to satisfy it puts the
comparand in the transcript.

SENDING THE PRINTED PROMPT INSTEAD (DORMANT). Where a printed prompt exists and the dispatch differs,
the hook can allow the dispatch with `updatedInput` -- the dispatch's own input with only `prompt`
replaced by the printed one -- and an `additionalContext` notice, instead of holding it. That path has
no hold budget (an allow cannot wedge a run). It runs only when all of these hold, and otherwise the
dispatch is held as above:
  * the transcript's CLI `version` is at least REWRITE_FLOOR. A runtime that ignored `updatedInput`
    on an allow would turn a visible hold into a silent pass, so the floor is the lowest version a
    live probe showed honouring it. Until that probe, REWRITE_FLOOR is a sentinel no CLI reaches;
  * the input is an object carrying `subagent_type` and `description` (a partial input is not sent);
  * no earlier rewrite in the session was found not to have taken: for each OUTPUT_PATH the runtime
    recorded this hook's notice against, the dispatch's result row (`toolUseResult.prompt`) must equal
    the printed prompt. One mismatch and every later dispatch is held, with a stderr line. This runs
    only after a rewritten dispatch's result exists, so the floor alone covers the first rewrite and
    any sibling dispatched beside it.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shlex
import sys
from typing import Any

MARKER = "[dispatch-check]"
REWRITE_MARKER = "[dispatch-rewrite]"
# The lowest CLI version measured honouring `updatedInput` on a PreToolUse allow. A sentinel until a
# live probe sets it: below it the dispatch is held, never rewritten.
REWRITE_FLOOR: tuple[int, ...] = (9999, 0, 0)
# The dispatches whose prompt a generator prints (market-sizing's dispatch_prompt.py, competitive-
# positioning's cp_dispatch_prompt.py). Every such prompt ends with END.
# CHECKLIST: in round 2 the grader was told "round 2 after a revision … down from N% in round 1"
# and wrote it to the founder; round 1's prompt had a verdict inserted.
# (context line, agent name after the plugin prefix) -> the reason a held dispatch is given. A dispatch
# is checked only when BOTH match: deck-review's and financial-model-review's CHECKLIST templates open
# with the same context line and have no generator; matched on the prefix alone, they were held for a
# prompt that cannot exist, or handed market-sizing's. One context line can belong to two skills' pairs.
_REVIEW_REASON = (
    "the review's instructions go out exactly as the prompt generator printed them, with nothing "
    "added, removed or reworded -- the review looks at the analysis without its constructor's framing"
)
# competitive-positioning's scoring and checklist prompts (cp_dispatch_prompt.py). A hand-applied review
# once wrote new scoring rules into these; anything a scorer should know belongs in the files it reads.
_SCORING_REASON = (
    "the scoring instructions go out exactly as the prompt generator printed them, with nothing added, "
    "removed or reworded -- anything the scorer should know belongs in the files it reads, not the prompt"
)
PAIRS: dict[tuple[str, str], str] = {
    ("CONTEXT: RED_TEAM", "market-sizing-redteam"): _REVIEW_REASON,
    ("CONTEXT: CHECKLIST", "market-sizing"): _REVIEW_REASON,
    ("CONTEXT: MOAT_SCORING", "competitive-positioning"): _SCORING_REASON,
    ("CONTEXT: POSITIONING_SCORING", "competitive-positioning"): _SCORING_REASON,
    ("CONTEXT: CHECKLIST", "competitive-positioning"): _SCORING_REASON,
    ("CONTEXT: STARTUP_RESEARCH", "competitive-positioning"): _SCORING_REASON,
    ("CONTEXT: RED_TEAM", "competitive-positioning-redteam"): _REVIEW_REASON,
}
CONTEXTS = tuple(dict.fromkeys(context for context, _ in PAIRS))
END = "Do NOT write any file other than OUTPUT_PATH."
DISPATCH_TOOLS = ("Agent", "Task")
MAX_HOLDS = 2
# The rest of the line, trimmed: local-lane paths contain spaces ("…/Library/Application Support/…"),
# and a `\S+` capture stopped at the first one, so every round and context shared one key.
# Leading whitespace allowed: a model that re-indents the prompt is still sending the same prompt.
_OUTPUT_RE = re.compile(r"^[ \t]*OUTPUT_PATH:[ \t]*(.+?)[ \t]*$", re.MULTILINE)


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _transcript_tools() -> Any:
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "stop_handover_check.py")
    spec = importlib.util.spec_from_file_location("stop_handover_check", path)
    if spec is None or spec.loader is None:
        raise ImportError(path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _result_text(block: dict[str, Any]) -> str:
    content = block.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(x.get("text", "") for x in content if isinstance(x, dict))
    return ""


_READ_LINE_RE = re.compile(r"^\s*\d+\t", re.MULTILINE)


def _unnumbered(text: str) -> str:
    """The Read tool numbers every line ("1\tCONTEXT: RED_TEAM"); a prompt redirected to a file and
    read back arrives that way. Strip the numbers only when every non-blank line carries one."""
    lines = [line for line in text.splitlines() if line.strip()]
    if lines and all(_READ_LINE_RE.match(line) for line in lines):
        return _READ_LINE_RE.sub("", text)
    return text


def _output_path(text: str) -> str | None:
    m = _OUTPUT_RE.search(text)
    return m.group(1) if m else None


# --- which tool results may be the comparand ---------------------------------------------------------

GENERATORS = frozenset({"dispatch_prompt.py", "cp_dispatch_prompt.py", "fmr_dispatch_prompt.py"})
# Commands that print text of their own choosing into the shell result. Matched on the command's name.
EMITTERS = frozenset(
    {
        "cat", "echo", "printf", "tee", "sed", "head", "tail", "awk", "gawk", "grep", "egrep", "fgrep",
        "rg", "jq", "less", "more", "nl", "tac", "rev", "od", "xxd", "hexdump", "strings", "cut", "sort",
        "uniq", "paste", "column", "fold", "fmt", "pr", "base64", "envsubst", "perl", "ruby", "node",
        "eval", "source", ".", "bash", "sh", "zsh", "dash", "ksh", "yes", "diff", "find", "xargs",
    }
)  # fmt: skip
# Commands that may name a redirected prompt file in the same block without changing it.
_READ_ONLY = frozenset({"wc", "cat", "head", "tail", "ls", "stat", "file", "test", "[", "md5", "md5sum",
                        "shasum", "sha256sum", "du", "echo", "printf"})  # fmt: skip
_PREFIXES = frozenset({"env", "command", "exec", "time", "nohup", "builtin"})
_SEPARATORS = frozenset({";", "&&", "||", "|", "|&", "&", "(", ")", ";;", "\n", "}"})
_WRITE_REDIRECTS = frozenset({">", ">>", ">|", "&>", "&>>", ">&"})
_READ_REDIRECTS = frozenset({"<", "<&", "<>"})
_ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_VAR_RE = re.compile(r"\$(?:\{([A-Za-z_][A-Za-z0-9_]*)\}|([A-Za-z_][A-Za-z0-9_]*))")
# An oversized result is saved to a file and the result carries only this header and a preview.
_PERSISTED_RE = re.compile(
    r"^<persisted-output>\s*\n.*?Full output saved to: (\S[^\n]*?)\s*$", re.MULTILINE | re.DOTALL
)
_PYTHON_FLAGS_WITH_ARG = frozenset({"-X", "-W", "-Q"})
_UV_FLAGS_WITH_ARG = frozenset({"--with", "--python", "-p", "--project", "--directory", "--from", "--env-file"})


class _Cmd:
    """One simple command: its words, where its stdout goes, and what it writes."""

    def __init__(self) -> None:
        self.argv: list[str] = []
        self.assigns: list[tuple[str, str]] = []
        self.stdout_file: str | None = None
        self.piped = False
        self.writes: list[str] = []
        self.substituted = False
        self.fed = False


def _substitutions(word: str) -> list[str] | None:
    """The bodies of every `$(...)` in a word; None when one is unbalanced."""
    out = []
    i = word.find("$(")
    while i >= 0:
        depth, j = 0, i + 1
        while j < len(word):
            if word[j] == "(":
                depth += 1
            elif word[j] == ")":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        if depth != 0:
            return None
        out.append(word[i + 2 : j])
        i = word.find("$(", j)
    return out


def _parse_block(command: str, _depth: int = 0) -> list[_Cmd] | None:
    """The simple commands of a shell block, or None when it cannot be read with confidence (a
    backtick, a heredoc or herestring, an unbalanced quote): such a block is never a comparand."""
    if "`" in command or _depth > 3:
        return None
    tokens: list[str] = []
    for line in re.sub(r"\\\n", " ", command).split("\n"):
        lex = shlex.shlex(line, posix=True, punctuation_chars=True)
        lex.whitespace_split = True
        lex.commenters = "#"
        try:
            tokens.extend(lex)
        except ValueError:
            return None
        tokens.append("\n")
    cmds: list[_Cmd] = []
    cur = _Cmd()
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok in ("<<", "<<-", "<<<"):
            return None
        if tok in _SEPARATORS:
            piped = tok in ("|", "|&")
            cur.piped = piped
            if cur.argv or cur.assigns:
                cmds.append(cur)
            cur = _Cmd()
            cur.fed = piped
            i += 1
            continue
        if tok in _WRITE_REDIRECTS or tok in _READ_REDIRECTS:
            if i + 1 >= len(tokens) or tokens[i + 1] in _SEPARATORS:
                return None
            target = tokens[i + 1]
            fd = cur.argv.pop() if cur.argv and cur.argv[-1].isdigit() and len(cur.argv) > 1 else None
            if tok in _WRITE_REDIRECTS and not (tok == ">&" and target.isdigit()):
                cur.writes.append(target)
                if fd in (None, "1") or tok in ("&>", "&>>", ">&"):
                    cur.stdout_file = target
            i += 2
            continue
        if "$(" in tok:
            bodies = _substitutions(tok)
            if bodies is None:
                return None
            for body in bodies:
                inner = _parse_block(body, _depth + 1)
                if inner is None:
                    return None
                for c in inner:
                    c.substituted = True
                cmds.extend(inner)
        if not cur.argv and _ASSIGN_RE.match(tok):
            name, _, value = tok.partition("=")
            cur.assigns.append((name, value))
        elif tok == "{" and not cur.argv:
            pass
        else:
            cur.argv.append(tok)
        i += 1
    if cur.argv or cur.assigns:
        cmds.append(cur)
    return cmds


def _words(argv: list[str]) -> list[str]:
    """argv with leading wrappers (`env`, `exec`, `export`, ...) and their assignments removed."""
    i = 0
    while i < len(argv):
        name = os.path.basename(argv[i])
        if name in _PREFIXES or name in ("export", "local", "declare", "readonly"):
            i += 1
            while i < len(argv) and (argv[i].startswith("-") or _ASSIGN_RE.match(argv[i])):
                i += 1
            continue
        break
    return argv[i:]


def _kind(argv: list[str]) -> str:
    """'generator', 'emitter', 'echo' (judged with the block's assignments), 'assign' (no command), or
    'other'."""
    words = _words(argv)
    if not words:
        return "assign"
    name = os.path.basename(words[0])
    if name in GENERATORS:
        return "generator"
    if name == "uv":
        rest = words[1:]
        if not rest or rest[0] != "run":
            return "other"
        j = 1
        while j < len(rest) and rest[j].startswith("-"):
            j += 2 if rest[j] in _UV_FLAGS_WITH_ARG else 1
        if j >= len(rest):
            return "other"
        if os.path.basename(rest[j]) in GENERATORS:
            return "generator"
        return _kind(rest[j:]) if os.path.basename(rest[j]).startswith("python") else "other"
    if re.fullmatch(r"python[0-9.]*", name):
        j = 1
        while j < len(words):
            w = words[j]
            if w in ("-c", "-m", "-"):
                return "emitter"
            if w.startswith("-"):
                j += 2 if w in _PYTHON_FLAGS_WITH_ARG else 1
                continue
            return "generator" if os.path.basename(w) in GENERATORS else "other"
        return "emitter"  # a bare interpreter reads its program from stdin
    if name in ("echo", "printf"):
        return "echo"
    if name in EMITTERS:
        return "emitter"
    return "other"


def _expand(word: str, env: dict[str, str]) -> str | None:
    """`$NAME` / `${NAME}` from the block's own literal assignments; None if any stays unknown."""
    unknown = False

    def sub(m: re.Match[str]) -> str:
        nonlocal unknown
        key = m.group(1) or m.group(2)
        if key not in env:
            unknown = True
            return ""
        return env[key]

    out = _VAR_RE.sub(sub, word)
    return None if unknown or "$" in out else out


_FILTERS = frozenset({"head", "tail", "sort", "uniq", "wc", "cat"})
_FILE_PRINTERS = frozenset({"cat", "head", "tail"})


def _operands(c: _Cmd) -> list[str]:
    """The arguments that are neither flags nor counts (`head -n 20 FILE` -> [FILE])."""
    return [w for w in _words(c.argv)[1:] if not w.startswith("-") and not w.isdigit()]


def _quiet_echo(c: _Cmd, env: dict[str, str], assigned: set[str]) -> bool:
    """An echo/printf that cannot print a prompt: every variable it names is `$?` or set in this block,
    and with the block's literal values filled in it names no context line and no closing line."""
    for word in _words(c.argv)[1:]:
        bare = word.replace("$?", "")
        names = [m.group(1) or m.group(2) for m in _VAR_RE.finditer(bare)]
        if any(n not in assigned for n in names) or "$" in _VAR_RE.sub("", bare):
            return False
        filled = _VAR_RE.sub(lambda m: env.get(m.group(1) or m.group(2), ""), bare)
        if "CONTEXT" in filled or END in filled:
            return False
    return True


def _env(cmds: list[_Cmd]) -> tuple[dict[str, str], set[str]]:
    """The block's own assignments, in order: literal values (expanded), and every name assigned."""
    env: dict[str, str] = {}
    assigned: set[str] = set()
    for c in cmds:
        if c.substituted:
            continue
        pairs = list(c.assigns)
        if c.argv and os.path.basename(c.argv[0]) in ("export", "local", "declare", "readonly"):
            for w in c.argv[1:]:
                if _ASSIGN_RE.match(w):
                    name, _, value = w.partition("=")
                    pairs.append((name, value))
        for name, value in pairs:
            assigned.add(name)
            expanded = _expand(value, env)
            if expanded is None:
                env.pop(name, None)
            else:
                env[name] = expanded
    return env, assigned


def _printing(cmds: list[_Cmd], env: dict[str, str], assigned: set[str], files: set[str]) -> tuple[bool, bool]:
    """(foreign, shown): whether any command prints text of its own, and whether one prints one of
    `files` (`cat`/`head`/`tail` of a file a generator wrote shows the generator's output)."""
    foreign = shown = False
    for c in cmds:
        kind = _kind(c.argv)
        words = _words(c.argv)
        name = os.path.basename(words[0]) if words else ""
        if kind == "echo":
            foreign = foreign or not _quiet_echo(c, env, assigned)
        elif kind == "emitter":
            operands = _operands(c)
            if name in _FILTERS and c.fed and not operands and not c.substituted:
                continue  # `ocr_uploads.py ... | tail -5` prints the piped command's output, not its own
            expanded = [_expand(w, env) for w in operands]
            paths = {os.path.normpath(w) for w in expanded if w is not None}
            if name in _FILE_PRINTERS and operands and None not in expanded and paths <= files and not c.writes:
                shown = shown or not c.substituted
                continue
            foreign = True
    return foreign, shown


def _writes_file(cmds: list[_Cmd], path: str, skip: _Cmd | None = None) -> bool:
    """Whether any command (but `skip`) could change `path`: it is named by a redirect, or by a command
    that is not read-only. Matched on the file name, so a mention through a variable still counts."""
    base = os.path.basename(path)
    for c in cmds:
        if c is skip or not any(base in w for w in c.argv + c.writes):
            continue
        words = _words(c.argv)
        if any(base in w for w in c.writes) or not words or os.path.basename(words[0]) not in _READ_ONLY:
            return True
    return False


def generator_block(command: str) -> tuple[bool, list[str]]:
    """(prints, files) for one shell block: whether a generator's output reaches the result with nothing
    else in the block printing text of its own, and the files a generator's stdout was redirected into
    (expanded with the block's own literal assignments) that nothing else in the block writes."""
    cmds = _parse_block(command)
    if cmds is None:
        return False, []
    gens = [c for c in cmds if not c.substituted and _kind(c.argv) == "generator"]
    if not gens:
        return False, []
    env, assigned = _env(cmds)
    kept = []
    for gen in gens:
        target = _expand(gen.stdout_file, env) if gen.stdout_file is not None and not gen.piped else None
        if target is not None and target.startswith("/"):
            path = os.path.normpath(target)
            if not _writes_file(cmds, path, skip=gen):
                kept.append(path)
    prints = any(c.stdout_file is None and not c.piped for c in gens) and not any(c.piped for c in gens)
    foreign, shown = _printing(cmds, env, assigned, set(kept))
    return (prints or shown) and not foreign, kept


def shows_file(command: str, files: set[str]) -> bool:
    """A shell block that prints one of `files` (`cat "$H/prompt.txt"`) and nothing of its own."""
    cmds = _parse_block(command)
    if cmds is None or not files:
        return False
    env, assigned = _env(cmds)
    foreign, shown = _printing(cmds, env, assigned, files)
    return shown and not foreign


def touches_file(command: str, path: str) -> bool:
    """Whether a later shell block could change `path` (an unreadable block that names it could)."""
    if os.path.basename(path) not in command:
        return False
    cmds = _parse_block(command)
    return cmds is None or _writes_file(cmds, path)


def _is_shell(name: Any) -> bool:
    return isinstance(name, str) and (name == "Bash" or name.endswith("__bash"))


def comparands(rows: list[dict[str, Any]]) -> list[str]:
    """The main-thread tool results that may be the comparand, in transcript order (module docstring)."""
    uses: dict[str, dict[str, Any]] = {}
    pending: dict[str, tuple[bool, list[str]]] = {}
    readable: set[str] = set()
    out: list[str] = []
    for row in rows:
        if row.get("isSidechain"):
            continue
        content = (row.get("message") or {}).get("content")
        if not isinstance(content, list):
            continue
        if row.get("type") == "assistant":
            for b in content:
                if not isinstance(b, dict) or b.get("type") != "tool_use":
                    continue
                uses[str(b.get("id"))] = b
                inp: dict[str, Any] = b["input"] if isinstance(b.get("input"), dict) else {}
                name = b.get("name")
                if _is_shell(name):
                    cmd = inp.get("command")
                    if not isinstance(cmd, str):
                        continue
                    verdict = generator_block(cmd)
                    if not verdict[0] and shows_file(cmd, readable):
                        verdict = (True, [])
                    readable = {path for path in readable if not touches_file(cmd, path)}
                    if verdict[0] or verdict[1]:
                        pending[str(b.get("id"))] = verdict
                elif name != "Read":
                    for key in ("file_path", "notebook_path", "path"):
                        target = inp.get(key)
                        if isinstance(target, str):
                            readable.discard(os.path.normpath(target))
        elif row.get("type") == "user":
            for b in content:
                if not isinstance(b, dict) or b.get("type") != "tool_result" or b.get("is_error"):
                    continue
                use = uses.get(str(b.get("tool_use_id")))
                if use is None:
                    continue
                text = _result_text(b)
                if _is_shell(use.get("name")):
                    key = str(b.get("tool_use_id"))
                    if key not in pending:
                        continue
                    prints, files = pending.pop(key)
                    readable.update(files)
                    if prints:
                        saved = _PERSISTED_RE.match(text)
                        if saved:
                            readable.add(os.path.normpath(saved.group(1)))
                        else:
                            out.append(text)
                elif use.get("name") == "Read":
                    read_input: dict[str, Any] = use["input"] if isinstance(use.get("input"), dict) else {}
                    target = read_input.get("file_path")
                    if isinstance(target, str) and os.path.normpath(target) in readable:
                        out.append(_unnumbered(text))
    return out


def _context_line_re(context: str) -> re.Pattern[str]:
    return re.compile(rf"^[ \t]*{re.escape(context)}[ \t]*$", re.MULTILINE)


def latest_printed(rows: list[dict[str, Any]], context: str, output_path: str | None = None) -> str | None:
    """The last generator output for `context` in the transcript, through its closing line.

    Only results `comparands()` accepts are searched, and the context must be a line of its own.
    Scoped to the dispatch's own OUTPUT_PATH when given. The path is what separates one skill's
    prompt from another's (their hand-off dirs differ) and one round from the next (each round gets
    its own path). A stale round sent verbatim to its own path therefore passes: it carries no added
    framing, and the missing hand-off for the newer round fails check_handoff loudly downstream.
    """
    found = None
    line_re = _context_line_re(context)
    for text in comparands(rows):
        starts = [m.start() for m in line_re.finditer(text)]
        if not starts:
            continue
        start = text.index(context, starts[-1])
        end = text.find(END, start)
        if end >= 0:
            candidate = text[start : end + len(END)]
            if output_path is None or _output_path(candidate) == output_path:
                found = candidate
    return found


def _holds(rows: list[dict[str, Any]], output_path: str) -> int:
    mark = f"{MARKER}[{output_path}]"
    return sum(1 for row in rows if row.get("type") == "user" and mark in json.dumps(row.get("message")))


def cli_version(rows: list[dict[str, Any]]) -> tuple[int, ...] | None:
    """The CLI version the runtime stamps on transcript rows (the latest one), or None."""
    for row in reversed(rows):
        version = row.get("version")
        if isinstance(version, str):
            m = re.match(r"^(\d+)\.(\d+)\.(\d+)", version.strip())
            return tuple(int(x) for x in m.groups()) if m else None
    return None


def _notice(output_path: str) -> str:
    return (
        f"{REWRITE_MARKER}[{output_path}] This dispatch was sent with the prompt the generator printed; "
        "the changes in your version were dropped. Do not send this dispatch again. To add a correction, "
        "re-run the generator with --correction and dispatch its output."
    )


def rewrite_failed(rows: list[dict[str, Any]]) -> bool:
    """Whether a dispatch this hook rewrote reached its sub-agent with a prompt other than the printed one.

    Which OUTPUT_PATHs were rewritten is read from the row the runtime writes for a hook's
    additionalContext (`{"type": "attachment", "attachment": {"type": "hook_additional_context",
    "content": [...]}}`), never from a tool result or a model turn, which the model can fill."""
    rewritten = set()
    for row in rows:
        attachment = row.get("attachment")
        if row.get("isSidechain") or row.get("type") != "attachment" or not isinstance(attachment, dict):
            continue
        if attachment.get("type") != "hook_additional_context":
            continue
        text = json.dumps(attachment.get("content"))
        for m in re.finditer(re.escape(REWRITE_MARKER) + r"\[(.+?)\] This dispatch was sent", text):
            rewritten.add(m.group(1))
    if not rewritten:
        return False
    for i, row in enumerate(rows):
        result = row.get("toolUseResult")
        if row.get("type") != "user" or row.get("isSidechain") or not isinstance(result, dict):
            continue
        sent = result.get("prompt")
        if not isinstance(sent, str) or _output_path(sent) not in rewritten:
            continue
        first = next((line.strip() for line in sent.splitlines() if line.strip()), "")
        if first not in CONTEXTS:
            return True
        printed = latest_printed(rows[:i], first, _output_path(sent))
        if printed is None or _squash(printed) != _squash(sent):
            return True
    return False


def _rewrite(tool_input: dict[str, Any], printed: str, output_path: str) -> dict[str, Any]:
    updated = dict(tool_input)
    updated["prompt"] = printed
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
            "permissionDecisionReason": f"{REWRITE_MARKER}[{output_path}] sent as the prompt generator printed it",
            "updatedInput": updated,
            "additionalContext": _notice(output_path),
        }
    }


def _may_rewrite(tool_input: Any, rows: list[dict[str, Any]]) -> bool:
    if not isinstance(tool_input, dict) or not all(
        isinstance(tool_input.get(k), str) for k in ("subagent_type", "description")
    ):
        return False
    version = cli_version(rows)
    if version is None or version < REWRITE_FLOOR:
        return False
    if rewrite_failed(rows):
        print("dispatch_prompt_check: an earlier rewritten dispatch did not carry the printed prompt", file=sys.stderr)
        return False
    return True


def decide(payload: dict[str, Any]) -> dict[str, Any] | None:
    if payload.get("hook_event_name") != "PreToolUse" or payload.get("tool_name") not in DISPATCH_TOOLS:
        return None
    tool_input = payload.get("tool_input")
    prompt = tool_input.get("prompt") if isinstance(tool_input, dict) else None
    if not isinstance(prompt, str):
        return None
    # The whole first line: "CONTEXT: CHECKLIST (repair)" is a hand-written repair prompt, not the printed
    # one, and is not compared (dispatch_type_check.py still holds it to its own agent).
    first = next((line.strip() for line in prompt.splitlines() if line.strip()), "")
    context = first if first in CONTEXTS else None
    if context is None:
        return None
    agent = tool_input.get("subagent_type") if isinstance(tool_input, dict) else None
    reason_text = PAIRS.get((context, agent.rsplit(":", 1)[-1])) if isinstance(agent, str) else None
    if reason_text is None:
        return None
    transcript = payload.get("transcript_path")
    if not isinstance(transcript, str) or not os.path.isfile(transcript):
        return None
    output_path = _output_path(prompt) or "?"
    rows = _transcript_tools().read_transcript(transcript)
    printed = latest_printed(rows, context, output_path)
    if printed is not None and _squash(printed) == _squash(prompt):
        return None
    if printed is not None and isinstance(tool_input, dict) and _may_rewrite(tool_input, rows):
        return _rewrite(tool_input, printed + "\n", output_path)
    if _holds(rows, output_path) >= MAX_HOLDS:
        print(
            f"dispatch_prompt_check: {output_path} sent unlike the printed prompt after {MAX_HOLDS} holds",
            file=sys.stderr,
        )
        return None
    if printed is None:
        reason = (
            f"{MARKER}[{output_path}] Held: this review round has no printed prompt yet. Run the prompt "
            "generator for this round and send its output as the prompt, unchanged."
        )
    else:
        reason = f"{MARKER}[{output_path}] Held: {reason_text}. Send this as the prompt, unchanged:\n\n{printed}"
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }
