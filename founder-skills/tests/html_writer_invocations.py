"""The nine HTML pages a run delivers, and how each writer is invoked.

One list, so the tests that stamp a page with its run id and the tests that scan a page's founder-facing
text cannot disagree about which writers exist. The extracted-values review page is not here: it is a
page shown mid-run, not a deliverable.
"""

from __future__ import annotations

from pathlib import Path

from no_ledger_goldens import HTML_WRITERS, html_argv

# The file each writer's skill delivers, as its SKILL.md names it.
_OUT_NAMES = {
    ("financial-model-review", "explore.py"): "explore.html",
    ("competitive-positioning", "explore.py"): "explore.html",
    ("cap-table", "explore.py"): "explorer.html",
}

# (skill, script, out_name, deliverable_key, base_flags)
WRITERS: tuple[tuple[str, str, str, str, tuple[str, ...]], ...] = tuple(
    (
        skill,
        script,
        _OUT_NAMES.get((skill, script), "report.html"),
        key,
        ("--ungated",) if (skill, script) == ("deck-review", "visualize.py") else (),
    )
    for skill, script, key in HTML_WRITERS
)


def argv(skill: str, script: str, work: Path, out: Path, run_id: str | None = None) -> list[str]:
    """The writer's argv (without the interpreter), with `--run-id` when one is given."""
    args = html_argv(skill, script, work, out)
    if run_id is not None:
        args += ["--run-id", run_id]
    return args
