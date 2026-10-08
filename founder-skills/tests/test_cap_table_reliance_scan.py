"""The paid cap-table lane's Reliance Boundary scan, tested for free.

It lives here, not in `test_e2e_cap_table.py`, because every test in a `test_e2e_*.py` file is taken for a paid
lane that must be a named skip in the release workflow (`test_skill_contract.py`).
"""

from __future__ import annotations

import pytest
from test_e2e_cap_table import eligibility_conclusion


# The Reliance Boundary scan must red on a conclusion and stay green on text that defers the question. A paid
# run once failed on "They will tell you whether you qualify" and "I am not concluding that you qualify" -- the
# report doing exactly what the boundary asks. A later run failed the same way on "This review doesn't conclude
# that you qualify", a contraction the deferral list did not cover.
@pytest.mark.parametrize(
    "text",
    [
        "Good news: you qualify for the exclusion.",
        "Once the five years pass, you will qualify.",
        "On these facts you are eligible for QSBS.",
        "The company qualifies for QSBS.",
        "Whether or not the board agrees, you qualify.",
        "It doesn't matter: you qualify.",
    ],
)
def test_eligibility_scan_catches_a_conclusion(text: str) -> None:
    assert eligibility_conclusion(text) is not None


@pytest.mark.parametrize(
    "text",
    [
        "They will tell you whether you qualify and under which regime.",
        "I am naming the rule. I am not concluding that you qualify.",
        "Counsel can confirm if you qualify.",
        "I cannot say whether you are eligible.",
        "This review doesn't conclude that you qualify or that you don't.",
        "This review doesn\u2019t conclude that you qualify.",
    ],
)
def test_eligibility_scan_passes_text_that_defers(text: str) -> None:
    assert eligibility_conclusion(text) is None
