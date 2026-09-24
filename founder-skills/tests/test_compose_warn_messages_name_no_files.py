"""No skill's compose_report.py may build a founder-facing warning message that names one of
our own internal artifact files (`checklist.json`, `positioning_scores.json`, `moat_scores.json`,
...). A founder cannot act on a file name -- see `test_market_sizing.py`'s
`test_compose_own_warnings_never_name_an_internal_file` docstring, which states the same rule for
market-sizing alone: "FOUNDER_TEXT_TOKEN's remedy tells the model to fix a label or note IT wrote;
a file name in compose's own message text would have no such author, and the founder would read
it anyway."

This is the fleet-wide version of that check, covering all six skills. It REPLACES the static
(AST) half of market-sizing's own test -- that file keeps only its live-compose half, which drives
the real producer and asserts FOUNDER_TEXT_TOKEN never fires; this file is the static half for
every skill, market-sizing included.

Two warning-construction shapes exist across the fleet:

- Five skills (market-sizing, deck-review, competitive-positioning, financial-model-review,
  ic-sim) build warnings through a local `_warn(code, message, founder_message=None)` helper.
- cap-table has no `_warn(...)` helper. It builds warning dicts as {"code": ..., "message": ...}
  literals directly, and this file's second AST visitor covers that shape.

TWO AUDIENCES. Where `_warn` takes `founder_message`, its own docstring states the contract:
`message` is AGENT-facing, flows unchanged into report.json, and in financial-model-review "MUST
keep naming the authoritative artifact"; `founder_message` is what report.md renders instead of
`message`. So a call that passes `founder_message` has an agent-facing `message` that is exempt
from this check -- naming the file there is the point -- and its `founder_message` is checked
instead. A call without `founder_message` has its `message` rendered to the founder, and that
`message` is checked.

SCOPE. This check catches internal file names written as literals in a warning's source. It does
NOT see file names interpolated at runtime, e.g. "Required artifact missing: {name}" /
"Artifact has invalid JSON: {name}", which exist today in at least four skills
(competitive-positioning, financial-model-review, ic-sim, market-sizing). Those messages have two
audiences and need a design decision, not a rename.

The pre-fix red (measured): 5 founder-facing call sites / 7 (message, filename) pairs, all in
competitive-positioning (line 668 names two files; line 885 names three). Two further calls whose
`message` names a file are CORRECTLY EXEMPT, because each passes `founder_message`:
financial-model-review METRIC_SELF_CONTRADICTION and ic-sim DEALBREAKER_PROVENANCE_UNVERIFIABLE.
A scan that ignores the two-audience rule counts 7 sites / 9 pairs; that count is wrong, and
"fixing" the two exempt messages would break a documented contract and the test that pins it.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILLS_DIR = REPO_ROOT / "founder-skills" / "skills"

SKILLS = [
    "market-sizing",
    "cap-table",
    "deck-review",
    "competitive-positioning",
    "financial-model-review",
    "ic-sim",
]

# Matches a bare lowercase_identifier.json token, e.g. "checklist.json", "positioning_scores.json".
_INTERNAL_FILENAME_PATTERN = re.compile(r"\b[a-z][a-z0-9_]*\.json\b")


def _compose_report_path(skill: str) -> Path:
    return SKILLS_DIR / skill / "scripts" / "compose_report.py"


def _message_arg_source(call: ast.Call) -> str | None:
    """Returns the unparsed source of a `_warn(...)` call's `message` argument, or None if the
    call doesn't supply one (positional index 1, or the `message` keyword)."""
    node: ast.expr | None
    if len(call.args) >= 2:
        node = call.args[1]
    else:
        node = next((kw.value for kw in call.keywords if kw.arg == "message"), None)
    if node is None:
        return None
    try:
        return ast.unparse(node)
    except Exception:
        return None


def _founder_message_arg_source(call: ast.Call) -> str | None:
    """Returns the unparsed source of a `_warn(...)` call's `founder_message` argument, if any
    (keyword-only in every skill that has the parameter)."""
    node = next((kw.value for kw in call.keywords if kw.arg == "founder_message"), None)
    if node is None:
        return None
    try:
        return ast.unparse(node)
    except Exception:
        return None


class _WarnCallCollector(ast.NodeVisitor):
    """Collects every call to a module-local `_warn(...)` warning-construction helper."""

    def __init__(self) -> None:
        self.call_count = 0
        self.message_sources: list[tuple[int, str]] = []
        self.founder_message_sources: list[tuple[int, str]] = []
        # `message` of calls that pass founder_message: agent-facing by contract, not checked.
        self.exempt_message_sources: list[tuple[int, str]] = []

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Name) and node.func.id == "_warn":
            self.call_count += 1
            message = _message_arg_source(node)
            founder_message = _founder_message_arg_source(node)
            if founder_message is not None:
                self.founder_message_sources.append((node.lineno, founder_message))
                if message is not None:
                    self.exempt_message_sources.append((node.lineno, message))
            elif message is not None:
                self.message_sources.append((node.lineno, message))
        self.generic_visit(node)


