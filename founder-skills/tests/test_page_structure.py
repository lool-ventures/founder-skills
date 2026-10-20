"""Structure every redesigned page keeps, read by meaning (ids, data-*, tags), never by class name.

The pages adopt the shared UI module one skill at a time; `SHELL_PAGES` lists the writers on the shared
shell, and `CHECKLIST_PAGES` those of them that also render a scored checklist with a ring. A writer joins
in the same change that moves it onto the shell, so these checks land red before the rewrite and stay as
the guard after it.

Two families:
  * the page shell: a phone viewport, a language, one `<main>`, an explicit light colour scheme,
    every `<details>` opened by a `<summary>`, and no content hidden by an inline `display:none`
    toggle (content that JS shows or hides is invisible with JS off, and missing from a printout);
  * checklist coverage: every criterion in the run's checklist appears on the page exactly once, by
    `data-criterion`, carrying its own status; every group says which statuses it holds
    (`data-has`), which is what lets the filter hide a group with nothing to show.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from _dom import Element, by_attr, by_id, by_tag, parse
from compose_invocations import drive_compose
from no_ledger_goldens import FIXTURES, html_argv

# (skill, script) of every writer that renders a scored checklist and a ring on the shared shell.
CHECKLIST_PAGES: tuple[tuple[str, str], ...] = (
    ("financial-model-review", "visualize.py"),
    ("financial-model-review", "explore.py"),
    ("deck-review", "visualize.py"),
    ("market-sizing", "visualize.py"),
    ("ic-sim", "visualize.py"),
)
# (skill, script) of every writer on the shared shell: the checklist pages, and pages with no score.
SHELL_PAGES: tuple[tuple[str, str], ...] = (*CHECKLIST_PAGES, ("cap-table", "visualize.py"))

# The statuses each skill's checklist can carry, as filter chips. market-sizing grades pass / fail only
# (its `checklist.py` has no warn), so its page offers no Warn chip and no "Needs attention" chip, which
# would only repeat Fail.
_CHIPS_ALL = ["ck-f-all", "ck-f-attn", "ck-f-fail", "ck-f-warn", "ck-f-pass", "ck-f-na"]
# ic-sim's dimensions carry a moderate result, which is neither a problem nor a pass: its own chip.
_CHIPS = {
    "market-sizing": ["ck-f-all", "ck-f-fail", "ck-f-pass", "ck-f-na"],
    "ic-sim": ["ck-f-all", "ck-f-attn", "ck-f-fail", "ck-f-warn", "ck-f-neutral", "ck-f-pass", "ck-f-na"],
}

# The status each skill's checklist item carries, as the page's `data-status` names it.
_TONE_DEFAULT = {"pass": "pass", "fail": "fail", "warn": "warn", "not_applicable": "na"}
_TONES = {
    "ic-sim": {
        "strong_conviction": "pass",
        "moderate_conviction": "neutral",
        "concern": "warn",
        "dealbreaker": "fail",
        "to_confirm": "na",
        "not_applicable": "na",
    }
}


def _tone(skill: str) -> dict[str, str]:
    return _TONES.get(skill, _TONE_DEFAULT)


# Where each skill's checklist items live: (artifact, path to the list). ic-sim's are its 28 dimensions.
_ITEMS: dict[str, tuple[str, tuple[str, ...]]] = {"ic-sim": ("score_dimensions.json", ("items",))}
# Where each skill's checklist score lives, for the ring test.
_SCORE: dict[str, tuple[str, tuple[str, ...]]] = {"ic-sim": ("score_dimensions.json", ("summary", "conviction_score"))}


def _items_of(skill: str, work: Path) -> list[dict[str, Any]]:
    artifact, path = _ITEMS.get(skill, ("checklist.json", ("items",)))
    node: Any = json.loads((work / artifact).read_text())
    for key in path:
        node = node[key]
    items: list[dict[str, Any]] = node
    return items


def _many_problems_fmr(work: Path) -> None:
    """Turn the fixture's checklist into one with many fails and warns (13 and 17), the shape a weak
    model produces. The fixture alone carries one of each, which hides a list that does not scale."""
    path = work / "checklist.json"
    ck = json.loads(path.read_text())
    applicable = [i for i in ck["items"] if i["status"] != "not_applicable"]
    for n, it in enumerate(applicable[:30]):
        it["status"] = "fail" if n < 13 else "warn"
    s = ck["summary"]
    for k in ("pass", "fail", "warn", "not_applicable"):
        s[k] = sum(1 for i in ck["items"] if i["status"] == k)
    s["failed_items"] = [dict(i, severity="high") for i in applicable[:13]]
    s["warned_items"] = [dict(i, severity="medium") for i in applicable[13:30]]
    s["score_pct"], s["overall_status"] = 44.0, "major_revision"
    path.write_text(json.dumps(ck))


def _many_problems_dr(work: Path) -> None:
    """deck-review's shape: 12 fails and 8 warns among the weighted criteria, with the counts and
    `by_category` recomputed the way its `checklist.py` does (the weightless duplicate left out)."""
    path = work / "checklist.json"
    ck = json.loads(path.read_text())
    weighted = [i for i in ck["items"] if i.get("weight", 1) != 0 and i["status"] != "not_applicable"]
    for n, it in enumerate(weighted[:20]):
        it["status"] = "fail" if n < 12 else "warn"
        it["evidence"] = f"Invented evidence {n}: the slide states this with nothing behind it."
    s = ck["summary"]
    counted = [i for i in ck["items"] if i.get("weight", 1) != 0]
    for k in ("pass", "fail", "warn", "not_applicable"):
        s[k] = sum(1 for i in counted if i["status"] == k)
    by_cat: dict[str, dict[str, int]] = {}
    for i in counted:
        by_cat.setdefault(i["category"], {"pass": 0, "fail": 0, "warn": 0, "not_applicable": 0})[i["status"]] += 1
    s["by_category"] = by_cat
    s["score_pct"], s["overall_status"] = 36.0, "major_revision"
    path.write_text(json.dumps(ck))


def _many_problems_ms(work: Path) -> None:
    """market-sizing's shape: pass / fail / not applicable only, `failed_items` as ids."""
    path = work / "checklist.json"
    ck = json.loads(path.read_text())
    passing = [i for i in ck["items"] if i["status"] == "pass"]
    for n, it in enumerate(passing[:9]):
        it["status"] = "fail"
        it["notes"] = f"Invented note {n}: one source, and nothing checks it."
    s = ck["summary"]
    for k in ("pass", "fail", "not_applicable"):
        s[k] = sum(1 for i in ck["items"] if i["status"] == k)
    s["failed_items"] = [i["id"] for i in ck["items"] if i["status"] == "fail"]
    s["all_pass"] = False
    s["score_pct"], s["overall_status"] = 55.0, "needs_work"
    path.write_text(json.dumps(ck))


