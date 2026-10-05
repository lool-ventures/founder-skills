"""Every script invocation in shipped markdown passes only options that script accepts.

A SKILL.md once told the model to run ``python3 "$SCRIPTS/runway.py" --stdin --pretty``.
runway.py's argparse has no ``--stdin``, so every such call died with "unrecognized
arguments" (exit 2), and no test noticed: the contract tests read the prose, the producer
tests call the script with the flags the producer knows. This file joins the two.

Scanned text: every ``SKILL.md`` under ``skills/``, every ``.md`` under
``skills/*/references/`` and plugin-root ``references/``, and ``agents/*.md``.

An invocation is ``python``/``python3`` followed by a path ending in ``<name>.py``, matched
by basename because the path is written through a variable (``"$SCRIPTS/…"``,
``$SHARED_SCRIPTS/…``, ``${CLAUDE_PLUGIN_ROOT}/…``). Its option tokens run to the end of
that shell command: ``;``, ``|``, ``&``, ``>``, ``<``, ``)``, a newline without a ``\\``
continuation, or a closing backtick / fence.

Accepted options come from the script's AST: every string literal starting with ``-``
passed positionally to any ``.add_argument(...)`` call, subparsers and ``parents=`` parsers
included (so a flag valid for one subcommand passes for all -- a deliberate lenience; the
defect class here is a flag the script has nowhere).

Abbreviations: no parser in the plugin sets ``allow_abbrev=False``, so at runtime argparse
WOULD accept a unique prefix (``--pre`` for ``--pretty``). This test still requires the
exact name: a prefix that is unique today stops being unique the day a sibling flag is
added, and then the documented call fails with "ambiguous option".
"""

from __future__ import annotations

import ast
import re
import shlex
from dataclasses import dataclass
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SKILLS_ROOT = PLUGIN_ROOT / "skills"
ROOT_SCRIPTS = PLUGIN_ROOT / "scripts"

# Scripts that parse ``sys.argv`` by hand instead of through argparse, mapped to the flags
# each accepts (derived by reading the script). EMPTY today: every script a shipped
# markdown invokes uses argparse (measured 2026-10-05). A resolved script with no
# ``add_argument`` call that is not listed here FAILS the test -- never a silent skip.
HAND_PARSED: dict[str, frozenset[str]] = {}

# argparse adds these unless ``add_help=False``; every invoked parser keeps the default.
_IMPLICIT = frozenset({"-h", "--help"})

# Lever-engaged floor: the scan found 185 invocations on 2026-10-05. A broken regex
# finds far fewer; the margin absorbs ordinary prose edits.
MIN_INVOCATIONS = 170

_INVOCATION = re.compile(r"\bpython3?[ \t]+(?:-[A-Za-z]+[ \t]+)*\"?(?:[^\s\"'`]*/)?([A-Za-z_][A-Za-z0-9_]*)\.py\"?")
# A ``<placeholder>`` -- not a redirect (``< file``) and not a heredoc (``<<EOF``).
_PLACEHOLDER = re.compile(r"(?<!<)<(?![<\s=])[^<>\n]*>")
_TERMINATORS = frozenset(";|&><)`")


@dataclass(frozen=True)
class Invocation:
    line: int
    script: str  # basename without ``.py``
    flags: tuple[str, ...]


def _command_tail(text: str, start: int) -> str:
    """The rest of the shell command beginning at ``start``, continuations joined."""
    out: list[str] = []
    quote: str | None = None
    i = start
    while i < len(text):
        ch = text[i]
        if quote:
            if ch == quote:
                quote = None
            elif ch == "\n":  # an unclosed quote in prose never spans lines
                break
            out.append(ch)
        elif ch == "\\" and text[i + 1 : i + 2] == "\n":
            out.append(" ")
            i += 2
            continue
        elif ch == "\n" or ch in _TERMINATORS or (ch == "#" and text[i - 1] in " \t"):  # "#": a comment
            break
        else:
            if ch in "\"'":
                quote = ch
            out.append(ch)
        i += 1
    return "".join(out)


