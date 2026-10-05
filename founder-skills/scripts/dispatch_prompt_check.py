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
    `fmr_dispatch_prompt.py` from its own skill's `skills/<skill>/scripts/` folder of an INSTALLED
    plugin (a Cowork or Desktop plugin mount or cache, the CLI's plugin cache, the cloud skills mount,
    the folder the runtime says it loaded our skill from, or the one this hook runs from) or as
    `$SCRIPTS/<generator>`, the form SKILL.md writes; never a copy elsewhere, and never once any call in
    the session (a sub-agent's included) wrote into the plugin's scripts or over a generator, with names
    read through the block's own assignments -- whose output reaches the result, and in which EVERY
    other command is known to be quiet: assignments, `cd`, `mkdir`, `ls` (before the generator only),
    `wc`, `test`, `true`, `set -e`, `cp`/`mv` with no device or /proc argument, the plugin's
    `resolve_artifacts_root.py` and `ocr_uploads.py` (piped at most into `head`/`tail`/`wc`), and `echo`
    of literals and of `$?` or the block's own variables that, run together, name no context line, no
    OUTPUT_PATH and no closing line. Anything else -- an unknown command, a shell keyword or function, a
    subshell, a heredoc, an input redirect -- and the block is not a comparand. The search takes the
    LAST context line in a result, so this is what keeps a trailing `cat forged.txt` out. Or the
    generator is the block's LAST command (after `;`, a newline or `&&`), and what runs before it may
    print -- the steps a model folds into the same block (a producer pipe, its exit-code echo, a `cat`)
    -- so long as each is a plugin script or a known command that cannot leave anything running that
    prints later (no other interpreter, no exec, trap, sed, awk or find). A block that sets PATH,
    PYTHONPATH and the like is never a comparand;
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
# positioning's cp_dispatch_prompt.py, financial-model-review's fmr_dispatch_prompt.py). Every such prompt
# ends with END.
# CHECKLIST: in round 2 the grader was told "round 2 after a revision … down from N% in round 1"
# and wrote it to the founder; round 1's prompt had a verdict inserted.
# (context line, agent name after the plugin prefix) -> the reason a held dispatch is given. A dispatch
# is checked only when BOTH match: deck-review's CHECKLIST template opens with the same context line and
# has no generator; matched on the prefix alone, it was held for a prompt that cannot exist, or handed
# market-sizing's. One context line can belong to several skills' pairs.
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
    # financial-model-review's grader (fmr_dispatch_prompt.py): kept runs sent it a prompt missing most of
    # the template's sentences.
    ("CONTEXT: CHECKLIST", "financial-model-review"): _REVIEW_REASON,
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
_QUIET = frozenset({"cd", "mkdir", "wc", "test", "[", "true", ":", "cp", "mv"})
# Quiet only BEFORE the generator: a listing after it prints names whoever made the files chose, one per
# line, which could stand in for a prompt's lines.
_QUIET_BEFORE = frozenset({"ls"})
# What may run, and print, before the generator when the generator is the block's last command: none of
# these can leave anything running that prints after it (no interpreter of unknown code, no background
# job, no exec, no trap, no sed/awk/find that can run commands).
_MAY_PRECEDE = frozenset({"cat", "echo", "printf", "grep", "egrep", "fgrep", "rg", "ls", "wc", "head", "tail",
                          "sort", "uniq", "cut", "tr", "jq", "test", "[", "true", "false", ":", "cd", "mkdir",
                          "cp", "mv", "touch", "date", "pwd", "basename", "dirname", "stat", "file", "du", "df",
                          "diff", "cmp", "md5", "md5sum", "shasum", "sha256sum", "nl", "column", "set"})  # fmt: skip
# Variables that change which program runs or what it loads: set anywhere in the block, no comparand.
_HIJACK_VARS = frozenset({"PATH", "PYTHONPATH", "PYTHONSTARTUP", "PYTHONHOME", "PYTHONINSPECT", "PYTHONUSERBASE",
                          "PYTHONSAFEPATH", "BASH_ENV", "ENV", "LD_PRELOAD", "LD_LIBRARY_PATH", "IFS", "PS4",
                          "SHELLOPTS", "BASHOPTS", "PROMPT_COMMAND"})  # fmt: skip
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
        self.sep_before: str | None = None
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
                nxt.sep_before = tok
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


# Where a plugin is installed, by lane: Cowork's local and remote plugin mounts, Desktop's plugin cache, the
# CLI's plugin cache, the cloud container's skills mount. Also trusted: the folder the runtime says it
# loaded our skill from, and the folder this hook runs from (the hook runs host-native at the host loop
# while the shell runs in the VM, so that one counts only where the two agree: the CLI, the e2e lanes).
_INSTALL_MARKERS = ("/.local-plugins/", "/.remote-plugins/", "/cowork_plugins/", "/.claude/plugins/",
                    "/mnt/skills/plugins/")  # fmt: skip
HOOK_PLUGIN_ROOT = os.path.normpath(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# The plugin folders this session's runtime loaded our skills from ("Base directory for this skill: ..."),
# as the shell names them. Set by comparands() from the transcript's own rows.
_SESSION_ROOTS: set[str] = set()
_BASE_DIR_RE = re.compile(r"^Base directory for this skill: (/\S[^\n]*?)/skills/([a-z-]+)\s*$", re.MULTILINE)
_OUR_SKILLS = ("cap-table", "competitive-positioning", "deck-review", "financial-model-review", "ic-sim",
               "market-sizing")  # fmt: skip


def session_roots(rows: list[dict[str, Any]]) -> set[str]:
    """Plugin roots from the runtime's skill-load rows (isMeta), for our skills only."""
    out = set()
    for row in rows:
        if row.get("type") != "user" or not row.get("isMeta") or row.get("isSidechain"):
            continue
        for text in strings((row.get("message") or {}).get("content")):
            for m in _BASE_DIR_RE.finditer(text):
                if m.group(2) in _OUR_SKILLS:
                    out.add(norm_path(m.group(1)))
    return out


def _installed_root(root: str) -> bool:
    """A plugin root as a generator path names it: an installed plugin, the plugin this hook runs from,
    or a variable set in an earlier shell (unknown here; unset at run time, the call fails)."""
    if root.startswith("$"):
        return True
    if not root.startswith("/"):
        return False
    r = norm_path(root)
    return r == norm_path(HOOK_PLUGIN_ROOT) or r in _SESSION_ROOTS or any(m in r + "/" for m in _INSTALL_MARKERS)


def _trusted_generator(path: str, raw: dict[str, str], assigned: set[str], distrusted: set[str]) -> bool:
    """A generator run from its own skill's scripts folder of an installed plugin: the path, filled from
    the block's own assignments, ends `/skills/<skill>/scripts/<generator>` under such a root, or is
    `$SCRIPTS/<generator>` with SCRIPTS set in an earlier block (the form every SKILL.md writes). A copy
    of the plugin anywhere else, or a relative path, is not trusted."""
    base = os.path.basename(path)
    skill = GENERATORS.get(base)
    if skill is None or base in distrusted:
        return False
    filled = _partial(path, raw)
    suffix = f"/skills/{skill}/scripts/{base}"
    if filled.endswith(suffix):
        return _installed_root(filled[: -len(suffix)])
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


def _hijacked(cmds: list[_Cmd]) -> bool:
    """A block that sets a variable deciding which program runs or what it loads (PATH, PYTHONPATH...)."""
    for c in cmds:
        for name, _value in _assignments(c):
            if name in _HIJACK_VARS or name.startswith("DYLD_"):
                return True
    return False


def generator_block(command: str, distrusted: frozenset[str] | set[str] = frozenset()) -> tuple[bool, list[str]]:
    """(prints, files) for one shell block: whether a trusted generator's output reaches the result
    with nothing after it able to print text of its own choosing, and the files a generator's stdout was
    redirected into (expanded with the block's own literal assignments) that nothing else in the block
    writes.

    Two shapes count. Every other command known to be quiet, the generator anywhere; or the generator
    the block's LAST command, after `;`, a newline or `&&`, with what runs before it free to print (its
    output comes first, and the search takes the last context line) so long as it cannot leave anything
    running that prints later. The second needs the generator last: if it failed after a printing step,
    the call's exit code says so, where a quiet command after it would hide the failure."""
    cmds = _parse_block(command)
    if cmds is None or _hijacked(cmds):
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
    printing = [c for c in gens if c.stdout_file is None and not c.piped]
    prints = bool(printing) and all(not c.piped for c in gens)
    top = [c for c in cmds if not c.substituted]
    last = printing[-1] if printing else None
    split = top.index(last) if last is not None else len(top)
    quiet, shown = _block_quiet(cmds, kinds, env, assigned, set(kept), set(map(id, top[:split])))
    if quiet:
        return (prints or shown), kept
    if last is not None and top[-1] is last and last.sep_before != "||" and prints:
        before = [(c, k) for c, k in zip(cmds, kinds) if not c.substituted and top.index(c) < split]
        subs = [(c, k) for c, k in zip(cmds, kinds) if c.substituted]
        if all(_may_precede(c, k, raw) for c, k in before):
            sub_quiet, _ = _block_quiet([c for c, _ in subs], [k for _, k in subs], env, assigned, set(), set())
            return sub_quiet, kept
    return False, kept


def _may_precede(c: _Cmd, kind: str, raw: dict[str, str]) -> bool:
    """A command that may run, and print, before the generator: a known command that cannot leave
    anything running that prints later, a plugin script, another trusted generator, an assignment."""
    if kind in ("generator", "assign", "quiet"):
        return True
    words = _words(c.argv)
    name = os.path.basename(words[0]) if words else ""
    script = _script(words)
    if script is not None:
        return _plugin_script(script, raw) and os.path.basename(script) not in GENERATORS
    return name in _MAY_PRECEDE and not _INTERPRETERS_RE.match(name)


def _block_quiet(
    cmds: list[_Cmd],
    kinds: list[str],
    env: dict[str, str],
    assigned: set[str],
    files: set[str],
    before: set[int] | None = None,
) -> tuple[bool, bool]:
    """(quiet, shown): whether every command is a generator or known to be quiet, and whether a
    `cat`/`head`/`tail` in the block prints one of `files` (a file a generator wrote). `before` holds
    the commands that run before the generator, where a listing is quiet too."""
    shown = False
    echoes = []
    before = before or set()
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
        if name in _QUIET_BEFORE and id(c) in before:
            continue
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


# What in a written path points into the plugin: the script folders as SKILL.md names them, a skills tree,
# an install root.
_PLUGIN_HINTS = ("$SCRIPTS", "${SCRIPTS}", "$SHARED_SCRIPTS", "${SHARED_SCRIPTS}", "PLUGIN_ROOT", "/skills/",
                 *_INSTALL_MARKERS)  # fmt: skip
_WRITERS = frozenset({"cp", "mv", "ln", "install", "rsync", "tee", "dd", "truncate", "patch", "tar", "unzip",
                      "touch", "chmod", "curl", "wget", "git"})  # fmt: skip


def _into_plugin(text: str) -> bool:
    if any(g in text for g in GENERATORS) or any(h in text for h in _PLUGIN_HINTS):
        return True
    return text.startswith("/") and (norm_path(text) + "/").startswith(norm_path(HOOK_PLUGIN_ROOT) + "/")


def _distrusts(command: str) -> set[str]:
    """Generators a shell block could have rewritten. A generator named by anything but a run of it or a
    read-only command; and every generator when the block writes into the plugin (a redirect, an
    in-place edit, a copy, link or extraction whose target points there), runs inline code that names
    it, or cannot be read and mentions it in a line that writes (`_raw_writes_into_plugin`). Names are
    read with the block's own assignments filled in, so a name spelt apart (`G=dispatch_prompt; ...
    "$G.py"`) is still seen."""
    cmds = _parse_block(command)
    if cmds is None:
        return set(GENERATORS) if _raw_writes_into_plugin(command) else set()
    _env_values, raw, _assigned = _env(cmds)
    out: set[str] = set()
    for c in cmds:
        words = _words(c.argv)
        name = os.path.basename(words[0]) if words else ""
        filled = [_partial(w, raw) for w in words[1:]]
        if any(_into_plugin(_partial(t, raw)) for t in c.writes):
            return set(GENERATORS)
        if name in _WRITERS:
            targets = filled[-1:] if name in ("cp", "ln", "install", "rsync") else filled
            if any(_into_plugin(t) for t in targets):
                return set(GENERATORS)
        if name == "sed" and any(w == "-i" or w.startswith("-i") for w in filled) and any(map(_into_plugin, filled)):
            return set(GENERATORS)
        inline = _INTERPRETERS_RE.match(name) and any(w in ("-c", "-e") for w in words[1:])
        if inline and any(_into_plugin(w) or "dispatch_" in w or "prompt.py" in w for w in filled):
            return set(GENERATORS)
        script = _script(words)
        for g in GENERATORS:
            if any(os.path.basename(_partial(t, raw)) == g for t in c.writes):
                out.add(g)
            elif any(os.path.basename(w) == g for w in filled) and name not in _READ_ONLY:
                running = script is not None and os.path.basename(script) == g
                if running and not any(os.path.basename(w) == g for w in filled[1:]):
                    continue
                out.add(g)
    return out


# A write in a line the parser could not read: a redirect (a `>` after a space, so `<path>` is not one),
# a copy or in-place edit, a file opened for writing by inline code.
_RAW_WRITE_RE = re.compile(
    r"(?:(?:^|\s)[0-9&]?>>?\s*[^\s&]|\b(?:cp|mv|ln|tee|install|rsync|dd|truncate|patch)\s|sed\s+-i"
    r"|open\([^)]*,\s*['\"][wax+]|write_text\(|write_bytes\()"
)


# Commands a line may run beside a generator that saves its output: they print, and write nothing.
_RAW_READERS = frozenset({"echo", "printf", "wc", "ls", "test", "[", "true", "cat", "head", "tail"})
_RAW_SEGMENT_SEPS = frozenset({";", "&&", "||", "|"})
_RAW_QUIET_REDIRECTS = (("2", ">", "/dev/null"), ("2", ">&", "1"))


def _raw_tokens(line: str) -> list[str] | None:
    lex = shlex.shlex(line, posix=True, punctuation_chars=True)
    lex.whitespace_split = True
    lex.commenters = ""
    try:
        return list(lex)
    except ValueError:
        return None


_RAW_OPENERS = frozenset({"for", "while", "until", "if", "case", "select", "{", "("})
_RAW_CLOSERS = frozenset({"done", "fi", "esac", "}", ")"})


def _raw_env(lines: list[str], names: set[str]) -> dict[str, str] | None:
    """The literal assignments of `lines` (a raw block's lines before the one judged) that bash certainly
    ran: a command of assignments only, outside any loop, test or group, to a name the whole block
    assigns once (`names`). None when the nesting cannot be followed."""
    env: dict[str, str] = {}
    depth = 0
    for line in lines:
        tokens = _raw_tokens(line) or []
        segment: list[str] = []
        for tok in [*tokens, ";"]:
            if tok not in _RAW_SEGMENT_SEPS:
                segment.append(tok)
                continue
            head = segment[0] if segment else ""
            if head in _RAW_OPENERS:
                depth += 1
            elif head in _RAW_CLOSERS:
                depth -= 1
            elif depth == 0 and segment and all(_ASSIGN_RE.match(w) for w in segment):
                for word in segment:
                    name, _, value = word.partition("=")
                    expanded = _expand(value, env)
                    if name in names and expanded is not None:
                        env[name] = expanded
            segment = []
        if depth < 0:
            return None
    return env


def _saves_generator_output_elsewhere(line: str, env: dict[str, str], assigned: set[str]) -> bool:
    """A raw line that only runs a generator and saves its output outside the plugin, all or nothing: as
    in the parsed branch, a generator named as the script being run is not a mention of it. Exactly one
    command is `python<N> <generator> ...` with no assignment before it, the generator a trusted one
    (`_trusted_generator`), every argument resolved by `env` and none in the plugin or naming a
    generator, and its only write its stdout to an absolute path that is neither; every other command is
    a reader with no write. No substitution, no in-place flag, no `tee`; any doubt and
    the line is not exempt."""
    if "`" in line or "$(" in line:
        return False
    tokens = _raw_tokens(line)
    if not tokens:
        return False
    segments: list[list[str]] = [[]]
    for tok in tokens:
        if tok in _RAW_SEGMENT_SEPS:
            segments.append([])
        else:
            segments[-1].append(tok)
    runs = 0
    for seg in segments:
        words: list[str] = []
        redirects: list[tuple[str, str, str]] = []
        i = 0
        while i < len(seg):
            tok = seg[i]
            if tok and tok[0] in "<>&" or tok.endswith((">", "<")):
                if i + 1 >= len(seg):
                    return False
                fd = words.pop() if words and words[-1].isdigit() else ""
                redirects.append((fd, tok, seg[i + 1]))
                i += 2
                continue
            words.append(tok)
            i += 1
        names = words
        if not names or _ASSIGN_RE.match(names[0]) or "-i" in words or "tee" in words:
            return False
        quiet = all(r in _RAW_QUIET_REDIRECTS for r in redirects)
        if names[0] in _RAW_READERS:
            if not quiet or (names[0] == "printf" and "-v" in names):
                return False
            if any(_into_plugin(w) or "dispatch_" in w or "prompt.py" in w for w in names):
                return False
            continue
        if not (re.fullmatch(r"python[0-9.]*", names[0]) and len(names) > 1):
            return False
        if not _trusted_generator(names[1], env, assigned, set()):
            return False
        for arg in names[2:]:
            value = _expand(arg, env)
            if value is None or _into_plugin(value) or os.path.basename(value) in GENERATORS:
                return False
        runs += 1
        out = [r for r in redirects if r not in _RAW_QUIET_REDIRECTS]
        if len(out) > 1 or (out and (out[0][0] not in ("", "1") or out[0][1] not in (">", ">|"))):
            return False
        if out:
            target = _expand(out[0][2], env)
            if target is None or not target.startswith("/") or _into_plugin(target):
                return False
            if os.path.basename(target) in GENERATORS:
                return False
    return runs == 1


def _raw_writes_into_plugin(command: str) -> bool:
    """For a block the parser cannot read (a heredoc, a loop): whether any line both writes (a redirect,
    a copy, an in-place edit, a file opened by inline code) and names the plugin or a generator. Read
    line by line, so a heredoc's body is checked too. A line that only runs a generator and saves its
    output outside the plugin is not such a line, unless the block changes folder (a relative path
    elsewhere in it could then land in the plugin) or has a heredoc (whose body is not commands)."""
    lines = command.splitlines()
    off = "<<" in command or re.search(r"(?<![\w.-])(?:cd|pushd|popd)(?![\w.-])", command) is not None
    # Every name the block assigns anywhere (a loop or heredoc body, a command's prefix, `export`): one
    # assigned twice is never resolved.
    counts: dict[str, int] = {}
    for name in re.findall(r"(?<![\w$./-])([A-Za-z_][A-Za-z0-9_]*)=", command):
        counts[name] = counts.get(name, 0) + 1
    once = {name for name, n in counts.items() if n == 1}
    for i, line in enumerate(lines):
        env = None if off else _raw_env(lines[:i], once)
        if env is not None and _saves_generator_output_elsewhere(line, env, set(counts)):
            continue
        if not _RAW_WRITE_RE.search(line.replace("2>&1", "").replace(">/dev/null", "")):
            continue
        if _into_plugin(line) or "dispatch_" in line or "prompt.py" in line:
            return True
    return False


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
    _SESSION_ROOTS.clear()
    _SESSION_ROOTS.update(session_roots(rows))
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
            f"{MARKER}[{output_path}] Held: no printed prompt for this OUTPUT_PATH yet. Run the prompt "
            "generator in a shell call of its own, or as the last command of its block, with nothing after it "
            "that prints, and send the text it prints as the prompt, unchanged. Do not redirect its output "
            "away: the printed text is what the dispatch is compared with."
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