def _many_problems_ic(work: Path) -> None:
    """ic-sim's shape: 3 dealbreakers on startup-side categories (Team, Market, Product, never Fund Fit, so
    the verdict is a hard pass in generic mode too), 8 concerns and 4 to confirm, with the summary recomputed
    by the producer itself (`score_dimensions.validate_dimensions`)."""
    import importlib.util

    path = work / "score_dimensions.json"
    sd = json.loads(path.read_text())
    spec = importlib.util.spec_from_file_location(
        "_ps_score_dimensions",
        Path(__file__).resolve().parents[1] / "skills" / "ic-sim" / "scripts" / "score_dimensions.py",
    )
    assert spec is not None and spec.loader is not None
    producer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(producer)
    items = sd["items"]
    for cat in ("Team", "Market", "Product"):
        next(i for i in items if i["category"] == cat)["status"] = "dealbreaker"
    rest = [i for i in items if i["status"] not in ("dealbreaker", "not_applicable")]
    for n, it in enumerate(rest[:12]):
        it["status"] = "concern" if n < 8 else "to_confirm"
        it["evidence"] = f"Invented evidence {n}: the materials state this with nothing behind it."
    result = producer.validate_dimensions(items, fund_mode=sd["summary"].get("fund_mode", "generic"))
    assert result["summary"]["verdict"] == "hard_pass", result["summary"]["verdict"]
    sd["items"], sd["summary"] = result["items"], result["summary"]
    path.write_text(json.dumps(sd))