def _option_tokens(tail: str) -> tuple[str, ...]:
    try:
        tokens = shlex.split(tail)
    except ValueError:
        tokens = tail.split()
    flags: list[str] = []
    for tok in tokens:
        tok = tok.strip("[]")
        if tok == "--":
            break
        if not tok.startswith("-") or tok == "-" or re.match(r"-\.?\d", tok):
            continue
        if tok in ("...", "-..."):
            continue
        flags.append(tok.split("=", 1)[0])
    return tuple(flags)


def extract_invocations(text: str) -> list[Invocation]:
    # Placeholders are blanked to the same length so offsets (and line numbers) hold.
    masked = _PLACEHOLDER.sub(lambda m: "~" * len(m.group(0)), text)
    found = []
    for m in _INVOCATION.finditer(masked):
        line = masked.count("\n", 0, m.start()) + 1
        found.append(Invocation(line, m.group(1), _option_tokens(_command_tail(masked, m.end()))))
    return found


def accepted_options(source: str) -> tuple[frozenset[str], int]:
    """(option strings, number of ``add_argument`` calls). Raises SyntaxError if unparseable."""
    opts: set[str] = set()
    calls = 0
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "add_argument":
            calls += 1
            for arg in node.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str) and arg.value.startswith("-"):
                    opts.add(arg.value)
    return frozenset(opts), calls


def bad_flags(inv: Invocation, accepted: frozenset[str]) -> list[str]:
    return [f for f in inv.flags if f not in accepted | _IMPLICIT]


# ── corpus ──────────────────────────────────────────────────────────────────


def _markdown_files() -> list[Path]:
    files = sorted(SKILLS_ROOT.glob("*/SKILL.md"))
    files += sorted(SKILLS_ROOT.glob("*/references/**/*.md"))
    files += sorted((PLUGIN_ROOT / "references").glob("**/*.md"))
    files += sorted((PLUGIN_ROOT / "agents").glob("*.md"))
    return files


def _owning_skill(md: Path) -> str | None:
    rel = md.relative_to(PLUGIN_ROOT).parts
    if rel[0] == "skills":
        return rel[1]
    if rel[0] == "agents":
        name = md.stem.removesuffix("-redteam")
        return name if (SKILLS_ROOT / name).is_dir() else None
    return None


def _resolve(script: str, skill: str | None) -> Path | str:
    """The script file, or a reason string when it cannot be resolved uniquely."""
    name = f"{script}.py"
    if skill and (SKILLS_ROOT / skill / "scripts" / name).is_file():
        return SKILLS_ROOT / skill / "scripts" / name
    if (ROOT_SCRIPTS / name).is_file():
        return ROOT_SCRIPTS / name
    hits = sorted(SKILLS_ROOT.glob(f"*/scripts/{name}"))
    if len(hits) == 1:
        return hits[0]
    if hits:
        return f"ambiguous across skills: {[h.parts[-3] for h in hits]}"
    return "no such script in the skill's scripts/ or the plugin-root scripts/"


