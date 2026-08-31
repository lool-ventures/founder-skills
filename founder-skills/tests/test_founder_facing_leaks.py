"""Regression ratchet for founder-facing "internal plumbing" leaks.

"LEAK" HERE IS A WORDING DEFECT, NOT A CONFIDENTIALITY BREACH -- founder-visible
text showing internal vocabulary (a script name, a payload key, a pipeline step)
where plain language belonged. Nothing confidential moves. The serious sense of the
word lives in `scripts/privacy_guard.py` and the PII gate; conflating the two
devalues it where it counts. The name stays only because it is referenced across
CI and ~68 files. See `cowork-tests/leak_scan.py`'s header for the full note.

The 6 SKILL.md files carry a class-based communication rule ("never surface
file/script names, `*.py`, `--flags`, `$vars`, exit codes, `W_`/`E_` codes, JSON,
or step/route labels — narrate in the founder's own words"). This test measures
whether the recorded cassettes actually keep those tokens out of the founder-
visible assistant narration, using the shared detector (`cowork-tests/leak_scan.py`).

It is a RATCHET, not a pass/fail on zero: the committed cassettes were recorded
against the pre-rule skills and carry a base rate of leaks, and a re-record is
currently held (baseline skew). So the gate is "no NEW leaks beyond the recorded
baseline". When cassettes are re-recorded against the fixed skills the count drops
— lower `BASELINE` to the new total at that time (ratchet down, never up).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CASSETTES = _REPO_ROOT / "cowork-tests" / "cassettes"
sys.path.insert(0, str(_REPO_ROOT / "cowork-tests"))

# Base rate measured 2026-07-16 against the pre-rule cassettes. Ratchet DOWN after
# any re-record against the class-based communication rule; never raise it.
# 144 was measured over nine syntactic classes. A tenth — `plumbing_verb`, the
# semantic class — was added after it recurred in two skills and survived three
# prose fixes; it contributes 13, and the ten-class total is 61, still far under.
# Ratchet DOWN as narration improves; never up.
# Ratcheted 144 -> 64 on 2026-08-04, and NOT because the cassettes improved: `leak_scan.py` gained
# two precision filters. It now excludes sub-agent narration (an event carrying
# `parent_tool_use_id` — no founder ever sees it) and can scope to one turn. Counting sub-agent text
# was measuring a population the founder is not exposed to.
#
# Ratcheting down locks the precision win in, per this file's own rule. If a future re-record raises
# the number, that is a real regression in the recorded narration, not a reason to raise this back.
#
# ---------------------------------------------------------------------------------------------
# RAISED 55 -> 59 on 2026-08-06. This BREAKS the rule stated directly above, deliberately and once.
# It must be reversed in the next version. Read this before touching the number again.
#
# WHAT HAPPENED. Re-recording `financial-model-review-smoke` (to arm a gate assertion; the delta was
# `gates 0 -> 1`) took that cassette from 1 leak to 5, and the corpus from 55 to 59. The five:
#   [code_span]     `sample_model.xlsx`          (the founder's OWN upload)
#   [plumbing_verb] "stage the extraction"
#   [plumbing_verb] "dispatching the inputs review — the sub-agent"
#   [code_span]     `inputs.json`                (a genuine internal-file leak)
#   [json_ref]      inputs.json
#
# THE ARGUMENT FOR RAISING. The narration did not get worse; the FIXTURE got fresher. This exact
# class was measured on 3 of 3 live runs across three different skills on the same day, including
# skills whose cassettes were never re-recorded. The old cassette's count of 1 was a sampling
# artifact of one lucky recording, not evidence of clean narration. Holding the line at 55 would
# have meant reverting a good recording and keeping a stale fixture — which is the same failure
# shape as the vacuous assertion removed earlier that day: a guard that stays green by not looking.
#
# THE ARGUMENT AGAINST, which is not weak. "The number rose but the product didn't get worse" is
# precisely the rationalization this rule exists to refuse. Every raise will have a story. Accepting
# one makes the next easier, and the ratchet's whole value is that it never negotiates. A reader who
# takes this as precedent has learned the wrong lesson: the exception is recorded here at length
# because it should be ARGUED again from scratch, never cited.
#
# WHY IT WAS RESOLVED THIS WAY. The leak is real and known — tracked as an open issue deferred to the
# version after 0.7.0, with a measured 3/3 reproduction and an identified (untested) mechanism: the
# skills' own architecture prose supplies the plumbing vocabulary their narration rule forbids. The
# right fix is to stop the narration, not to choose between a stale fixture and a broken guard.
#
# THE OBLIGATION — PARTLY DISCHARGED 2026-08-20, and the measurement corrected two predictions.
# The narration fix landed (deck-review SKILL.md) and four lanes were re-recorded at harness 1.25.0:
# 59 -> 57. That is a ratchet DOWN, so the rule is honoured, but it is NOT below 55 and the
# obligation above therefore still stands.
#
# WHAT THE MEASUREMENT REFUTED, because both errors are instructive and were stated confidently:
#   1. "Re-recording deck-review cannot lower the count, since its lanes are already at 0." True but
#      irrelevant — deck-review-smoke went 0 -> 1, GAINING a `plumbing_verb` hit ("dispatching the
#      ledger extraction") in the skill whose narration was supposedly fixed. A prose fix does not
#      generalise across every phrase in the file.
#   2. "No lane can fall, because the fix was deck-review-only." False: financial-model-review-smoke
#      went 5 -> 2 with no narration edit at all. Some of what this scans is run-to-run variance in
#      how the agent narrates, not a fixed property of the skill text.
# Net -2 is therefore the sum of a real regression and an unearned improvement, not a clean win.
# Do not read a falling total as proof the narration rule is working.
#
# 12 of the 22 cassettes are still at their pre-fix recordings, and cap-table alone holds 30 of the
# remaining leaks against a one-line skill change — so the bulk of this number has never been
# re-measured against fixed narration.
BASELINE = 20


pytestmark = pytest.mark.skipif(
    not _CASSETTES.exists() or not any(_CASSETTES.glob("*.cassette.json")),
    reason="no committed cassettes to scan",
)


def _total_leaks() -> tuple[int, dict[str, int]]:
    import leak_scan  # type: ignore[import-not-found]  # from cowork-tests/ (added to sys.path above)

    per_file: dict[str, int] = {}
    for cass in sorted(_CASSETTES.glob("*.cassette.json")):
        per_file[cass.name] = len(leak_scan.scan_cassette(cass))
    return sum(per_file.values()), per_file


def test_no_new_founder_facing_leaks() -> None:
    total, per_file = _total_leaks()
    assert total <= BASELINE, (
        f"Founder-facing plumbing leaks rose to {total} (baseline {BASELINE}). "
        f"A skill change surfaced new internal tokens to the founder. Run "
        f"`python3 cowork-tests/leak_scan.py cowork-tests/cassettes/ --show` to see them, "
        f"and fix the SKILL.md narration (class-based rule at each file's ~line 100-166). "
        f"Per-file: { {k: v for k, v in sorted(per_file.items(), key=lambda kv: -kv[1]) if v} }"
    )


def test_detector_finds_the_known_leak_classes() -> None:
    """Guard the detector itself: a crafted plumbing string must trip it."""
    import leak_scan

    sample = "Exit 1 (not found). Running `extract_cap_table.py --mode=grid`; W_CAP_BASE_ASSUMED."
    classes = {c for c, _ in leak_scan.scan_text(sample)}
    for expected in ("exit_code", "code_span", "route_label", "warn_err_code"):
        assert expected in classes, f"detector missed {expected} in: {sample!r}"


# ---------------------------------------------------------------------------
# The detector's own precision. It is now the instrument for a before/after
# narration measurement, so its filters need their own tests: an instrument that
# silently counts the wrong population produces a threshold nobody can trust.
# ---------------------------------------------------------------------------


def _events(*evs: dict) -> dict:
    import json as _json

    return {"events": [_json.dumps(e) for e in evs]}


def _assistant(text: str, *, parent: str | None = None, kind: str = "assistant") -> dict:
    e: dict = {"type": kind, "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}}
    if parent:
        e["parent_tool_use_id"] = parent
    return e


def test_subagent_text_is_not_founder_visible() -> None:
    """A sub-agent's own narration never reaches the founder, so it must not be counted.

    Measured: counting it inflated one run from 9 leak-bearing top-level blocks to 78 raw hits.
    """
    import leak_scan

    top = leak_scan.founder_text_blocks(_events(_assistant("Gating the hand-off.")))
    sub = leak_scan.founder_text_blocks(_events(_assistant("Gating the hand-off.", parent="toolu_1")))
    assert len(top) == 1
    assert sub == [], "sub-agent text must be excluded from the founder-visible population"


def test_turn_scoping_separates_a_reflection_turn() -> None:
    """A `critique` run's reflection turn is ASKED to discuss internals, so leaks there are correct
    behaviour. Comparing raw totals across a critique run and a scenario run compares different
    things; `turn=1` scopes to the graded task turn."""
    import leak_scan

    init = {"type": "system", "subtype": "init"}
    cassette = _events(
        init,
        _assistant("Now dispatching the sub-agents."),
        init,
        _assistant("The COMPETITOR_RECALL dispatch confused me."),
    )
    turn1 = leak_scan.founder_text_blocks(cassette, turn=1)
    turn2 = leak_scan.founder_text_blocks(cassette, turn=2)
    both = leak_scan.founder_text_blocks(cassette)
    assert len(turn1) == 1 and "dispatching" in turn1[0]
    assert len(turn2) == 1 and "COMPETITOR_RECALL" in turn2[0]
    assert len(both) == 2, "turn=None keeps every turn, which is right for a single-turn cassette"


def test_block_stats_reports_a_ratio_not_just_hits() -> None:
    """The block RATIO is what compares across runs — one verbose block can carry many hits, which
    is exactly how a 78-hit total came from 10 blocks."""
    import json as _json
    import tempfile

    import leak_scan

    cassette = _events(
        _assistant("Gating the hand-off and piping through the producer and dispatching Step 3.5."),
        _assistant("Your competitor set looks solid."),
    )
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        _json.dump(cassette, f)
        path = Path(f.name)
    leak_blocks, total_blocks = leak_scan.block_stats(path)
    hits = len(leak_scan.scan_cassette(path))
    path.unlink()
    assert (leak_blocks, total_blocks) == (1, 2)
    assert hits > leak_blocks, "one block carried several hits — which is why the ratio is the metric"


def test_the_published_command_keep_set_is_narrow() -> None:
    """A code span holding a command the plugin PUBLISHES is not a leak — and nothing else is.

    `/founder-skills:feedback` is a slash command a founder is meant to type, so naming it is
    the sanctioned feedback channel rather than leaked plumbing. Counting it inflated the
    fleet total by one, in the one direction that matters for a ratchet.

    This test exists because a keep-set is exactly the shape that quietly becomes a hole. It
    pins all four properties: the exemption fires for a published command, does NOT fire for an
    unpublished one, leaves every other leak class untouched, and is load-bearing (emptying it
    restores the finding). The members are derived from `founder-skills/commands/`, so the set
    cannot drift from what the plugin actually ships.
    """
    import leak_scan

    published = "/founder-skills:feedback"
    assert published in leak_scan.PUBLISHED_COMMANDS, (
        f"{published} is no longer derived from commands/; the keep-set reads that directory, so "
        "either the command was renamed or the derivation broke"
    )
    assert not leak_scan.scan_text(f"you can run `{published}` any time"), "a published command was flagged"

    # NOT a blank cheque for anything command-shaped.
    assert leak_scan.scan_text("run `/founder-skills:not-a-real-command`"), (
        "an UNPUBLISHED command-shaped token was exempted — the keep-set has become a pattern"
    )

    # Every other class is untouched, including a code span that is genuine plumbing.
    for plumbing in ("I ran `compose_report.py`", "hit `W_THIN_QUOTES`", "see `--gate-state`"):
        assert leak_scan.scan_text(plumbing), f"a genuine leak stopped firing: {plumbing!r}"

    # Load-bearing: without the set, the finding comes back.
    original = leak_scan.PUBLISHED_COMMANDS
    try:
        leak_scan.PUBLISHED_COMMANDS = frozenset()
        assert leak_scan.scan_text(f"run `{published}`"), "the keep-set is not what suppresses this"
    finally:
        leak_scan.PUBLISHED_COMMANDS = original


# The matcher, hoisted so the specimens below exercise the SAME object the live scan does. Inside the
# function it could be blinded without any control noticing -- which is the whole defect class.
_JSON_PATH_RE = re.compile(r"\b[a-z_]{3,}(?:\[[^\]]*\])?(?:\.[a-z_]{3,}(?:\[[^\]]*\])?)+\b")

# A dotted token ending in a real file extension is a FILENAME, not a JSON path. Founder-facing prose
# legitimately names the founder's own upload.
_NOT_A_PATH_SUFFIXES = (".py", ".json", ".md", ".csv", ".xlsx")


def _json_path_tokens(text: str) -> list[str]:
    """Internal JSON paths named in `text`, ignoring anything file-shaped."""
    return [tok for tok in _JSON_PATH_RE.findall(text) if not tok.endswith(_NOT_A_PATH_SUFFIXES)]


# HISTORICAL -- every one of these shipped to a founder in a validation message.
_PATH_SPECIMENS_BAD = (
    "expenses.headcount[0].salary_monthly",
    "cash.monthly_net_burn",
    "metadata.warning_overrides[0].reviewed_by",
    "x_axis.rationale",
)

# LEGITIMATE -- live prose that must survive. `sample_model.xlsx` is the FOUNDER'S OWN upload, which
# they must be able to find; `growth_rate_monthly` is a bare field name with no path, deliberately
# NOT this detector's business (the founder-text policy handles undotted tokens, and duplicating that
# here would produce two warnings for one defect with different remedies).
_PATH_SPECIMENS_OK = (
    "Could not read sample_model.xlsx -- check the file opens in Excel.",
    "growth_rate_monthly is above the stage benchmark.",
)


def test_validation_messages_carry_no_json_paths() -> None:
    """Founder-facing validation messages are a surface NOTHING else scans.

    `validate_inputs.py` and `review_inputs.py` build warning dicts whose `message` is rendered
    straight into the founder's review page. Neither imports the founder-text policy, and the policy
    could not help anyway: a snake_case token after a dot is invisible to it by design, because
    cap-table's rule ids are dotted and counsel cites them verbatim.

    So sixteen messages shipped JSON paths -- "expenses.headcount[0].salary_monthly",
    "cash.monthly_net_burn" -- to founders for months, with every fleet guard green. This is the
    detector for that surface, and it is deliberately NOT in the shared module: the shape is only
    unambiguous where there are no rule ids to protect.

    The machine-readable `field` key is untouched and must stay a path -- the UI targets it. Only the
    half a human reads is checked.
    """
    import ast as _ast

    # POSITIVE CASE FIRST. Everything below scans live repo data and asserts the collection empty --
    # which proves nothing once the data is clean, and clean is the goal. This detector had a coverage
    # FLOOR (a rotted SCAN reds) and no specimens (a rotted MATCHER stayed green). Both directions now.
    for bad in _PATH_SPECIMENS_BAD:
        assert _json_path_tokens(bad), f"the matcher no longer catches a path that actually shipped: {bad}"
    for ok in _PATH_SPECIMENS_OK:
        assert not _json_path_tokens(ok), f"the matcher flags legitimate founder-facing prose: {ok}"

    SKILLS = Path(__file__).resolve().parents[1] / "skills"
    offenders: list[str] = []
    scripts_scanned = 0
    messages_examined = 0
    for script in sorted(SKILLS.glob("*/scripts/*.py")):
        scripts_scanned += 1
        try:
            tree = _ast.parse(script.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover - defensive
            continue
        for node in _ast.walk(tree):
            # A dict literal with a "message" key: the founder-facing half of a warning.
            if not isinstance(node, _ast.Dict):
                continue
            for k, v in zip(node.keys, node.values, strict=False):
                if not (isinstance(k, _ast.Constant) and k.value == "message"):
                    continue
                # Collect the literal text of an f-string or plain string, ignoring interpolations.
                parts: list[str] = []
                stack = [v]
                while stack:
                    cur = stack.pop()
                    if isinstance(cur, _ast.Constant) and isinstance(cur.value, str):
                        parts.append(cur.value)
                    elif isinstance(cur, _ast.JoinedStr):
                        stack.extend(cur.values)
                    elif isinstance(cur, _ast.BinOp):
                        stack.extend([cur.left, cur.right])
                text = " ".join(parts)
                messages_examined += 1
                for tok in _json_path_tokens(text):
                    offenders.append(f"{script.parent.parent.name}/{script.name}:{node.lineno} {tok}")
    # COVERAGE FLOOR, before the verdict. This scan walks skill scripts for `"message"` dict keys, and
    # every step of that is fragile in a way that fails SILENTLY: a moved directory, a renamed key, a
    # message built by a helper instead of a literal. Each would leave `offenders` empty and the test
    # green, which is indistinguishable from "the messages are clean". Measured 112 literals across
    # 107 scripts today. Raise when the fleet grows; never lower to accommodate a scan that stopped
    # finding things.
    assert scripts_scanned >= 90, (
        f"only {scripts_scanned} skill scripts were scanned (floor 90) — the glob or the layout moved"
    )
    assert messages_examined >= 90, (
        f"only {messages_examined} founder-facing message literals were examined (floor 90). The scan "
        "went quiet, and a quiet scan reads exactly like a clean one."
    )
    assert offenders == [], (
        "founder-facing validation messages name internal JSON paths: "
        + "; ".join(sorted(set(offenders))[:8])
        + ". Keep the path in the machine-readable `field` key; write the message for a human."
    )