_MANY_PROBLEMS: dict[str, Callable[[Path], None]] = {
    "financial-model-review": _many_problems_fmr,
    "deck-review": _many_problems_dr,
    "market-sizing": _many_problems_ms,
    "ic-sim": _many_problems_ic,
}
_VARIANTS = ("fixture", "many-problems")
_CACHE: dict[tuple[str, str, str], tuple[str, list[dict[str, Any]]]] = {}


def _render(skill: str, script: str, variant: str) -> tuple[str, list[dict[str, Any]]]:
    """(page html, the checklist items the page was built from)."""
    key = (skill, script, variant)
    if key not in _CACHE:
        with tempfile.TemporaryDirectory() as td:
            work = Path(td)
            drive_compose(skill, FIXTURES / skill, work)
            if variant == "many-problems":
                _MANY_PROBLEMS[skill](work)
            out = work / "page.html"
            proc = subprocess.run(
                [sys.executable, *html_argv(skill, script, work, out)], capture_output=True, text=True
            )
            assert proc.returncode == 0, proc.stderr
            items = _items_of(skill, work) if (skill, script) in CHECKLIST_PAGES else []
            _CACHE[key] = (out.read_text(encoding="utf-8"), items)
    return _CACHE[key]


# A page with no checklist has no many-problems variant (`_MANY_PROBLEMS` seeds checklist failures).
_PAGES = [
    pytest.param(s, w, v, id=f"{s}/{w}/{v}")
    for s, w in SHELL_PAGES
    for v in _VARIANTS
    if v == "fixture" or s in _MANY_PROBLEMS
]
_CK_PAGES = [pytest.param(s, w, v, id=f"{s}/{w}/{v}") for s, w in CHECKLIST_PAGES for v in _VARIANTS]


def _doc(skill: str, script: str, variant: str) -> Element:
    return parse(_render(skill, script, variant)[0])


@pytest.mark.parametrize(("skill", "script", "variant"), _PAGES)
def test_the_page_has_a_phone_viewport_a_language_and_one_main(skill: str, script: str, variant: str) -> None:
    doc = _doc(skill, script, variant)
    metas = {m.get("name"): m.get("content") for m in by_tag(doc, "meta") if m.has("name")}
    assert "width=device-width" in (metas.get("viewport") or "")
    assert metas.get("color-scheme") == "light", "no dark styles ship yet, so the page must say it is light"
    (html_el,) = by_tag(doc, "html")
    assert html_el.get("lang") == "en"
    assert len(by_tag(doc, "main")) == 1


# The line each skill's report prints its headline score on, and the score in it. financial-model-review's is
# its verdict (report.json `verdict`, the report's first paragraph and the printed hand-over), which names the
# score the ring shows; its `**Overall:**` line always prints the checklist score, which a deck-only review
# does not headline. Which score and which name is held, per combination, by `test_score_owners.py`.
_REPORT_SCORE = {
    "financial-model-review": r"(?:Model Quality|Deck Financial Readiness): [^(\n]*\(([\d.]+)%\)",
    "deck-review": r"\*\*Deck-craft score:\*\* ([\d.]+)%",
    "market-sizing": r"Self-check: ([\d.]+)%",
    "ic-sim": r"\*\*Conviction Score:\*\* ([\d.]+)%",
}


# Two invented scores: one with a decimal (a page that rounds drifts from a report that does not) and one
# whole (a page or report that prints the raw float says "63.0" where the fleet format says "63").
_INVENTED_SCORES = (63.7, 63.0)


