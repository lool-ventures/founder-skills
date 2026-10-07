"""No internal token may appear in founder-visible text in any generated HTML page.

The compose-time scan covers `report.md`. The HTML generators are a separate delivery surface reading
the same artifacts, and nothing checked them: an enum or field name our producers write into an
evidence string reaches `report.html` exactly as it reaches the markdown.

SCOPE, stated so a green is not over-read:

  * Only TEXT NODES are scanned. Attribute values and script/style bodies are excluded — an
    `<option value="moat_count">` whose label reads "Moat Count" is not a leak, and JS identifiers are
    not founder-facing prose.
  * THE EXPLORERS ARE BARELY COVERED, and pretending otherwise would be worse than not scanning them.
    Measured text-node share of each page: visualize 1.4-4.4%, explore 0.1-0.2% (255-793 B of static
    text in a 300 KB page). Their founder-visible content is rendered by JavaScript from the embedded
    payload at runtime and never exists as a static text node, so this scan cannot see it. A
    display-string scan of the payload was tried and abandoned: it cannot distinguish a display field
    from a provenance map keyed by field name (`evidence_source.description == "agent_estimate"` is
    not a label), and produced a false positive on the first page it examined. What covers that
    surface today is the Cowork UI gate, i.e. a human reading the rendered page.
  * HTML output is not run through `substitute()` as a whole document, the way `report.md` is. This
    asserts that our PRODUCERS emit no internal token; it cannot rewrite one a sub-agent authors into
    free text.
  * CORRECTED: this file used to say an authored token "reaches `report.html` exactly as it reaches the
    markdown". That has not been true since compose began substituting the whole markdown document: the
    markdown was repaired and the HTML was not, so the two delivered pages read the SAME sentence two
    ways, which is worse than both being wrong and is a shape this scan cannot see. Where a string is
    shared, the repair now belongs at the one owner both renderers read it from (`_view._founder_prose`
    on the assumption rows). Strings only the HTML renders still bypass the policy -- the red team's
    `what_is_true` through `checked_multiples`, and the checklist notes.
"""

from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

import pytest
from compose_invocations import drive_compose

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / "founder-skills" / "tests" / "fixtures"

# (skill, generator) for every HTML generator in the fleet.
GENERATORS = [
    ("competitive-positioning", "visualize.py"),
    ("competitive-positioning", "explore.py"),
    ("financial-model-review", "visualize.py"),
    ("financial-model-review", "explore.py"),
    ("cap-table", "visualize.py"),
    ("cap-table", "explore.py"),
    ("ic-sim", "visualize.py"),
    ("market-sizing", "visualize.py"),
    ("deck-review", "visualize.py"),
    # The extracted-values review page — a page the founder opens and reads, and the 10th HTML
    # generator in the fleet. It was missing from this list while every other one was covered.
    ("financial-model-review", "review_inputs.py"),
]

# Static-text floor per generator. NOT one number: a 300 KB explorer legitimately yields ~250 B of
# text nodes, so a single floor either passes vacuously for explorers or fails honestly-thin pages.
_TEXT_FLOOR = {"visualize.py": 700, "explore.py": 200, "review_inputs.py": 200}