def _scan() -> tuple[list[tuple[Path, str | None, Invocation]], list[str], dict[Path, frozenset[str]]]:
    invocations: list[tuple[Path, str | None, Invocation]] = []
    problems: list[str] = []
    accepted: dict[Path, frozenset[str]] = {}
    for md in _markdown_files():
        skill = _owning_skill(md)
        for inv in extract_invocations(md.read_text(encoding="utf-8")):
            invocations.append((md, skill, inv))
            where = f"{md.relative_to(PLUGIN_ROOT)}:{inv.line}"
            target = _resolve(inv.script, skill)
            if isinstance(target, str):
                problems.append(f"{where}: {inv.script}.py -- {target}")
                continue
            if target not in accepted:
                if target.name in HAND_PARSED:
                    accepted[target] = HAND_PARSED[target.name]
                else:
                    try:
                        opts, calls = accepted_options(target.read_text(encoding="utf-8"))
                    except SyntaxError as exc:
                        problems.append(f"{where}: {target.relative_to(PLUGIN_ROOT)} is unparseable ({exc})")
                        continue
                    if calls == 0:
                        problems.append(
                            f"{where}: {target.relative_to(PLUGIN_ROOT)} has no add_argument call "
                            "and is not in HAND_PARSED"
                        )
                        continue
                    accepted[target] = opts
            for flag in bad_flags(inv, accepted[target]):
                problems.append(f"{where}: {target.relative_to(PLUGIN_ROOT)} does not accept {flag}")
    return invocations, problems, accepted


_SCAN = None


def _cached_scan() -> tuple[list[tuple[Path, str | None, Invocation]], list[str], dict[Path, frozenset[str]]]:
    global _SCAN
    if _SCAN is None:
        _SCAN = _scan()
    return _SCAN


# ── tests ───────────────────────────────────────────────────────────────────


def test_every_documented_invocation_passes_only_accepted_options() -> None:
    _invocations, problems, _accepted = _cached_scan()
    assert not problems, "Documented script calls that would fail:\n" + "\n".join(problems)


def test_the_scan_engaged() -> None:
    invocations, _problems, accepted = _cached_scan()
    assert len(invocations) >= MIN_INVOCATIONS, f"only {len(invocations)} invocations found -- regex broken?"
    resolved_skills = {p.parts[-3] for p in accepted if p.parent.parent.parent == SKILLS_ROOT}
    expected = {d.name for d in SKILLS_ROOT.iterdir() if (d / "scripts").is_dir()}
    assert expected <= resolved_skills, f"no script resolved for: {sorted(expected - resolved_skills)}"


_SYNTHETIC_RUNWAY = """
import argparse
p = argparse.ArgumentParser()
p.add_argument("--pretty", action="store_true")
p.add_argument("-o", "--output")
p.add_argument("--run-id")
sub = p.add_subparsers()
s = sub.add_parser("x")
s.add_argument("--scenarios")
"""


def test_seeded_negative_stdin_is_caught() -> None:
    snippet = (
        "Run it:\n"
        "```bash\n"
        'cat "$REVIEW_DIR/inputs.json" | python3 "$SCRIPTS/runway.py" --stdin \\\n'
        '  --pretty --run-id <run_id> -o "$REVIEW_DIR/runway.json" > /dev/null\n'
        "```\n"
        "Then `python3 ${CLAUDE_PLUGIN_ROOT}/x/runway.py --scenarios=a --pre` and done.\n"
    )
    invs = extract_invocations(snippet)
    assert [(i.line, i.script) for i in invs] == [(3, "runway"), (6, "runway")]
    assert invs[0].flags == ("--stdin", "--pretty", "--run-id", "-o")
    assert invs[1].flags == ("--scenarios", "--pre")
    accepted, calls = accepted_options(_SYNTHETIC_RUNWAY)
    assert calls == 4
    assert bad_flags(invs[0], accepted) == ["--stdin"]
    # an abbreviation argparse would accept at runtime is still refused
    assert bad_flags(invs[1], accepted) == ["--pre"]


def test_terminators_stop_the_command() -> None:
    snippet = (
        'python3 "$S/a.py" --one | grep --two; python3 b.py --three && x --four\n'
        "`python3 c.py --five` --six\n"
        "python3 d.py --seven   # not --eight\n"
    )
    got = {i.script: i.flags for i in extract_invocations(snippet)}
    assert got == {"a": ("--one",), "b": ("--three",), "c": ("--five",), "d": ("--seven",)}


def test_unparseable_script_raises() -> None:
    with pytest.raises(SyntaxError):
        accepted_options("def broken(:\n")