@pytest.mark.parametrize("score", _INVENTED_SCORES)
@pytest.mark.parametrize(("skill", "script"), CHECKLIST_PAGES)
def test_the_ring_states_the_score_as_the_report_states_it(skill: str, script: str, score: float) -> None:
    """The ring (and its spoken label) and the report state one score one way, the fleet's: one decimal at
    most and no trailing zero ("63.7%", "63%")."""
    import re
    import shutil

    with tempfile.TemporaryDirectory() as td:
        fix, work = Path(td) / "fix", Path(td) / "work"
        shutil.copytree(FIXTURES / skill, fix)
        work.mkdir()
        artifact, path = _SCORE.get(skill, ("checklist.json", ("summary", "score_pct")))
        ck = json.loads((fix / artifact).read_text())
        ck[path[0]][path[1]] = score
        if skill == "ic-sim":
            # A score in the more-diligence band with that verdict, so no score-verdict mismatch fires.
            ck["summary"]["verdict"] = "more_diligence"
        (fix / artifact).write_text(json.dumps(ck))
        report = json.loads(drive_compose(skill, fix, work).read_text())
        md = report["verdict"] if skill == "financial-model-review" else report["report_markdown"]
        out = work / "page.html"
        proc = subprocess.run([sys.executable, *html_argv(skill, script, work, out)], capture_output=True, text=True)
        assert proc.returncode == 0, proc.stderr
        doc = parse(out.read_text(encoding="utf-8"))
    m = re.search(_REPORT_SCORE[skill], md)
    assert m, f"no score line in {skill}'s report.md"
    report_score = m.group(1)
    (ring,) = [e for e in doc.iter() if e.get("role") == "img" and " percent" in (e.get("aria-label") or "")]
    ring_score = re.search(r"([\d.]+) percent", ring.get("aria-label") or "")
    assert ring_score
    assert ring_score.group(1) == report_score, (ring_score.group(1), report_score)
    assert report_score == f"{round(score, 1):g}", (report_score, score)
    shown = [e.text() for e in doc.iter() if e.text() == f"{ring_score.group(1)}%"]
    assert shown, "the ring prints the same figure it speaks"


_SKILL_NAMES = {
    "financial-model-review": "Financial Model Review",
    "deck-review": "Deck Review",
    "market-sizing": "Market Sizing",
    "ic-sim": "IC Simulation",
    "cap-table": "Cap Table",
}


@pytest.mark.parametrize(("skill", "script", "variant"), _PAGES)
def test_the_page_has_exactly_one_footer_line(skill: str, script: str, variant: str) -> None:
    """One footer, written by the shell: "<skill> · founder skills by lool ventures · Share feedback".
    No page adds a "Generated by … Agent" line of its own beside it."""
    html = _render(skill, script, variant)[0]
    doc = parse(html)
    (footer,) = by_tag(doc, "footer")
    text = footer.text()
    assert text.startswith(_SKILL_NAMES[skill]) and "founder skills by lool ventures" in text, text
    assert [a.text() for a in footer.iter() if a.tag == "a"][-1] == "Share feedback"
    assert footer.parent is not None and footer.parent.tag == "body", "the footer sits outside <main>"
    assert "Generated by" not in html


@pytest.mark.parametrize(("skill", "script", "variant"), _PAGES)
def test_every_details_opens_with_a_summary(skill: str, script: str, variant: str) -> None:
    doc = _doc(skill, script, variant)
    details = by_tag(doc, "details")
    for d in details:
        first = next((c for c in d.children if isinstance(c, Element)), None)
        assert first is not None and first.tag == "summary", f"<details> without a leading <summary>: {d.attrs}"


@pytest.mark.parametrize(("skill", "script", "variant"), _PAGES)
def test_no_content_is_hidden_by_an_inline_display_none(skill: str, script: str, variant: str) -> None:
    doc = _doc(skill, script, variant)
    hidden = [
        e
        for e in doc.iter()
        if "display:none" in (e.get("style") or "").replace(" ", "") and e.text() and e.tag not in ("script", "style")
    ]
    assert not hidden, [(e.tag, e.attrs, e.text()[:60]) for e in hidden]


@pytest.mark.parametrize(("skill", "script", "variant"), _CK_PAGES)
def test_every_checklist_criterion_appears_once_with_its_status(skill: str, script: str, variant: str) -> None:
    html, items = _render(skill, script, variant)
    doc = parse(html)
    rows = by_attr(doc, "data-criterion")
    seen: dict[str, list[Element]] = {}
    for r in rows:
        seen.setdefault(r.get("data-criterion") or "", []).append(r)
    want = {i["id"]: _tone(skill)[i["status"]] for i in items}
    assert set(seen) == set(want), (sorted(set(want) - set(seen)), sorted(set(seen) - set(want)))
    for cid, els in seen.items():
        assert len(els) == 1, f"{cid} appears {len(els)} times"
        assert els[0].get("data-status") == want[cid], (cid, els[0].get("data-status"), want[cid])
    # Each item's own label is its row's text, the evidence below it.
    by_id_label = {i["id"]: i["label"] for i in items}
    for cid, (el,) in seen.items():
        assert by_id_label[cid] in el.text(), cid