def _founder_text():  # type: ignore[no-untyped-def]
    path = REPO_ROOT / "founder-skills" / "scripts" / "_founder_text.py"
    spec = importlib.util.spec_from_file_location("_founder_text", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _strip_element(html: str, tag: str) -> str:
    """Drop every `<tag>...</tag>` span, whatever its case or attributes.

    Scanned rather than matched with `<tag.*?</tag>`, which is blind to
    `<TAG>` and so would leave a whole script body in the founder-visible
    text this file asserts over.
    """
    lowered = html.lower()
    kept: list[str] = []
    pos = 0
    while (start := lowered.find(f"<{tag}", pos)) != -1:
        close = lowered.find(f"</{tag}", start)
        if close == -1:
            break
        end = lowered.find(">", close)
        if end == -1:
            break
        kept.append(html[pos:start])
        kept.append(" ")
        pos = end + 1
    kept.append(html[pos:])
    return "".join(kept)


def _text_nodes(html: str) -> str:
    """Founder-visible text only: no script/style bodies, no attribute values."""
    html = _strip_element(html, "script")
    html = _strip_element(html, "style")
    return re.sub(r"<[^>]+>", " ", html)


def _cap_table_keep() -> frozenset[str]:
    path = REPO_ROOT / "founder-skills" / "skills" / "cap-table" / "scripts" / "_labels.py"
    spec = importlib.util.spec_from_file_location("_labels", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return frozenset(k for m in mod.MAPS.values() for k in m)


# The DELIVERABLE's own filename is not internal plumbing. A page that tells a founder "open
# explore.html directly in Chrome" is naming the file in their hands and giving them something they
# can act on — which is precisely the test `_founder_text` applies. The filename class cannot make
# that distinction (a name is a name), so the exception is stated here, narrowly: only the names of
# files this fleet actually delivers to a founder, never a script or module name.
_DELIVERABLE_FILENAMES = frozenset({"explore.html", "report.html", "explorer.html", "report.md"})


@pytest.mark.parametrize(("skill", "generator"), GENERATORS)
def test_generated_html_carries_no_internal_tokens(skill: str, generator: str) -> None:
    ft = _founder_text()
    script = REPO_ROOT / "founder-skills" / "skills" / skill / "scripts" / generator
    if not script.exists():
        pytest.skip(f"{skill} has no {generator}")

    with tempfile.TemporaryDirectory() as td:
        work = Path(td)
        drive_compose(skill, FIXTURES / skill, work)
        out = work / "page.html"
        if generator == "review_inputs.py":
            # Different CLI: positional inputs path, and --static is the Cowork branch (the
            # --workspace branch backgrounds an HTTP server that never exits). --static takes the
            # OUTPUT path, it is not a bare flag.
            argv = [str(script), str(work / "inputs.json"), "--static", str(out)]
        else:
            argv = [str(script), "--dir", str(work), "-o", str(out)]
            # deck-review's visualize.py sits behind the same authorization boundary as its
            # compose (see G2). These fixtures carry no gate, which is the legitimate ungated
            # path -- it just has to be stated rather than spelled as a missing flag.
            if skill == "deck-review" and generator == "visualize.py":
                argv.append("--ungated")
        result = subprocess.run([sys.executable, *argv], capture_output=True, text=True)
        assert result.returncode == 0, f"{skill}/{generator} failed: {result.stderr[-400:]}"
        html = out.read_text(encoding="utf-8")

    # Non-vacuity: a trivially small page would pass without proving anything.
    assert len(html) > 2000, f"{skill}/{generator} produced only {len(html)}B"
    text = _text_nodes(html)
    floor = _TEXT_FLOOR[generator]
    assert len(text) > floor, (
        f"{skill}/{generator} yielded {len(text)}B of text nodes, below its {floor}B floor — either the "
        f"stripper broke or the page stopped rendering static text"
    )

    keep = _cap_table_keep() if skill == "cap-table" else None
    found = ft.scan(text, extra_keep=keep)
    assert found["enums"] == [], (
        f"{skill}/{generator} shows internal token(s) in founder-visible text: {found['enums']}. "
        f"Render them through the shared founder-text policy, or stop writing them into the artifact."
    )
    # FILENAMES TOO. This assertion was missing, and its absence was not theoretical: a script name
    # injected into a counsel question rendered into the page and this test passed. The two classes
    # need separate assertions because `substitute()` fixes only one of them -- it unsnakes an enum,
    # and deliberately never rewrites a filename ("renaming a file in prose would be a lie"). So the
    # policy pass that cleans the enum class leaves this one to arrive intact, which makes a filename
    # the ONLY thing a scan of policied output can still catch, and it was the one thing unchecked.
    leaked_files = [f for f in found["filenames"] if f not in _DELIVERABLE_FILENAMES]
    assert leaked_files == [], (
        f"{skill}/{generator} shows internal filename(s) in founder-visible text: {leaked_files}. "
        f"A founder cannot act on a script name; state what it does, or stop writing it into the artifact."
    )


def test_the_generator_list_is_the_deliverable_writers_plus_the_review_page() -> None:
    """The deliverable writers are listed once (`html_writer_invocations`); this list adds only the
    mid-run review page, so a new writer cannot be scanned here and missed there, or the reverse."""
    from html_writer_invocations import WRITERS

    assert set(GENERATORS) - {("financial-model-review", "review_inputs.py")} == {(w[0], w[1]) for w in WRITERS}


def test_the_scanner_would_catch_a_token_in_a_text_node() -> None:
    """Guard the stripper: if it over-stripped, every page above would pass vacuously."""
    ft = _founder_text()
    html = "<div><p>status is switching_costs</p><option value='moat_count'>Moat Count</option></div>"
    found = ft.scan(_text_nodes(html))
    assert found["enums"] == ["switching_costs"], found
    assert "moat_count" not in found["enums"], "an attribute value is not founder-visible text"


def test_the_scanner_would_catch_a_filename_in_a_text_node() -> None:
    """The filenames control, mirroring the enum one above.

    The per-generator `filenames` assertion is currently green because exactly ONE hit exists
    fleet-wide and it is exempted as a delivered filename. So that assertion is `[] == []` today, and
    without this control a broken stripper or a broken class would read as clean forever. It is the
    class most worth a control, because the shared policy deliberately never rewrites a filename --
    which makes a filename the one internal token a scan of policied output can still catch.
    """
    ft = _founder_text()
    html = "<div><p>generated by extract_aoa.py</p></div>"
    found = ft.scan(_text_nodes(html))
    assert found["filenames"] == ["extract_aoa.py"], found
    assert "explore.html" in _DELIVERABLE_FILENAMES, (
        "the exemption list must still name the deliverable that keeps the live assertion green, or "
        "the one real hit fleet-wide would red for the wrong reason"
    )


_ = Callable  # re-exported type import kept for parametrize signature clarity


# Every attribute whose value a browser shows to a person on hover or to a screen reader. Not a
# guess: `data-tooltip` is the DOMINANT mechanism in this fleet (four live sites against two for
# `title`), with its own JS handler in two skills, and the first version of this check dismissed that
# class as a hypothetical variant.
_TOOLTIP_ATTRS = ("title", "data-tooltip", "aria-label")

# The signature of the defect that actually shipped: the SAME expression rendered RAW in the tooltip
# and HUMANISED in the visible text beside it, so the founder reads "broad-based weighted average"
# and hovers to find `broad_based_weighted_average`.
#
# The predicate is the RELATIONSHIP, not "the value looks internal" and not "the placeholder is
# unresolved". Both of those were tried and are unsound: a template placeholder is substituted by the
# browser after delivery, so a legitimate prose tooltip built by concatenation
# (`fmr/explore.py:1733`, whose value is a benchmark explanation) is indistinguishable from a defect
# by that test -- measured, it false-positives on the first real site it meets.
_RAW_BESIDE_HUMANISED = re.compile(
    r'title="[^"]*?escape\(\s*([A-Za-z_][\w.]*)\s*\)[^"]*"[^>]*>[^<]{0,80}?humanize\([^)]*?\1'
)

# Specimens live INSIDE the detector, not beside it. A companion control can be deleted on its own;
# these cannot be removed without removing the assertion that uses them. HISTORICAL are the exact
# strings that shipped; LEGITIMATE are live lines that must survive, quoted from the tree so the set
# cannot drift into strawmen.
_TOOLTIP_SPECIMENS_BAD = (
    '`<span class="term" title="${escape(val)}">${escape(humanize(cat, val))}</span>`',
    '<span class="badge ${s.completeness}" title="${escape(s.completeness)}">'
    '${escape(humanize("completeness", s.completeness))}</span>',
)
_TOOLTIP_SPECIMENS_OK = (
    # fmr/explore.py:1733 — prose built by concatenation; the value is a benchmark explanation.
    """'<td><span class="badge ' + referenceRating + '" title="' + escHtml(refNote) + '">' + refIcon""",
    # cap-table/explore.py:494 — a literal prose tooltip on a button.
    '<button class="btn" id="compare-toggle" title="Compare two scenarios side by side">',
)


def test_the_tooltip_signature_catches_what_shipped_and_spares_what_did_not() -> None:
    """The positive case for the detector below, which is otherwise unfalsifiable.

    A detector that scans live data and asserts "no offenders" proves nothing once the data is clean
    -- and clean is the goal. Blinding its matcher to `(?!x)x` left it green. So the matcher is
    exercised here against known input in both directions: it must flag every string that actually
    shipped, and spare every live line that must survive.
    """
    for s in _TOOLTIP_SPECIMENS_BAD:
        assert _RAW_BESIDE_HUMANISED.search(s), f"the matcher no longer catches a shipped defect: {s[:70]}"
    for s in _TOOLTIP_SPECIMENS_OK:
        assert not _RAW_BESIDE_HUMANISED.search(s), f"the matcher flags legitimate prose: {s[:70]}"


@pytest.mark.parametrize(("skill", "generator"), GENERATORS)
def test_no_generator_puts_a_raw_value_in_a_tooltip(skill: str, generator: str) -> None:
    """Tooltips are founder-visible text that no text-node scan reaches.

    Read from the GENERATED PAGE, not from generator source. The first version read Python source on
    the stated grounds that JS-built tooltips "never exist as static HTML at all" -- false, and
    measuring it is what replaced the instrument: a JS template literal is emitted verbatim and the
    browser substitutes after delivery, so the page carries both. Source-reading also inherits the
    generator's own quoting and f-string layers, and measured 0 of 6 live tooltip sites.
    """
    ft = _founder_text()
    script = REPO_ROOT / "founder-skills" / "skills" / skill / "scripts" / generator
    if not script.exists():
        pytest.skip(f"{skill} has no {generator}")

    with tempfile.TemporaryDirectory() as td:
        work = Path(td)
        drive_compose(skill, FIXTURES / skill, work)
        out = work / "page.html"
        if generator == "review_inputs.py":
            argv = [str(script), str(work / "inputs.json"), "--static", str(out)]
        else:
            argv = [str(script), "--dir", str(work), "-o", str(out)]
            if skill == "deck-review" and generator == "visualize.py":
                argv.append("--ungated")
        result = subprocess.run([sys.executable, *argv], capture_output=True, text=True)
        assert result.returncode == 0, f"{skill}/{generator} failed: {result.stderr[-400:]}"
        html = out.read_text(encoding="utf-8")

    assert not _RAW_BESIDE_HUMANISED.search(html), (
        f"{skill}/{generator} shows a humanised label and hides the raw code in its tooltip. The "
        "visible text is already readable; the tooltip adds only our vocabulary."
    )

    values: list[str] = []
    for attr in _TOOLTIP_ATTRS:
        values.extend(re.findall(rf'{attr}="([^"]*)"', html))
        values.extend(re.findall(rf"{attr}='([^']*)'", html))
    keep = _cap_table_keep() if skill == "cap-table" else None
    found = ft.scan(" ".join(values), extra_keep=keep)
    assert found["enums"] == [] and found["filenames"] == [], (
        f"{skill}/{generator} hides internal vocabulary in a tooltip: {found}"
    )


def test_a_disabled_lens_explains_itself_without_naming_an_artifact() -> None:
    """The branch the fleet scan cannot reach, because the fixture never takes it.

    THE THIRD VACUITY MECHANISM. The parametrized scan above asserts "no internal token in the
    generated page", and it is honest about what it finds — but the financial-model-review fixture
    carries every artifact, so the code path that renders a DISABLED lens never executes. The scan
    therefore reported clean on a page that had nothing to say, while the disabled-lens path shipped
    `runway.json` into a founder-visible `<div class="stub-reason">` and into a tooltip beside it.

    A detector's silence means nothing when the candidate population is empty. Specimens cannot fix
    that; only exercising the branch can, which is what this does — it stages the fixture, stubs one
    artifact out, and scans the page the founder would actually get.
    """
    import json as _json
    import subprocess
    import sys as _sys

    ft = _founder_text()
    script = REPO_ROOT / "founder-skills" / "skills" / "financial-model-review" / "scripts" / "explore.py"
    with tempfile.TemporaryDirectory() as td:
        work = Path(td)
        drive_compose("financial-model-review", FIXTURES / "financial-model-review", work)
        # A skipped artifact, the shape the producer writes when a lens could not be computed.
        (work / "runway.json").write_text(
            _json.dumps({"skipped": True, "metadata": {"run_id": "test-run"}}), encoding="utf-8"
        )
        out = work / "page.html"
        result = subprocess.run(
            [_sys.executable, str(script), "--dir", str(work), "-o", str(out)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr[-400:]
        html = out.read_text(encoding="utf-8")

    assert "stub-reason" in html, (
        "the disabled-lens path did not render — this test exists to exercise it, so if the page no "
        "longer takes that branch the guard has gone back to proving nothing"
    )
    text = _text_nodes(html)
    found = ft.scan(text)
    assert found["filenames"] == [], (
        f"a disabled lens names our artifact files to the founder: {found['filenames']}. They cannot "
        "act on a filename — say which analysis is missing, not which file."
    )
    assert found["enums"] == [], found["enums"]


# A review written the way a reviewer slips: a competitor's slug, our file names and our field names in
# the three fields printed to the founder word for word. The competitive-positioning fixture carries no
# review, so without this seed the fleet scans above pass over "What an Outside Review Found" having
# rendered nothing into it -- the counsel-packet precedent in test_compose_invariants.py.
_CP_SEEDED_FINDINGS: list[dict[str, str]] = [
    {
        "claim_attacked": "The rating of quickbooks-online on switching_costs in moat_scores.json",
        "what_is_true": "pilot-com publishes a migration guide, so the placement in positioning_scores.json "
        "overstates lock-in; see landscape.json",
        "evidence_quote": "Most customers complete their migration within two weeks of signing up",
        "source_url": "https://example.com/migration",
        "source_title": "Help centre",
        "severity": "high",
    },
    {
        "claim_attacked": "The differentiation claim in product_profile.json",
        "what_is_true": "manual-spreadsheets remains the default for most small firms per checklist.json",
        "evidence_quote": "Most small firms still reconcile their books in a spreadsheet every month",
        "source_url": "https://example.com/survey",
        "source_title": "Survey",
        "severity": "low",
    },
]
_CP_SEEDED_UNCHECKED = ["The quickbooks-online rating on network_effects, because the directory needs a login"]


def test_the_outside_review_section_carries_no_internal_tokens_on_either_page() -> None:
    import json as _json
    import sys as _sys

    ft = _founder_text()
    scripts = REPO_ROOT / "founder-skills" / "skills" / "competitive-positioning" / "scripts"
    raw = " ".join(
        [f[k] for f in _CP_SEEDED_FINDINGS for k in ("claim_attacked", "what_is_true")] + _CP_SEEDED_UNCHECKED
    )
    seeded = ft.scan(raw)
    assert seeded["filenames"] and seeded["enums"], (
        f"the seed no longer carries the tokens it exists to push through the renderers: {seeded}"
    )
    with tempfile.TemporaryDirectory() as td:
        work = Path(td) / "analysis"
        work.mkdir()
        for src in (FIXTURES / "competitive-positioning").glob("*.json"):
            (work / src.name).write_bytes(src.read_bytes())
        run_id = _json.loads((work / "landscape.json").read_text(encoding="utf-8"))["metadata"]["run_id"]
        docs = Path(td) / "docs"
        docs.mkdir()
        piped = subprocess.run(
            [
                _sys.executable,
                str(scripts / "cp_red_team.py"),
                "--run-id",
                run_id,
                "--uploads-dir",
                str(docs),
                "-o",
                str(work / "redteam.json"),
            ],
            input=_json.dumps(
                {
                    "findings": _CP_SEEDED_FINDINGS,
                    "could_not_check": _CP_SEEDED_UNCHECKED,
                    "sources_read": [],
                    "metadata": {"run_id": run_id},
                }
            ),
            capture_output=True,
            text=True,
        )
        assert piped.returncode == 0, piped.stderr[-400:]
        assert _json.loads(piped.stdout)["accepted"] == 2, piped.stdout
        composed = subprocess.run(
            [
                _sys.executable,
                str(scripts / "compose_report.py"),
                "--dir",
                str(work),
                "-o",
                str(work / "report.json"),
                "--write-md",
                str(work / "report.md"),
            ],
            capture_output=True,
            text=True,
        )
        assert composed.returncode == 0, composed.stderr[-400:]
        md = (work / "report.md").read_text(encoding="utf-8")
        page = subprocess.run(
            [_sys.executable, str(scripts / "visualize.py"), "--dir", str(work)],
            capture_output=True,
            text=True,
        )
        assert page.returncode == 0, page.stderr[-400:]

    heading = "What an Outside Review Found"
    md_section = md[md.index(heading) :]
    md_section = md_section[: md_section.find("\n## ", 1)]
    text = _text_nodes(page.stdout)
    html_section = text[text.index(heading) :][:4000]
    for name, section in (("report.md", md_section), ("report.html", html_section)):
        # Non-vacuity: the seeded findings reached the section, rather than a "no review" sentence.
        assert "Most customers complete their migration" in section, f"{name} did not render the seed"
        found = ft.scan(section)
        assert found == {"enums": [], "filenames": []}, (
            f"{name}'s outside-review section reaches the founder with internal tokens: {found}"
        )