class _WarningDictCollector(ast.NodeVisitor):
    """Collects every {"code": ..., "message": ...} dict literal warning-construction shape.

    cap-table's compose_report.py builds its warning dicts this way instead of through a
    `_warn(...)` helper function -- confirmed by inspection: `grep -n "^def _warn"
    founder-skills/skills/cap-table/scripts/compose_report.py` finds nothing, while
    `founder-skills/skills/{market-sizing,deck-review,competitive-positioning,
    financial-model-review,ic-sim}/scripts/compose_report.py` each define one.
    """

    def __init__(self) -> None:
        self.dict_count = 0
        self.message_sources: list[tuple[int, str]] = []

    def visit_Dict(self, node: ast.Dict) -> None:
        keys = [k.value if isinstance(k, ast.Constant) else None for k in node.keys]
        if "code" in keys and "message" in keys:
            self.dict_count += 1
            message_node = node.values[keys.index("message")]
            try:
                source = ast.unparse(message_node)
            except Exception:
                source = ""
            self.message_sources.append((node.lineno, source))
        self.generic_visit(node)


def _collect(skill: str) -> tuple[int, list[tuple[int, str]], list[tuple[int, str]]]:
    """Returns (helper_use_count, message_sources, founder_message_sources) for one skill.

    Tries the `_warn(...)` call shape first; falls back to the {"code", "message"} dict-literal
    shape only when zero `_warn(...)` calls are found, so a skill that happens to build one
    incidental code/message dict alongside real `_warn(...)` calls is still read from its real
    warning path.
    """
    path = _compose_report_path(skill)
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    warn = _WarnCallCollector()
    warn.visit(tree)
    if warn.call_count > 0:
        return warn.call_count, warn.message_sources, warn.founder_message_sources

    dicts = _WarningDictCollector()
    dicts.visit(tree)
    return dicts.dict_count, dicts.message_sources, []


def _offenders(sources: list[tuple[int, str]]) -> list[tuple[int, str]]:
    return [(lineno, src) for lineno, src in sources if _INTERNAL_FILENAME_PATTERN.search(src)]


@pytest.mark.parametrize("skill", SKILLS)
def test_warning_helper_found_at_least_once(skill: str) -> None:
    """Non-vacuity guard: a typo'd helper name must not make this suite pass vacuously.

    Every skill's compose_report.py builds at least one warning today (market-sizing 50+,
    cap-table 14, and so on) -- a zero count here means the detector itself broke, not that the
    skill stopped emitting warnings.
    """
    call_count, _messages, _founder_messages = _collect(skill)
    assert call_count > 0, (
        f"{skill}: found no warning-construction call in compose_report.py -- expected either a "
        "`_warn(code, message, ...)` call or a {'code': ..., 'message': ...} dict literal. "
        "This means the detector's helper-name assumption is stale for this skill, not that the "
        "skill emits no warnings."
    )


@pytest.mark.parametrize("skill", SKILLS)
def test_compose_warnings_never_name_an_internal_file(skill: str) -> None:
    """A founder-facing `message` must not name one of our own `*.json` artifact files. A call that
    passes `founder_message` is exempt: its `message` is agent-facing by contract (module docstring)."""
    _call_count, messages, _founder_messages = _collect(skill)
    offenders = _offenders(messages)
    assert not offenders, (
        f"{skill}: {len(offenders)} warning message(s) in compose_report.py name an internal "
        "artifact filename a founder cannot act on:\n"
        + "\n".join(f"  line {lineno}: {src}" for lineno, src in offenders)
    )


@pytest.mark.parametrize("skill", SKILLS)
def test_founder_message_never_names_an_internal_file(skill: str) -> None:
    """A `founder_message` is what report.md renders in place of `message`: it must never carry a
    raw filename."""
    _call_count, _messages, founder_messages = _collect(skill)
    offenders = _offenders(founder_messages)
    assert not offenders, (
        f"{skill}: {len(offenders)} founder_message override(s) in compose_report.py name an "
        "internal artifact filename a founder cannot act on:\n"
        + "\n".join(f"  line {lineno}: {src}" for lineno, src in offenders)
    )


def test_market_sizing_is_covered() -> None:
    """market-sizing's own count is 0 today and must stay 0.

    This is a targeted, always-informative pin on top of the parametrized checks above: it fails
    by itself (independent of the other five skills) if market-sizing regresses, and it documents
    that market-sizing is the skill whose own test file (`test_market_sizing.py`) used to carry
    this check in AST form before it moved here.
    """
    call_count, messages, _founder_messages = _collect("market-sizing")
    assert call_count > 0
    assert _offenders(messages) == []


def test_the_two_audience_exemption_is_real_and_narrow() -> None:
    """The exemption must not quietly swallow founder-facing text: it covers exactly the calls that
    pass founder_message, and today those include the two agent-facing messages that name a file."""
    exempt: list[str] = []
    for skill in SKILLS:
        path = _compose_report_path(skill)
        warn = _WarnCallCollector()
        warn.visit(ast.parse(path.read_text(encoding="utf-8")))
        exempt += [f"{skill}:{ln}" for ln, src in warn.exempt_message_sources if _INTERNAL_FILENAME_PATTERN.search(src)]
    skills_with_named_file = {e.split(":")[0] for e in exempt}
    assert skills_with_named_file == {"financial-model-review", "ic-sim"}, exempt