@pytest.mark.parametrize(("skill", "script", "variant"), _CK_PAGES)
def test_every_checklist_group_names_the_statuses_it_holds(skill: str, script: str, variant: str) -> None:
    html, items = _render(skill, script, variant)
    doc = parse(html)
    groups = by_attr(doc, "data-has")
    assert groups, "no checklist group carries data-has"
    want: dict[str, set[str]] = {}
    for i in items:
        want.setdefault(i["category"], set()).add(_tone(skill)[i["status"]])
    assert len(groups) == len(want)
    for g in groups:
        # A weightless row (a criterion whose result counts under another) is counted nowhere.
        rows = [e for e in g.iter() if e.has("data-criterion") and e.get("data-weight") != "0"]
        has = set((g.get("data-has") or "").split())
        assert has == {r.get("data-status") for r in rows}, g.attrs
        # Every group renders open; the page's script closes the all-pass ones on load, so a reader
        # with scripts off (or a printout) still sees every criterion.
        assert g.tag == "details" and g.has("open"), g.attrs


@pytest.mark.parametrize(("skill", "script", "variant"), _CK_PAGES)
def test_the_checklist_filters_cover_every_status(skill: str, script: str, variant: str) -> None:
    doc = _doc(skill, script, variant)
    radios = [e for e in by_tag(doc, "input") if e.get("type") == "radio" and e.get("name") == "ck-f"]
    ids = [r.get("id") for r in radios]
    want = _CHIPS.get(skill, _CHIPS_ALL)
    assert ids == want
    assert [r.has("checked") for r in radios] == [True] + [False] * (len(want) - 1)
    labels = {e.get("for") for e in by_tag(doc, "label") if e.has("for")}
    assert set(ids) <= labels
    # "All" counts exactly the rows it shows (a weightless row included).
    (all_chip,) = [e for e in by_tag(doc, "label") if e.get("for") == "ck-f-all"]
    assert all_chip.text() == f"All {len(by_attr(doc, 'data-criterion'))}", all_chip.text()


# Classes that only group markup and carry no styling of their own (a script or a test hook reads
# them, or a parent's rule reaches the children). Every other class on a page must have a rule: a class
# with no rule is markup a restyle orphaned, which renders as bare text.
_UNSTYLED_STRUCTURAL = frozenset({"ui-ck", "ui-hero__text", "ui-finding-col", "active-eligible"})


@pytest.mark.parametrize(("skill", "script", "variant"), _PAGES)
def test_every_class_on_the_page_has_a_rule(skill: str, script: str, variant: str) -> None:
    import re

    html = _render(skill, script, variant)[0]
    doc = parse(html)
    css = " ".join(e.text() for e in by_tag(doc, "style"))
    styled = set(re.findall(r"\.([A-Za-z_][\w-]*)", css))
    used: set[str] = set()
    for e in doc.iter():
        if e.tag in ("script", "style"):
            continue
        used.update((e.get("class") or "").split())
    assert used, "the page carries no classes at all"
    orphans = sorted(used - styled - _UNSTYLED_STRUCTURAL)
    assert not orphans, f"class(es) with no CSS rule: {orphans}"


@pytest.mark.parametrize(("skill", "script", "variant"), _CK_PAGES)
def test_the_score_links_to_the_checklist(skill: str, script: str, variant: str) -> None:
    doc = _doc(skill, script, variant)
    target = by_id(doc, "checklist")
    assert target is not None
    links = [a for a in by_tag(doc, "a") if a.get("href") == "#checklist"]
    assert links, "the score ring does not link to the checklist"
    ring = [e for e in doc.iter() if e.get("role") == "img" and "percent" in (e.get("aria-label") or "")]
    assert ring, "no score ring with a spoken label"
