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
prompt the Agent call carries. Compared with whitespace squashed, as the e2e lane does. A main-thread
tool result counts only when the call that produced it is paired by tool id and is one of:
  * a shell block running a TRUSTED generator -- `dispatch_prompt.py`, `cp_dispatch_prompt.py` or
    `fmr_dispatch_prompt.py` from its own skill's `skills/<skill>/scripts/` folder (or as
    `$SCRIPTS/<generator>`, the form SKILL.md writes), never one any call in the session (a sub-agent's
    included) wrote over -- whose output reaches the result, and in which EVERY other command is known
    to be quiet: assignments, `cd`, `mkdir`, `ls`, `wc`, `test`, `true`, `set -e`, `cp`/`mv` with no
    device argument, the plugin's `resolve_artifacts_root.py` and `ocr_uploads.py` (piped at most into
    `head`/`tail`/`wc`), and `echo` of literals and of `$?` or the block's own variables that, run
    together, name no context line, no OUTPUT_PATH and no closing line. Anything else -- an unknown
    command, a shell keyword or function, a subshell, a heredoc, an input redirect -- and the block is
    not a comparand. The search takes the LAST context line in a result, so this is what keeps a
    trailing `cat forged.txt` out;
  * a Read, or a quiet block's `cat`/`head`/`tail`, of the file a generator's stdout was redirected
    into (`> "$HANDOFF_DIR/prompt.txt"`, the block's own `NAME="..."` assignments expanded), or of the
    file the runtime saved an oversized generator result to ("Full output saved to: ..."), while no
    later call could have changed it: a Write or Edit of it (a sub-agent's too), a shell block that
    cannot be read, runs an interpreter other than the plugin's own scripts, or writes or names a path
    it cannot resolve. `/private/tmp` and `/tmp` are the same file.
A redo printed with `--correction producer-rejected --detail-file F` quotes F inside the prompt, so it
counts only when the transcript shows F written by a plugin producer run in the main thread (a
truncating `2> F`, no other command in that block naming F) that failed -- the call exited non-zero,
or the block's own `echo "EXIT=$?"` straight after the producer printed a non-zero code -- and nothing
has written F since (reading it is fine). The two blocks name the same F when they spell it the same
way or resolve it to the same path. Residual: a producer echoes parts of its input in its message, so
a hand-off crafted to fail can carry text into the redo; the cap and the quoting bound it.
A Read of any other file, a sub-agent's reply, or a block that also prints
text is never the comparand. Residual: the generator's arguments are typed by the model, and `$SCRIPTS` set in an
earlier shell is trusted as the skill's own folder.

THE CONTEXT LINE. A dispatch is compared when its first non-blank line, invisible characters removed,
opens with a registered context line at a word boundary: "CONTEXT: RED_TEAM (round 2)" is RED_TEAM's
dispatch and is held like any other edit, since a redo is printed by the generator (`--correction`).
The comparand's context must be a line of its own. A context with no generator (deck-review's
CHECKLIST) is not registered here and is never compared.

THE BUDGET. A round is held at most twice, then let through with one stderr line: a hook that holds
forever can wedge a run on its own bug. Counted per OUTPUT_PATH, i.e. per round -- the only real user
prompts in a run are its first and its last, so a count per prompt would let round 1's holds spend
round 2's. No disclosure code is written from here: compose reading a marker the hook wrote would
make the report depend on the hook, and a missing marker would read as clean. The agent check keeps its
own marker and budget.

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


# Characters that render as nothing: removed before the first line is read, so "CONTEXT: RED_TEAM" with
# a zero-width space after it is still the RED_TEAM line.
INVISIBLE = dict.fromkeys(map(ord, "\u200b\u200c\u200d\u2060\ufeff\u00ad"))


def first_line(prompt: str) -> str:
    """The prompt's first non-blank line, invisible characters removed, trimmed."""
    return next((s for s in (line.translate(INVISIBLE).strip() for line in prompt.splitlines()) if s), "")


def context_prefix(line: str) -> str | None:
    """The registered context `line` opens with, ending at a word boundary, or None."""
    for context in CONTEXTS:
        if line == context or (line.startswith(context) and not re.match(r"[A-Za-z0-9_]", line[len(context)])):
            return context
    return None


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

# Each generator, by the skill whose scripts folder it must be run from.
GENERATORS: dict[str, str] = {
    "dispatch_prompt.py": "market-sizing",
    "cp_dispatch_prompt.py": "competitive-positioning",
    "fmr_dispatch_prompt.py": "financial-model-review",
}
# Plugin scripts a generator block may also run: they print only paths and receipts of their own.
_QUIET_SCRIPTS = frozenset({"resolve_artifacts_root.py", "ocr_uploads.py"})
# Commands that print nothing a model chooses (cp/mv only when no argument is a device).
_QUIET = frozenset({"cd", "mkdir", "ls", "wc", "test", "[", "true", ":", "cp", "mv"})
# What a pipe from ocr_uploads.py may feed: counts and the tail of its receipt.
_PIPE_FILTERS = frozenset({"head", "tail", "wc"})
# Commands that may name a redirected prompt file without changing it.
_READ_ONLY = frozenset({"wc", "cat", "head", "tail", "ls", "stat", "file", "test", "[", "md5", "md5sum",
                        "shasum", "sha256sum", "du", "echo", "printf", "grep", "rg", "diff", "cd", "mkdir",
                        "true", ":"})  # fmt: skip
_INTERPRETERS_RE = re.compile(
    r"^(python[0-9.]*|uv|uvx|node|deno|bun|perl|ruby|php|osascript|bash|sh|zsh|dash|ksh|awk|gawk|lua|tclsh)$"
)
_KEYWORDS = frozenset({"if", "then", "else", "elif", "fi", "while", "until", "do", "done", "for", "case",
                       "esac", "function", "select", "time", "!", "{", "}", "[[", "]]", "coproc", "eval",
                       "source", "."})  # fmt: skip
_SEPARATORS = frozenset({";", "&&", "||", "|", "\n"})
_WRITE_REDIRECTS = frozenset({">", ">>", ">|", "&>", "&>>", ">&"})
_ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_VAR_RE = re.compile(r"\$(?:\{([A-Za-z_][A-Za-z0-9_]*)\}|([A-Za-z_][A-Za-z0-9_]*))")
_SUBST_RE = re.compile(r"__SUBST(\d+)__")
# An oversized result is saved to a file and the result carries only this header and a preview.
_PERSISTED_RE = re.compile(
    r"^<persisted-output>\s*\n.*?Full output saved to: (\S[^\n]*?)\s*$", re.MULTILINE | re.DOTALL
)
_UV_FLAGS_WITH_ARG = frozenset({"--with", "--python", "-p", "--project", "--directory", "--from", "--env-file"})


class _Cmd:
    """One simple command: its words, where its stdout goes, and what it writes."""

    def __init__(self) -> None:
        self.argv: list[str] = []
        self.assigns: list[tuple[str, str]] = []
        self.stdout_file: str | None = None
        self.piped = False
        self.writes: list[str] = []
        self.redirects: list[tuple[str, str | None, str]] = []
        self.reads_input = False
        self.substituted = False
        self.upstream: _Cmd | None = None


def _lift_substitutions(text: str) -> tuple[str, list[str]] | None:
    """Replace each `$(...)` outside single quotes with a placeholder word; None when one is unbalanced
    or arithmetic (`$((`)."""
    out: list[str] = []
    bodies: list[str] = []
    i, quote = 0, ""
    while i < len(text):
        ch = text[i]
        if quote == "'":
            quote = "" if ch == "'" else quote
            out.append(ch)
            i += 1
            continue
        if ch == "\\" and i + 1 < len(text):
            out.append(text[i : i + 2])
            i += 2
            continue
        if ch in "'\"" and (not quote or quote == ch):
            quote = "" if quote == ch else ch
            out.append(ch)
            i += 1
            continue
        if text.startswith("$(", i):
            if text.startswith("$((", i):
                return None
            depth, j = 0, i + 1
            while j < len(text):
                if text[j] == "(":
                    depth += 1
                elif text[j] == ")":
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            if depth != 0:
                return None
            out.append(f"__SUBST{len(bodies)}__")
            bodies.append(text[i + 2 : j])
            i = j + 1
            continue
        out.append(ch)
        i += 1
    return "".join(out), bodies


def _parse_block(command: str, _depth: int = 0) -> list[_Cmd] | None:
    """The simple commands of a shell block, or None when it cannot be read with confidence: a
    backtick, a heredoc or herestring, an unbalanced quote, a shell keyword or function, a subshell,
    a background job. Such a block is never a comparand."""
    if "`" in command or _depth > 3:
        return None
    lifted = _lift_substitutions(re.sub(r"\\\n", " ", command))
    if lifted is None:
        return None
    text, bodies = lifted
    inner: list[_Cmd] = []
    for body in bodies:
        parsed = _parse_block(body, _depth + 1)
        if parsed is None:
            return None
        for c in parsed:
            c.substituted = True
        inner.extend(parsed)
    tokens: list[str] = []
    for line in text.split("\n"):
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
        if tok in ("<<", "<<-", "<<<", "(", ")", "&", ";;", "|&", "()"):
            return None
        if tok in _SEPARATORS:
            if cur.argv or cur.assigns:
                cmds.append(cur)
                cur.piped = tok == "|"
                nxt = _Cmd()
                nxt.upstream = cur if tok == "|" else None
                cur = nxt
            elif tok == "|":
                return None
            i += 1
            continue
        if tok in _WRITE_REDIRECTS or tok in ("<", "<&", "<>"):
            if i + 1 >= len(tokens) or tokens[i + 1] in _SEPARATORS:
                return None
            target = tokens[i + 1]
            fd = cur.argv.pop() if cur.argv and cur.argv[-1].isdigit() and len(cur.argv) > 1 else None
            if tok in _WRITE_REDIRECTS and not (tok == ">&" and target.isdigit()):
                cur.writes.append(target)
                cur.redirects.append((tok, fd, target))
                if fd in (None, "1") or tok in ("&>", "&>>", ">&"):
                    cur.stdout_file = target
            elif tok in ("<", "<>") or (tok == "<&" and not target.isdigit()):
                cur.reads_input = True
            i += 2
            continue
        if not cur.argv and _ASSIGN_RE.match(tok):
            name, _, value = tok.partition("=")
            cur.assigns.append((name, value))
        else:
            if not cur.argv and (tok in _KEYWORDS or tok.endswith("()")):
                return None
            cur.argv.append(tok)
        i += 1
    if cur.argv or cur.assigns:
        cmds.append(cur)
    return cmds + inner


def _words(argv: list[str]) -> list[str]:
    """argv with a leading `export`/`local`/`declare`/`readonly` and its assignments removed."""
    if argv and argv[0] in ("export", "local", "declare", "readonly"):
        rest = argv[1:]
        return [] if all(_ASSIGN_RE.match(w) for w in rest) else argv
    return argv


def _assignments(c: _Cmd) -> list[tuple[str, str]]:
    pairs = list(c.assigns)
    if c.argv and c.argv[0] in ("export", "local", "declare", "readonly"):
        pairs += [(w.partition("=")[0], w.partition("=")[2]) for w in c.argv[1:] if _ASSIGN_RE.match(w)]
    return pairs


def _partial(word: str, raw: dict[str, str]) -> str:
    """`$NAME` / `${NAME}` filled from the block's own assignments as written, unknown names left as is."""
    for _ in range(4):
        new = _VAR_RE.sub(lambda m: raw.get(m.group(1) or m.group(2), m.group(0)), word)
        if new == word:
            break
        word = new
    return word


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
    return None if unknown or "$" in out or _SUBST_RE.search(out) else out


def _env(cmds: list[_Cmd]) -> tuple[dict[str, str], dict[str, str], set[str]]:
    """The block's own assignments, in order: literal values (expanded), values as written, and names."""
    env: dict[str, str] = {}
    raw: dict[str, str] = {}
    assigned: set[str] = set()
    for c in cmds:
        if c.substituted:
            continue
        for name, value in _assignments(c):
            assigned.add(name)
            raw[name] = _partial(value, raw)
            expanded = _expand(value, env)
            if expanded is None:
                env.pop(name, None)
            else:
                env[name] = expanded
    return env, raw, assigned


def norm_path(path: str) -> str:
    """A path as compared: normalised, and macOS's `/private/tmp` and `/private/var` read as `/tmp`, `/var`."""
    p = os.path.normpath(path)
    for top in ("/private/tmp", "/private/var", "/private/etc"):
        if p == top or p.startswith(top + "/"):
            return p[len("/private") :]
    return p


def _script(words: list[str]) -> str | None:
    """The script a python / uv command runs, or None (inline code, a module, stdin, flags)."""
    if not words:
        return None
    name = os.path.basename(words[0])
    if name == "uv":
        rest = words[1:]
        if not rest or rest[0] != "run":
            return None
        j = 1
        while j < len(rest) and rest[j].startswith("-"):
            j += 2 if rest[j] in _UV_FLAGS_WITH_ARG else 1
        if j >= len(rest):
            return None
        if re.fullmatch(r"python[0-9.]*", os.path.basename(rest[j])):
            return _script(rest[j:])
        return rest[j]
    if re.fullmatch(r"python[0-9.]*", name):
        return words[1] if len(words) > 1 and not words[1].startswith("-") else None
    return None


def _trusted_generator(path: str, raw: dict[str, str], assigned: set[str], distrusted: set[str]) -> bool:
    """A generator run from its own skill's scripts folder: the path, filled from the block's own
    assignments, names `/skills/<skill>/scripts/<generator>`, or is `$SCRIPTS/<generator>` with SCRIPTS
    set in an earlier block (the form every SKILL.md writes)."""
    base = os.path.basename(path)
    skill = GENERATORS.get(base)
    if skill is None or base in distrusted:
        return False
    filled = _partial(path, raw)
    if f"/skills/{skill}/scripts/{base}" in filled:
        return True
    return filled in (f"$SCRIPTS/{base}", f"${{SCRIPTS}}/{base}") and "SCRIPTS" not in assigned


def _plugin_script(path: str, raw: dict[str, str]) -> bool:
    """A plugin script by its path: under a `scripts/` folder, or `$SCRIPTS/` / `$SHARED_SCRIPTS/` as the
    SKILL.mds write it."""
    filled = _partial(path, raw)
    heads = ("$SCRIPTS/", "${SCRIPTS}/", "$SHARED_SCRIPTS/", "${SHARED_SCRIPTS}/")
    return "/scripts/" in filled or filled.startswith(heads)


def _kind(c: _Cmd, raw: dict[str, str], assigned: set[str], distrusted: set[str]) -> str:
    """'generator', 'assign', 'quiet', 'echo', 'filter' (head/tail/wc fed by a pipe) or 'other'."""
    words = _words(c.argv)
    if not words:
        return "assign"
    name = os.path.basename(words[0])
    target = _script(words)
    path = target if target is not None else (words[0] if name in GENERATORS else None)
    if path is not None and os.path.basename(path) in GENERATORS:
        return "generator" if _trusted_generator(path, raw, assigned, distrusted) else "other"
    if target is not None and os.path.basename(target) in _QUIET_SCRIPTS and _plugin_script(target, raw):
        return "quiet"
    if name in ("echo",):
        return "echo"
    if name == "set":
        return "quiet" if all(w[:1] in "-+" for w in words[1:]) else "other"
    if name in ("cp", "mv"):
        # A device or a process's file descriptor (/dev/stdout, /dev/fd/1, /proc/self/fd/1) prints.
        special = re.compile(r"^/(dev|proc)(/|$)")
        return "other" if any(w == "-" or special.match(_partial(w, raw)) for w in words[1:]) else "quiet"
    if name in _QUIET:
        return "quiet"
    if name in _PIPE_FILTERS:
        return "filter"
    return "other"


def _quiet_echoes(echoes: list[_Cmd], env: dict[str, str], assigned: set[str]) -> bool:
    """Echoes that cannot print a prompt: no flags, no backslash, every variable `$?` or set in this
    block, and all of them together, literal values filled in and run together, naming no context line,
    no OUTPUT_PATH and no closing line (so a context line split across two echoes is still seen)."""
    joined = ""
    for c in echoes:
        args = _words(c.argv)[1:]
        if args and re.fullmatch(r"-[neE]+", args[0]):
            return False  # echo's own options: -n joins, -e reads escapes
        for word in args:
            bare = word.replace("$?", "")
            if "\\" in word or _SUBST_RE.search(bare):
                return False
            names = [m.group(1) or m.group(2) for m in _VAR_RE.finditer(bare)]
            if any(n not in assigned for n in names) or "$" in _VAR_RE.sub("", bare):
                return False
        joined += "".join(_VAR_RE.sub(lambda m: env.get(m.group(1) or m.group(2), ""), w) for w in args)
    flat = re.sub(r"\s+", "", joined)
    return not any(s in flat for s in ("CONTEXT", "OUTPUT_PATH", "DoNOTwrite"))


def _writes_file(
    cmds: list[_Cmd], path: str, env: dict[str, str], raw: dict[str, str], assigned: set[str], distrusted: set[str]
) -> bool:
    """Whether any of `cmds` could change `path`: it runs an interpreter other than the plugin's own
    scripts, writes a redirect that is `path` or cannot be resolved, or is not read-only and names
    `path`'s file or a path that cannot be resolved."""
    base = os.path.basename(path)
    for c in cmds:
        words = _words(c.argv)
        name = os.path.basename(words[0]) if words else ""
        kind = _kind(c, raw, assigned, distrusted)
        for target in c.writes:
            expanded = _expand(target, env)
            if expanded == "/dev/null":
                continue
            if expanded is None or base in target or norm_path(expanded) == path:
                return True
        if not words or name in _READ_ONLY:
            continue
        own_script = kind in ("generator", "quiet") and _script(words) is not None
        if _INTERPRETERS_RE.match(name) and not own_script:
            return True
        for w in words[1:]:
            expanded = _expand(w, env)
            if base in w or (expanded is not None and base in expanded):
                return True
            if not own_script and expanded is None:
                return True
    return False


def generator_block(command: str, distrusted: frozenset[str] | set[str] = frozenset()) -> tuple[bool, list[str]]:
    """(prints, files) for one shell block: whether a trusted generator's output reaches the result
    with every other command in the block known to be quiet, and the files a generator's stdout was
    redirected into (expanded with the block's own literal assignments) that nothing else in the block
    writes."""
    cmds = _parse_block(command)
    if cmds is None:
        return False, []
    env, raw, assigned = _env(cmds)
    kinds = [_kind(c, raw, assigned, set(distrusted)) for c in cmds]
    gens = [c for c, k in zip(cmds, kinds) if k == "generator" and not c.substituted]
    if not gens:
        return False, []
    kept = []
    trust = set(distrusted)
    for gen in gens:
        target = _expand(gen.stdout_file, env) if gen.stdout_file is not None and not gen.piped else None
        if target is not None and target.startswith("/"):
            path = norm_path(target)
            # Only what runs after the generator (or inside a substitution) can change its file.
            later = [c for c in cmds[cmds.index(gen) + 1 :] if c is not gen] + [c for c in cmds if c.substituted]
            if not _writes_file(later, path, env, raw, assigned, trust):
                kept.append(path)
    prints = all(not c.piped for c in gens) and any(c.stdout_file is None for c in gens)
    quiet, shown = _block_quiet(cmds, kinds, env, assigned, set(kept))
    return (prints or shown) and quiet, kept


def _block_quiet(
    cmds: list[_Cmd], kinds: list[str], env: dict[str, str], assigned: set[str], files: set[str]
) -> tuple[bool, bool]:
    """(quiet, shown): whether every command is a generator or known to be quiet, and whether a
    `cat`/`head`/`tail` in the block prints one of `files` (a file a generator wrote)."""
    shown = False
    echoes = []
    for c, kind in zip(cmds, kinds):
        if c.reads_input or (c.piped and kind not in ("quiet", "generator")):
            return False, False
        if kind in ("generator", "assign"):
            if kind == "generator" and c.piped:
                return False, False
            continue
        if kind == "quiet":
            continue
        if kind == "echo":
            echoes.append(c)
            continue
        words = _words(c.argv)
        name = os.path.basename(words[0]) if words else ""
        flags = [w for w in words[1:] if w.startswith("-") or w.isdigit()]
        operands = [w for w in words[1:] if w not in flags]
        if kind == "filter" and c.upstream is not None and not operands and not c.substituted:
            up = _script(_words(c.upstream.argv))
            if up is not None and os.path.basename(up) == "ocr_uploads.py":
                continue
        if name in ("cat", "head", "tail") and operands and not c.substituted and not c.writes and files:
            paths = [_expand(w, env) for w in operands]
            if None not in paths and {norm_path(p) for p in paths if p is not None} <= files:
                shown = True
                continue
        return False, False
    return (not echoes or _quiet_echoes(echoes, env, assigned)), shown


def shows_file(command: str, files: set[str], distrusted: frozenset[str] | set[str] = frozenset()) -> bool:
    """A shell block that prints one of `files` (`cat "$H/prompt.txt"`) and nothing of its own."""
    cmds = _parse_block(command)
    if cmds is None or not files:
        return False
    env, raw, assigned = _env(cmds)
    kinds = [_kind(c, raw, assigned, set(distrusted)) for c in cmds]
    if "generator" in kinds:
        return False
    quiet, shown = _block_quiet(cmds, kinds, env, assigned, files)
    return quiet and shown


def touches_file(command: str, path: str, distrusted: frozenset[str] | set[str] = frozenset()) -> bool:
    """Whether a later shell block could change `path`. A block that cannot be read, or runs an
    interpreter other than the plugin's own scripts, could change anything."""
    cmds = _parse_block(command)
    if cmds is None:
        return True
    env, raw, assigned = _env(cmds)
    return _writes_file(cmds, path, env, raw, assigned, set(distrusted))


def _distrusts(command: str) -> set[str]:
    """Generator file names a shell block could have rewritten: named by anything but a run of it or a
    read-only command, or named in a block that cannot be read."""
    named = {g for g in GENERATORS if g in command}
    if not named:
        return set()
    cmds = _parse_block(command)
    if cmds is None:
        return named
    out = set()
    for c in cmds:
        words = _words(c.argv)
        name = os.path.basename(words[0]) if words else ""
        script = _script(words)
        for g in named:
            in_args = [w for w in words[1:] if g in w]
            if any(g in t for t in c.writes):
                out.add(g)
            elif in_args and name not in _READ_ONLY:
                if script is not None and os.path.basename(script) == g and not any(g in w for w in words[2:]):
                    continue  # running it
                out.add(g)
    return out


def _file_keys(word: str, env: dict[str, str]) -> frozenset[str]:
    """How a file named in a block is matched across blocks: the words as written
    (`$HANDOFF_DIR/producer_rejected.txt`), and its normalised path when the block's own assignments
    resolve it. Two blocks name the same file when any key is shared."""
    keys = {"as-written:" + word}
    expanded = _expand(word, env)
    if expanded is not None and expanded.startswith("/"):
        keys.add(norm_path(expanded))
    return frozenset(keys)


def producer_outputs(command: str) -> list[tuple[frozenset[str], re.Pattern[str] | None]]:
    """Files a plugin producer's output was saved to in this block (`... checklist.py ... 2> F`, a
    truncating redirect), where no other command in the block names the file; each with the pattern of
    the block's own `echo "EXIT=$?"` run straight after the producer, if there is one. A redo's message
    must come from one of these files, written by a run that failed: the call exited non-zero, or that
    echo printed a non-zero code."""
    cmds = _parse_block(command)
    if cmds is None:
        return []
    env, raw, _assigned = _env(cmds)
    out = []
    for i, c in enumerate(cmds):
        script = _script(_words(c.argv))
        if c.substituted or script is None or not _plugin_script(script, raw):
            continue
        if os.path.basename(script) in GENERATORS or os.path.basename(script) in _QUIET_SCRIPTS:
            continue
        exit_echo = None
        nxt = cmds[i + 1] if i + 1 < len(cmds) else None
        if not c.piped and nxt is not None and not nxt.substituted and _words(nxt.argv)[:1] == ["echo"]:
            args = _words(nxt.argv)[1:]
            if len(args) == 1 and args[0].count("$?") == 1 and "$" not in args[0].replace("$?", ""):
                head, _, tail = args[0].partition("$?")
                exit_echo = re.compile(rf"^{re.escape(head)}(\d+){re.escape(tail)}$", re.MULTILINE)
        for op, _fd, target in c.redirects:
            if op not in (">", ">|", "&>"):
                continue
            base = os.path.basename(target)
            if any(c2 is not c and any(base in w for w in c2.argv + c2.writes) for c2 in cmds):
                continue
            if sum(base in t for t in c.writes) > 1:
                continue
            out.append((_file_keys(target, env), exit_echo))
    return out


def redo_details(command: str) -> list[frozenset[str]] | None:
    """The --detail-file of each `--correction producer-rejected` generator run in this block (as file
    keys), or None when the block runs no such redo."""
    cmds = _parse_block(command)
    if cmds is None:
        return None
    env, _raw, _assigned = _env(cmds)
    found: list[frozenset[str]] | None = None
    for c in cmds:
        words = _words(c.argv)
        if "producer-rejected" not in words and "--correction=producer-rejected" not in words:
            continue
        found = found if found is not None else []
        for i, w in enumerate(words):
            if w == "--detail-file" and i + 1 < len(words):
                found.append(_file_keys(words[i + 1], env))
            elif w.startswith("--detail-file="):
                found.append(_file_keys(w.partition("=")[2], env))
    return found


def _failed(result: dict[str, Any], exit_echo: re.Pattern[str] | None) -> bool:
    """The producer's run failed: its call exited non-zero, or the block's own exit-code echo says so."""
    if result.get("is_error"):
        return True
    m = exit_echo.search(_result_text(result)) if exit_echo is not None else None
    return m is not None and m.group(1) != "0"


def _is_shell(name: Any) -> bool:
    return isinstance(name, str) and (name == "Bash" or name.endswith("__bash"))


_FILE_TOOL_KEYS = ("file_path", "notebook_path", "path")


def _entry_touched(command: str, keys: frozenset[str], distrusted: set[str]) -> bool:
    """Whether a later shell block could change a saved rejection named by `keys`; reading it does not."""
    return any(touches_file(command, k.removeprefix("as-written:"), distrusted) for k in keys)


def comparands(rows: list[dict[str, Any]]) -> list[str]:
    """The main-thread tool results that may be the comparand, in transcript order (module docstring).

    Writes anywhere in the transcript, a sub-agent's included, can drop a file read back or make a
    generator untrusted; only the main thread's own results are ever the comparand."""
    uses: dict[str, dict[str, Any]] = {}
    pending: dict[str, tuple[bool, list[str]]] = {}
    producing: dict[str, list[tuple[frozenset[str], re.Pattern[str] | None]]] = {}
    rejected: list[frozenset[str]] = []
    readable: set[str] = set()
    distrusted: set[str] = set()
    out: list[str] = []
    for row in rows:
        side = bool(row.get("isSidechain"))
        content = (row.get("message") or {}).get("content")
        if not isinstance(content, list):
            continue
        if row.get("type") == "assistant":
            for b in content:
                if not isinstance(b, dict) or b.get("type") != "tool_use":
                    continue
                inp: dict[str, Any] = b["input"] if isinstance(b.get("input"), dict) else {}
                name = b.get("name")
                if _is_shell(name):
                    cmd = inp.get("command")
                    if not isinstance(cmd, str):
                        continue
                    distrusted |= _distrusts(cmd)
                    verdict = (False, []) if side else generator_block(cmd, distrusted)
                    details = redo_details(cmd)
                    if details is not None and not (details and all(any(d & r for r in rejected) for d in details)):
                        verdict = (False, [])  # a redo whose message is not a failed producer's own output
                    if not side and not verdict[0] and shows_file(cmd, readable, distrusted):
                        verdict = (True, [])
                    readable = {path for path in readable if not touches_file(cmd, path, distrusted)}
                    rejected = [r for r in rejected if not _entry_touched(cmd, r, distrusted)]
                    if not side and producer_outputs(cmd):
                        producing[str(b.get("id"))] = producer_outputs(cmd)
                    if verdict[0] or verdict[1]:
                        pending[str(b.get("id"))] = verdict
                elif name != "Read":
                    for key in _FILE_TOOL_KEYS:
                        target = inp.get(key)
                        if isinstance(target, str):
                            readable.discard(norm_path(target))
                            base = os.path.basename(target)
                            rejected = [r for r in rejected if not any(os.path.basename(k) == base for k in r)]
                            if os.path.basename(target) in GENERATORS:
                                distrusted.add(os.path.basename(target))
                if not side:
                    uses[str(b.get("id"))] = b
        elif row.get("type") == "user" and not side:
            for b in content:
                if not isinstance(b, dict) or b.get("type") != "tool_result":
                    continue
                for keys, exit_echo in producing.pop(str(b.get("tool_use_id")), []):
                    if _failed(b, exit_echo):
                        rejected.append(keys)  # the producer failed: its message is in the file
                if b.get("is_error"):
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
                            readable.add(norm_path(saved.group(1)))
                        else:
                            out.append(text)
                elif use.get("name") == "Read":
                    read_input: dict[str, Any] = use["input"] if isinstance(use.get("input"), dict) else {}
                    target = read_input.get("file_path")
                    if isinstance(target, str) and norm_path(target) in readable:
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


def strings(obj: Any) -> Any:
    """Every string inside a decoded JSON value, so a marker is found in the text the runtime wrote and
    not in an encoding that escapes non-ASCII characters, quotes and backslashes."""
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for value in obj.values():
            yield from strings(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from strings(value)


def _holds(rows: list[dict[str, Any]], output_path: str) -> int:
    mark = f"{MARKER}[{output_path}]"
    return sum(1 for row in rows if row.get("type") == "user" and any(mark in t for t in strings(row.get("message"))))


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
        "the changes in your version were dropped. Do not send this dispatch again. Nothing is added to a "
        "generated prompt by hand: re-run the generator. A producer's rejection goes back through its "
        "--correction producer-rejected, and nothing else does."
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
        text = "\n".join(strings(attachment.get("content")))
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
        first = first_line(sent)
        if first not in CONTEXTS:
            continue  # not a generated dispatch: it says nothing about whether the rewrite took
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


def agent_name(agent: str) -> str | None:
    """The agent after our plugin's prefix, or the bare name; another plugin's `x:<name>` is None."""
    agent = agent.strip()
    if agent.startswith("founder-skills:"):
        return agent[len("founder-skills:") :]
    return None if ":" in agent else agent


def decide(payload: dict[str, Any]) -> dict[str, Any] | None:
    if payload.get("hook_event_name") != "PreToolUse" or payload.get("tool_name") not in DISPATCH_TOOLS:
        return None
    tool_input = payload.get("tool_input")
    prompt = tool_input.get("prompt") if isinstance(tool_input, dict) else None
    if not isinstance(prompt, str):
        return None
    # A first line that opens with a generated context and carries more ("CONTEXT: RED_TEAM (round 2)") is
    # that context's dispatch, compared like any other: a redo is printed by the generator (--correction).
    context = context_prefix(first_line(prompt))
    if context is None:
        return None
    agent = tool_input.get("subagent_type") if isinstance(tool_input, dict) else None
    name = agent_name(agent) if isinstance(agent, str) else None
    reason_text = PAIRS.get((context, name)) if name is not None else None
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
