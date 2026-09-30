"""rerecord.sh's cost pre-flight tells a budget refusal from a load failure by the harness's MESSAGE.

The pre-flight runs `record scenarios/ --dry-run --max-budget-usd <cap>` and used to branch on the exit
code: 2 meant "over budget", anything else "a scenario did not load". cowork-harness 4.0.0 exits 1 for a
budget refusal too (measured on the pre-release: the same "refused before spending" message, rc 2 at 3.10.0
and rc 1 at 4.0.0), which landed a cost refusal in the branch that prints "THIS IS NOT A COST PROBLEM".
The message is the same on both versions, so the classifier keys on it and works under either.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_HELPER = _ROOT / "cowork-tests" / "preflight_classify.sh"
_RERECORD = _ROOT / "cowork-tests" / "rerecord.sh"

_COST = (
    "--max-budget-usd $0.0100 refused before spending: this batch of 35 scenario(s) has cost up to $120.8037 "
    "in prior runs."
)
# The harness's own wording, as captured from 3.10.0 and the 4.0.0 pre-release on the same inputs.
_BROKEN = '✗ broken: scenarios/broken.yaml: Unrecognized key: "bogus_key" at (root)'
_POLICY = "✗ refused: scenarios/y.yaml: prompt policy"  # a non-"broken" ✗ line: still not a cost problem
# The advisory lines a real dry-run prints beside a refusal; they are neither a cost nor a load failure.
_ADVISORY = "⚠ would-refuse (advisory): scenarios/a.yaml: refusing to record into a repo-visible path at hostloop"


def _classify(rc: int, stderr: str, tmp_path: Path) -> str:
    err = tmp_path / "preflight.err"
    err.write_text(stderr, encoding="utf-8")
    r = subprocess.run(
        ["bash", "-c", f'. "{_HELPER}"; classify_preflight {rc} "{err}"'],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


@pytest.mark.parametrize(
    ("rc", "stderr", "want"),
    [
        (0, "", "ok"),
        (2, _ADVISORY + "\n" + _COST, "cost"),  # 3.10.0
        (1, _ADVISORY + "\n" + _COST, "cost"),  # 4.0.0 -- the case that used to print "THIS IS NOT A COST PROBLEM"
        (1, _BROKEN, "load"),
        (1, _POLICY, "load"),
        (2, _BROKEN + "\n" + _COST, "load_and_cost"),  # 3.10.0: some broken + over the cap
        (1, _BROKEN + "\n" + _COST, "load_and_cost"),  # 4.0.0: the same case
        (1, "", "load"),  # a failure with nothing recognisable is never called a cost problem
        (3, "unexpected", "load"),
    ],
    ids=["ok", "cost-3.10", "cost-4.0", "broken", "policy", "both-3.10", "both-4.0", "silent-fail", "other-rc"],
)
def test_the_classifier_keys_on_the_message_not_the_exit_code(rc: int, stderr: str, want: str, tmp_path: Path) -> None:
    assert _classify(rc, stderr, tmp_path) == want


def test_rerecord_uses_the_classifier_and_no_longer_branches_on_exit_2() -> None:
    text = _RERECORD.read_text(encoding="utf-8")
    start = text.index("=== cost pre-flight")
    block = text[start : text.index("\nfi\n", start)]
    assert "classify_preflight" in block and "preflight_classify.sh" in text
    assert "\n    2)\n" not in block, "the pre-flight still maps exit 2 to the cost branch"
    # The harness prints everything to stderr; the classifier needs it, and the operator still sees it.
    assert "2>" in block
