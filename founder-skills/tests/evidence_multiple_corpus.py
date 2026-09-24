"""Re-run the false-positive measurement the unsupported-multiple check is calibrated on.

NOT a test module (no `test_` prefix, so pytest does not collect it) — a tool, because the data it
reads is machine-local: kept `cowork-harness` run dirs, which exist on a developer's machine and not
in CI. `test_fmr_unsupported_multiple.py` pins the parts that CAN be pinned.

WHY IT EXISTS. The check's whole justification is a measured false-positive rate: over 2,854 real
CHECKLIST evidence/notes strings harvested 2026-09-19 from every kept run dir (289
financial-model-review, 1,563 deck-review, 694 competitive-positioning, 308 market-sizing), only 39
state a multiple at all and exactly ONE fires — the defect the check was written for. Silent on the
other 38. That is the reason a medium warning was judged shippable, and 38 is the denominator.
**Re-run this as real reviews accumulate.** If the count stays 0 across a larger denominator the
design holds; if it does not, the check is miscalibrated and the design record in
`docs/internal/2026-09-19-fmr-critique-corpus-findings.md` is wrong.

It imports the PRODUCTION detector rather than restating it. An earlier revision of this work
measured a prototype, wrote a spec describing something else, and shipped a regex that matched
nothing — the check fired zero times where the prototype fired once. A tool with its own copy of the
grammar would reproduce exactly that.

    python3 founder-skills/tests/evidence_multiple_corpus.py
"""

from __future__ import annotations

import collections
import glob
import importlib.util
import json
import os
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DETECTOR = REPO_ROOT / "founder-skills" / "skills" / "financial-model-review" / "scripts" / "_evidence_multiple.py"

#: Skill names, matched against the artifact directory. NOT a capture group: the dir is
#: `<skill>-<company-slug>/`, so a generic regex groups by COMPANY and prints a real name.
SKILLS = (
    "financial-model-review",
    "competitive-positioning",
    "deck-review",
    "market-sizing",
    "ic-sim",
    "cap-table",
)

#: Where kept run dirs live. Machine-local by nature.
RUN_GLOB = "~/.cowork-harness/runs/**/checklist.json"

#: The 2026-09-19 reading, for comparison on a later run. Not an assertion — the corpus grows.
BASELINE = {"strings": 2854, "with_a_multiple": 39, "fires": 1}


def load_detector() -> Any:
    spec = importlib.util.spec_from_file_location("fmr_evidence_multiple", DETECTOR)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def harvest(run_glob: str = RUN_GLOB) -> dict[str, set[str]]:
    """Assessor-written evidence and notes from every kept run dir, grouped by skill.

    Dedupe is on the exact stripped string, per skill.
    """
    by_skill: dict[str, set[str]] = collections.defaultdict(set)
    for path in glob.glob(os.path.expanduser(run_glob), recursive=True):
        skill = next((s for s in SKILLS if f"/{s}-" in path), "unknown")
        try:
            with open(path, encoding="utf-8") as handle:
                document = json.load(handle)
        except Exception:
            continue
        for item in document.get("items", []):
            if not isinstance(item, dict):
                continue
            for field in ("evidence", "notes"):
                value = item.get(field)
                if isinstance(value, str) and value.strip():
                    by_skill[skill].add(value.strip())
    return dict(by_skill)


def measure(by_skill: dict[str, set[str]]) -> list[tuple[str, int, int, int]]:
    detector = load_detector()
    rows = []
    for skill in sorted(by_skill):
        strings = by_skill[skill]
        multiples = sum(1 for s in strings if detector.MULTIPLE_RE.search(s))
        fires = sum(1 for s in strings if detector.unsupported_multiple(s) is not None)
        rows.append((skill, len(strings), multiples, fires))
    return rows


def main() -> None:
    rows = measure(harvest())
    if not rows:
        print("no kept run dirs found — this tool reads machine-local data")
        return
    print(f"{'skill':28s} {'strings':>8s} {'multiples':>10s} {'fires':>6s}")
    for skill, n, m, f in rows:
        print(f"{skill:28s} {n:8d} {m:10d} {f:6d}")
    total = (sum(r[1] for r in rows), sum(r[2] for r in rows), sum(r[3] for r in rows))
    print(f"{'TOTAL':28s} {total[0]:8d} {total[1]:10d} {total[2]:6d}")
    print(
        f"\n2026-09-19 baseline: {BASELINE['strings']} strings, "
        f"{BASELINE['with_a_multiple']} with a multiple, {BASELINE['fires']} fire "
        f"(the defect). A fire count above the number of real defects is the signal to re-read "
        f"the design record."
    )


if __name__ == "__main__":
    main()
