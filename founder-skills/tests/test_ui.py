"""The shared page components (`scripts/_ui.py`): output shape, escaping, and the CSS/JS contract.

This is the one test file allowed to assert on the module's class names: page tests read pages by
id, data-* and text (`_dom.py`), so a restyle moves only this file.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from types import ModuleType

import pytest
from _dom import by_attr, by_tag, parse

REPO_ROOT = Path(__file__).resolve().parents[2]
_UI_PATH = REPO_ROOT / "founder-skills" / "scripts" / "_ui.py"


def _ui() -> ModuleType:
    spec = importlib.util.spec_from_file_location("_ui_under_test", _UI_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ui = _ui()
XSS = '<script>alert("x")</script>&'


# --- the CSS and JS constants ----------------------------------------------------------------------


@pytest.mark.parametrize("name", ["UI_CSS", "UI_JS"])
def test_constants_cannot_end_a_script_or_open_a_style_early(name: str) -> None:
    """The founder-text scan ends a <script> span at the first `</script`; a literal inside the shared
    JS would turn the rest of the script into "text" and red the fleet scan on JS identifiers."""
    text = getattr(ui, name).lower()
    assert "</script" not in text
    assert "<style" not in text
    assert "</style" not in text


@pytest.mark.parametrize("name", ["UI_CSS", "UI_JS"])
def test_constants_never_name_the_embedded_payload(name: str) -> None:
    """The dead-payload analyzer scans the whole page for `DATA`; shared code naming it would flip a
    page's payload to dynamic access."""
    assert "DATA" not in getattr(ui, name)


def test_the_css_has_a_filter_rule_for_every_chip() -> None:
    css = ui.UI_CSS
    for key, status in (("fail", "fail"), ("warn", "warn"), ("pass", "pass"), ("na", "na"), ("neutral", "neutral")):
        assert f'#ck-f-{key}:checked ~ .ui-ck__groups .ui-ck__item:not([data-status="{status}"])' in css
        assert f'#ck-f-{key}:checked ~ .ui-ck__groups .ui-ck__grp:not([data-has~="{status}"])' in css
        assert f'#ck-f-{key}:checked ~ .ui-ck__chips [for="ck-f-{key}"]' in css
    assert '#ck-f-attn:checked ~ .ui-ck__groups .ui-ck__grp:not([data-has~="fail"]):not([data-has~="warn"])' in css
    assert ":has(" not in css


def _rule(selector: str) -> str:
    """The declaration block of the first rule whose selector list is exactly `selector`."""
    m = re.search(r"(?:^|\})\s*" + re.escape(selector) + r"\s*\{([^}]*)\}", ui.UI_CSS, re.M)
    assert m, f"no rule for {selector}"
    return m.group(1)


def test_the_section_nav_wraps_and_never_clips() -> None:
    """At the 720 px preview the five section links overflowed a hidden-scrollbar strip and the last one
    read "Runwa". The nav wraps instead."""
    block = _rule(".ui-nav")
    assert "flex-wrap: wrap" in block
    assert "overflow" not in block and "scrollbar-width" not in ui.UI_CSS
    assert "::-webkit-scrollbar" not in ui.UI_CSS


def test_a_long_unbroken_token_breaks_rather_than_widening_the_page() -> None:
    """Model-written text (evidence, a rationale, a supplied fact) can carry a 600-character URL. Measured in a
    browser at a phone's width, a page with no wrap rule panned sideways for many screens. The body breaks any
    token anywhere, and the
    header's text column may shrink below its content's width (a grid child's min-width is otherwise auto)."""
    assert "overflow-wrap: anywhere" in _rule("body.ui-body")
    assert "min-width: 0" in _rule(".ui-hero__text")
    assert "--st-neutral-bar" in _rule(":root") and "var(--st-neutral-bar)" in _rule(".ui-ck__bar .u")


def _tokens() -> dict[str, str]:
    """Every `--name: value` the page carries: the brand tokens (`_theme.TOKENS_CSS`), then ours."""
    theme_path = REPO_ROOT / "founder-skills" / "skills" / "financial-model-review" / "scripts" / "_theme.py"
    spec = importlib.util.spec_from_file_location("_theme_for_ui_test", theme_path)
    assert spec is not None and spec.loader is not None
    theme = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(theme)
    out: dict[str, str] = {}
    for css in (theme.TOKENS_CSS, ui.UI_CSS):
        for name, value in re.findall(r"(--[\w-]+):\s*([^;]+);", css):
            out.setdefault(name, value.strip())
    return out


def _hex(token: str, tokens: dict[str, str]) -> str:
    value = tokens[token]
    for _ in range(5):
        m = re.fullmatch(r"var\((--[\w-]+)\)", value)
        if not m:
            break
        value = tokens[m.group(1)]
    assert re.fullmatch(r"#[0-9A-Fa-f]{6}", value), (token, value)
    return value


def _contrast(fg: str, bg: str) -> float:
    def lum(h: str) -> float:
        rgb = [int(h[i : i + 2], 16) / 255 for i in (1, 3, 5)]
        lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
        return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]

    a, b = sorted((lum(fg), lum(bg)), reverse=True)
    return (a + 0.05) / (b + 0.05)


@pytest.mark.parametrize(
    ("fg", "bg"),
    [
        ("--st-warn", "--ui-surface"),
        ("--st-warn", "--st-warn-tint"),
        ("--st-na", "--ui-surface"),
        ("--st-na", "--st-na-tint"),
        ("--st-pass-ink", "--ui-surface"),
        ("--st-pass-ink", "--st-pass-tint"),
        ("--st-fail", "--ui-surface"),
        ("--st-fail", "--st-fail-tint"),
        ("--ui-ink-2", "--ui-surface"),
        ("--ui-ink-2", "--ui-surface-2"),
        ("--ui-on-accent", "--ui-accent"),
    ],
)
def test_status_text_reaches_4_5_to_1(fg: str, bg: str) -> None:
    tokens = _tokens()
    ratio = _contrast(_hex(fg, tokens), _hex(bg, tokens))
    assert ratio >= 4.5, f"{fg} on {bg} is {ratio:.2f}:1"


def test_status_text_and_glyphs_use_the_ink_tokens_and_the_focus_ring_is_visible() -> None:
    tokens = _tokens()
    # The glyphs: white on a solid circle for fail and warn, ink on a tint for pass and not applicable.
    assert "background: var(--st-warn); color: #FFFFFF" in _rule(".ui-st--warn")
    assert "background: var(--st-fail); color: #FFFFFF" in _rule(".ui-st--fail")
    assert _contrast("#FFFFFF", _hex("--st-warn", tokens)) >= 4.5
    assert _contrast("#FFFFFF", _hex("--st-fail", tokens)) >= 4.5
    assert "color: var(--st-pass-ink)" in _rule(".ui-st--pass")
    assert "color: var(--st-pass-ink)" in _rule(".ui-pill--pass")
    assert "color: var(--st-na)" in _rule(".ui-st--na")
    # The brand green stays the fill (bars, ring); only text and glyphs take the darker ink.
    assert tokens["--st-pass"] == "var(--lool-success)"
    # Focus ring: 3:1 against the page and the cards (non-text contrast).
    assert "outline: 2px solid var(--ui-accent)" in _rule(":focus-visible")
    for bg in ("--ui-bg", "--ui-surface"):
        assert _contrast(_hex("--ui-accent", tokens), _hex(bg, tokens)) >= 3.0
    assert "--lool-azure); outline-offset" not in ui.UI_CSS


def test_print_shows_every_criterion_whatever_the_filter() -> None:
    """Filtering is a reading aid: a printout carries the whole list. The rule must come after the
    filter rules and override them."""
    css = ui.UI_CSS
    print_block = css[css.index("@media print") :]
    assert ".ui-ck__groups .ui-ck__grp { display: block !important; }" in print_block
    assert ".ui-ck__groups .ui-ck__item { display: grid !important; }" in print_block
    assert css.index("@media print") > css.index('#ck-f-na:checked ~ .ui-ck__groups .ui-ck__grp:not([data-has~="na"])')


def test_the_css_is_light_only_and_avoids_dark_media() -> None:
    assert "color-scheme: light" in ui.UI_CSS
    assert "prefers-color-scheme" not in ui.UI_CSS


def test_the_script_opens_everything_for_print_and_closes_only_all_pass_groups() -> None:
    js = ui.UI_JS
    assert "beforeprint" in js and "afterprint" in js
    assert "indexOf('fail') < 0 && h.indexOf('warn') < 0" in js


# --- page_shell -----------------------------------------------------------------------------------


def _shell() -> str:
    page: str = ui.page_shell(
        title=f"T {XSS}",
        body_html="<p id='b'>body</p>",
        brand_css="/*BRAND*/",
        page_css="/*PAGE*/",
        head_html="<script>/*HEAD*/</script>\n",
        scripts_html="<script>/*PAGE-JS*/</script>\n",
        skill_name=f"Skill {XSS}",
    )
    return page


def test_the_shell_is_one_document_with_a_viewport_a_language_and_one_main() -> None:
    page = _shell()
    doc = parse(page)
    assert page.startswith("<!DOCTYPE html>")
    (html_el,) = by_tag(doc, "html")
    assert html_el.get("lang") == "en"
    metas = {m.get("name"): m.get("content") for m in by_tag(doc, "meta") if m.has("name")}
    assert (metas["viewport"] or "").startswith("width=device-width")
    assert metas["color-scheme"] == "light"
    assert len(by_tag(doc, "main")) == 1
    assert len(re.findall(r"<head(?:\s[^>]*)?>", page)) == 1


def test_the_shell_escapes_the_title_and_orders_its_parts() -> None:
    page = _shell()
    (title,) = by_tag(parse(page), "title")
    assert title.text() == f"T {XSS}"
    assert "<title>T &lt;script&gt;" in page
    # brand tokens, then the shared CSS, then the page's own; page JS before the shared JS.
    assert page.index("/*BRAND*/") < page.index(":root {\n  --ui-bg") < page.index("/*PAGE*/")
    assert page.index("/*HEAD*/") < page.index("<style>")
    assert page.index("/*PAGE-JS*/") < page.index(ui.UI_JS)
    assert page.index('<footer class="ui-footer"') > page.index("</main>")
    assert ui.UI_CSS in page


def test_the_shell_carries_exactly_one_footer_line_with_the_skill_and_a_feedback_button() -> None:
    doc = parse(_shell())
    (footer,) = by_tag(doc, "footer")
    text = footer.text()
    assert text.startswith(f"Skill {XSS}") and "founder skills by lool ventures" in text
    assert text.endswith("Share feedback")
    links = {a.text(): a for a in footer.iter() if a.tag == "a"}
    assert links["Share feedback"].get("class") == "ui-feedback"
    # The feedback link is the one every page has always carried (`_theme.FOOTER_CREDIT_HTML`).
    theme = (REPO_ROOT / "founder-skills" / "skills" / "deck-review" / "scripts" / "_theme.py").read_text()
    assert f'href="{links["Share feedback"].get("href")}"' in theme
    assert links["founder skills"].get("href") == ui.REPO_URL and links["lool ventures"].get("href") == ui.LOOL_URL


def test_the_feedback_button_is_a_filled_accent_button_with_readable_text_and_a_focus_ring() -> None:
    tokens = _tokens()
    rule = _rule(".ui-footer a.ui-feedback")
    assert "background: var(--ui-accent); color: var(--ui-on-accent)" in rule
    assert "border-radius: var(--r-pill)" in rule
    assert _contrast(_hex("--ui-on-accent", tokens), _hex("--ui-accent", tokens)) >= 4.5
    assert "color: var(--ui-on-accent)" in _rule(".ui-footer a.ui-feedback:hover")
    assert _contrast(_hex("--ui-on-accent", tokens), _hex("--lool-blue-deep", tokens)) >= 4.5
    focus = _rule(".ui-footer a.ui-feedback:focus-visible")
    assert "outline: 2px solid var(--ui-accent)" in focus
    assert _contrast(_hex("--ui-accent", tokens), _hex("--ui-bg", tokens)) >= 3.0


def test_a_figure_cut_on_a_phone_shows_that_it_scrolls() -> None:
    """The platform scrollbar is invisible until touched on macOS and iOS, so a chart or table wider
    than the screen gets a shadow on the side that scrolls, drawn by the background alone: two covers
    that scroll with the content ("local") over two shadows that stay put ("scroll")."""
    blocks = re.findall(r"(?:^|\})\s*\.ui-table-wrap, \.ui-scroll\s*\{([^}]*)\}", ui.UI_CSS, re.M)
    assert any("overflow-x: auto" in b for b in blocks)
    shadow = [b for b in blocks if "background:" in b]
    assert len(shadow) == 1 and shadow[0].count("no-repeat local") == 2 and shadow[0].count("no-repeat scroll") == 2
    # At rest (nothing to scroll) each cover's solid part must hide its shadow whole, or a faint shade
    # shows at the edge of every figure that fits.
    cover = re.search(r"var\(--ui-surface\) (\d+)%[^/]*/ (\d+)px 100% no-repeat local", shadow[0])
    shade = re.search(r"/ (\d+)px 100% no-repeat scroll", shadow[0])
    assert cover and shade
    assert int(cover.group(1)) / 100 * int(cover.group(2)) >= int(shade.group(1))


def test_a_decimal_score_fits_the_phone_ring() -> None:
    """A score with a decimal is up to five characters with its sign; on a phone the dial is 76 px, so the number
    sits under 1rem there or it touches the stroke (seen at 390 px)."""
    phone = ui.UI_CSS[ui.UI_CSS.index("@media (max-width: 640px)") :]
    m = re.search(r"\.ui-ring__num \{ font-size: ([\d.]+)rem", phone)
    assert m and float(m.group(1)) < 1.0, m
    assert ".ui-ring__dial { width: 76px" in phone


def test_a_score_prints_as_the_artifact_carries_it() -> None:
    assert [ui.score_text(v) for v in (68.2, 21, 21.0, 95.6, 100.0, 0, 41.25)] == [
        "68.2",
        "21",
        "21",
        "95.6",
        "100",
        "0",
        "41.2",
    ]
    # A skill whose report prints whole numbers asks for them, so its ring says what its report says.
    assert [ui.score_text(v, decimals=0) for v in (20.6, 95.9, 21.0, 100)] == ["21", "96", "21", "100"]


# --- header_card ----------------------------------------------------------------------------------


def test_the_header_card_escapes_its_strings_and_keeps_trusted_markup() -> None:
    out = ui.header_card(
        eyebrow=XSS,
        title=XSS,
        meta_html='<span class="ui-chip">Seed</span>',
        verdict_html="<b>v</b>",
        body_html="<p id='n'>note</p>",
        ring_html="<figure id='r'></figure>",
    )
    doc = parse(out)
    assert "<script>" not in out
    (h1,) = by_tag(doc, "h1")
    assert h1.text() == XSS
    assert out.startswith('<header class="ui-hero"')
    assert not re.search(r"<head(?:\s[^>]*)?>", out), "the stamp regex must not mistake the card for <head>"
    for frag in ('<span class="ui-chip">Seed</span>', "<b>v</b>", "<p id='n'>note</p>", "<figure id='r'>"):
        assert frag in out
    # The verdict is findable by meaning (pages' tests read it by `data-verdict`, never by class).
    (verdict,) = by_attr(doc, "data-verdict")
    assert verdict.tag == "p" and verdict.text() == "v"


def test_an_empty_header_card_slot_renders_nothing() -> None:
    out = ui.header_card(eyebrow="E", title="T")
    for cls in ("ui-hero__meta", "ui-hero__verdict", "ui-hero__body"):
        assert cls not in out


# --- score_ring -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("pct", "dash"),
    [(0, "0 100"), (50, "50 100"), (100, "100 100"), (150, "100 100"), (-5, "0 100"), (62.5, "62.5 100")],
)
def test_the_ring_arc_follows_the_score_clamped(pct: float, dash: str) -> None:
    out = ui.score_ring(pct, tone="warn", value_text="x", label="L", aria_label="a")
    assert f'stroke-dasharray="{dash}"' in out
    assert 'pathLength="100"' in out


def test_a_ring_with_no_score_draws_only_the_track() -> None:
    out = ui.score_ring(None, tone="neutral", value_text="—", label="L", aria_label="no score")
    assert "ui-ring__value" not in out and "ui-ring__track" in out


def test_the_ring_says_its_label_and_links_where_asked() -> None:
    out = ui.score_ring(
        96, tone="pass", value_text="96%", label=XSS, caption="Strong", aria_label=f"say {XSS}", href="#checklist"
    )
    doc = parse(out)
    (fig,) = [e for e in doc.iter() if e.get("role") == "img"]
    assert fig.get("aria-label") == f"say {XSS}"
    assert "ui-ring--pass" in (fig.get("class") or "")
    # The tone is read by meaning too, so a page's tests never read it from a class name.
    assert fig.get("data-tone") == "pass"
    (a,) = by_tag(doc, "a")
    assert a.get("href") == "#checklist"
    assert "<script>" not in out
    assert "Strong" in doc.text()


def test_an_unknown_ring_tone_raises() -> None:
    with pytest.raises(ValueError):
        ui.score_ring(50, tone="green", value_text="x", label="L", aria_label="a")


# --- checklist ------------------------------------------------------------------------------------


def _groups() -> list[dict[str, object]]:
    return [
        {
            "name": f"Cash {XSS}",
            "count_text": "1/3 (33%)",
            "items": [
                {"tone": "fail", "title": f"Title {XSS}", "criterion": "C_1", "evidence": f"Ev {XSS}"},
                {"tone": "warn", "title": "W", "criterion": "C_2", "evidence_html": "<em>trusted</em>"},
                {"tone": "pass", "title": "P", "criterion": "C_3", "evidence": ""},
                {"tone": "na", "title": "N", "criterion": "C_4"},
            ],
        },
        {
            "name": "All good",
            "count_text": "2/2 (100%)",
            "items": [
                {"tone": "pass", "title": "P2", "criterion": "C_5", "evidence": "fine"},
                {"tone": "pass", "title": "P3", "criterion": "C_6", "evidence": "fine"},
            ],
        },
        {"name": "Empty", "count_text": "", "items": []},
    ]


def test_the_checklist_lists_every_item_once_with_its_status() -> None:
    doc = parse(ui.checklist(_groups()))
    rows = by_attr(doc, "data-criterion")
    assert [(r.get("data-criterion"), r.get("data-status")) for r in rows] == [
        ("C_1", "fail"),
        ("C_2", "warn"),
        ("C_3", "pass"),
        ("C_4", "na"),
        ("C_5", "pass"),
        ("C_6", "pass"),
    ]


def test_every_group_is_open_and_names_what_it_holds() -> None:
    doc = parse(ui.checklist(_groups()))
    groups = by_tag(doc, "details")
    assert [g.get("data-has") for g in groups] == ["fail warn pass na", "pass"], "an empty group is not drawn"
    assert all(g.has("open") for g in groups)
    for g in groups:
        assert g.children and getattr(g.children[0], "tag", None) == "summary"


def test_the_checklist_escapes_plain_text_and_keeps_trusted_evidence() -> None:
    out = ui.checklist(_groups())
    assert "<script>" not in out
    assert "&lt;script&gt;" in out
    assert "<em>trusted</em>" in out
    doc = parse(out)
    c1 = by_attr(doc, "data-criterion", "C_1")[0]
    assert f"Title {XSS}" in c1.text() and f"Ev {XSS}" in c1.text()
    # a pass with no evidence renders its title alone
    c3 = by_attr(doc, "data-criterion", "C_3")[0]
    assert c3.text().endswith("P") and "ui-ck__ev" not in str([e.attrs for e in c3.iter()])


def test_the_chips_count_and_the_all_chip_starts_checked() -> None:
    doc = parse(ui.checklist(_groups()))
    radios = [e for e in by_tag(doc, "input") if e.get("name") == "ck-f"]
    assert [r.get("id") for r in radios] == ["ck-f-all", "ck-f-attn", "ck-f-fail", "ck-f-warn", "ck-f-pass", "ck-f-na"]
    assert [r.has("checked") for r in radios] == [True] + [False] * 5
    chips = {e.get("for"): e for e in by_tag(doc, "label")}
    counts = {k: chips[k].text() for k in chips}
    assert counts == {
        "ck-f-all": "All 6",
        "ck-f-attn": "Needs attention 2",
        "ck-f-fail": "Fail 1",
        "ck-f-warn": "Warn 1",
        "ck-f-pass": "Pass 3",
        "ck-f-na": "Not applicable 1",
    }


def test_a_zero_count_chip_is_marked_empty_and_labels_can_be_renamed() -> None:
    groups = [{"name": "G", "count_text": "", "items": [{"tone": "pass", "title": "P", "criterion": "X"}]}]
    out = ui.checklist(groups, labels={"na": "N/A"})
    doc = parse(out)
    chips = {e.get("for"): e for e in by_tag(doc, "label")}
    assert chips["ck-f-fail"].get("class") == "is-empty"
    assert chips["ck-f-pass"].get("class") is None
    assert chips["ck-f-na"].text() == "N/A 0"


def test_the_radios_precede_the_chips_and_the_groups() -> None:
    """The CSS filter is `#radio:checked ~ sibling`, so the order is the contract."""
    out = ui.checklist(_groups())
    last_radio = out.rindex('class="ui-ck__r"')
    assert last_radio < out.index('class="ui-ck__chips"') < out.index('class="ui-ck__groups"')


def test_an_unknown_item_tone_raises_rather_than_rendering_blank() -> None:
    with pytest.raises(ValueError):
        ui.checklist([{"name": "G", "items": [{"tone": "not_applicable", "title": "x"}]}])


def test_the_summary_slot_and_the_glyphs_say_the_status() -> None:
    doc = parse(ui.checklist(_groups(), summary_html="<b id='sum'>3 pass</b>"))
    assert any(e.get("id") == "sum" for e in doc.iter())
    glyphs = [e.get("aria-label") for e in doc.iter() if e.get("role") == "img"]
    assert glyphs == ["Fail", "Warn", "Pass", "Not applicable", "Pass", "Pass"]


def test_a_skill_with_no_warn_status_gets_no_warn_or_attention_chip() -> None:
    groups = [
        {
            "name": "G",
            "count_text": "",
            "items": [
                {"tone": "fail", "title": "F", "criterion": "A"},
                {"tone": "pass", "title": "P", "criterion": "B"},
                {"tone": "na", "title": "N", "criterion": "C"},
            ],
        }
    ]
    doc = parse(ui.checklist(groups, statuses=("fail", "pass", "na")))
    radios = [e.get("id") for e in by_tag(doc, "input") if e.get("name") == "ck-f"]
    assert radios == ["ck-f-all", "ck-f-fail", "ck-f-pass", "ck-f-na"]
    assert {e.get("for") for e in by_tag(doc, "label")} == set(radios)
    with pytest.raises(ValueError):
        ui.checklist(groups, statuses=("fail", "not_applicable"))


# sha256 of `checklist()` output for `_groups()` as the module rendered it before the `neutral` tone and
# `status_label` existed: default statuses, a skill with no warn, and renamed labels with a summary. A page
# that names neither must get exactly that markup, so the pages already on the shell are untouched.
_FROZEN_FOUR_TONE = {
    "default": "92593121edb80a3fba443d96a8b62214fd269f6c814eee928655eb1ce90227dd",
    "no_warn": "5ed3bcbaeb9fbca242e0f8148329a1c5375ae65728aa29cbdf480a9dcae760b2",
    "labels_summary": "ab3f55acfab9d9e6224f139917e2f3d8d73d492456471f708f5e4d6b285f5bd7",
}


def test_a_page_that_names_no_new_status_gets_the_four_tone_markup_unchanged() -> None:
    import hashlib

    assert ui.DEFAULT_STATUSES == ("fail", "warn", "pass", "na")
    outs = {
        "default": ui.checklist(_groups()),
        "no_warn": ui.checklist(_groups(), statuses=("fail", "pass", "na")),
        "labels_summary": ui.checklist(_groups(), labels={"na": "N/A"}, summary_html="<b>s</b>"),
    }
    assert {k: hashlib.sha256(v.encode()).hexdigest() for k, v in outs.items()} == _FROZEN_FOUR_TONE
    assert "ck-f-neutral" not in outs["default"] and "data-status-word" not in outs["default"]


def _neutral_groups() -> list[dict[str, object]]:
    return [
        {
            "name": "Team",
            "count_text": "",
            "items": [
                {"tone": "neutral", "title": "M", "criterion": "N_1", "status_label": "Moderate", "evidence": "e"},
                {"tone": "fail", "title": "D", "criterion": "N_2", "status_label": f"Dealbreaker {XSS}"},
                {"tone": "pass", "title": "S", "criterion": "N_3"},
            ],
        }
    ]


def test_the_neutral_tone_renders_its_glyph_bar_and_chip_when_a_page_names_it() -> None:
    out = ui.checklist(_neutral_groups(), statuses=("fail", "warn", "neutral", "pass", "na"))
    doc = parse(out)
    radios = [e.get("id") for e in by_tag(doc, "input") if e.get("name") == "ck-f"]
    assert radios == ["ck-f-all", "ck-f-attn", "ck-f-fail", "ck-f-warn", "ck-f-neutral", "ck-f-pass", "ck-f-na"]
    chips = {e.get("for"): e.text() for e in by_tag(doc, "label")}
    assert chips["ck-f-neutral"] == "Neutral 1" and chips["ck-f-attn"] == "Needs attention 1"
    (row,) = by_attr(doc, "data-criterion", "N_1")
    assert row.get("data-status") == "neutral"
    assert 'class="ui-st ui-st--neutral"' in out and "•" in out
    (grp,) = by_tag(doc, "details")
    assert grp.get("data-has") == "fail pass neutral"
    assert '<i class="u" style="--n:1"></i>' in out
    for rule in (".ui-st--neutral", ".ui-pill--neutral", ".ui-ck__bar .u", ".ui-ck__word"):
        assert rule in ui.UI_CSS, rule
    # Named but absent from the statuses, it still raises nothing: the tone is known, only the chip is not
    # offered. An unknown tone still raises.
    assert "ck-f-neutral" not in ui.checklist(_neutral_groups())
    with pytest.raises(ValueError):
        ui.checklist([{"name": "G", "items": [{"tone": "moderate", "title": "x"}]}])


def test_a_status_label_is_what_the_glyph_says_and_is_shown_after_the_title() -> None:
    doc = parse(ui.checklist(_neutral_groups(), statuses=("fail", "warn", "neutral", "pass", "na")))
    (row,) = by_attr(doc, "data-criterion", "N_1")
    assert row.get("data-status-word") == "Moderate"
    (glyph,) = [e for e in row.iter() if e.get("role") == "img"]
    assert glyph.get("aria-label") == "Moderate"
    assert "M" in row.text() and "Moderate" in row.text()
    (dealbreaker,) = by_attr(doc, "data-criterion", "N_2")
    assert dealbreaker.get("data-status-word") == f"Dealbreaker {XSS}"
    out = ui.checklist(_neutral_groups(), statuses=("fail", "warn", "neutral", "pass", "na"))
    assert "<script>" not in out
    # The visible word repeats the glyph's name, so it is hidden from a screen reader: the row says it once.
    (word,) = [e for e in row.iter() if e.text() == "Moderate" and e.get("role") != "img"]
    assert word.get("aria-hidden") == "true"
    spoken = [e.get("aria-label") for e in row.iter() if e.get("role") == "img"]
    spoken += [
        e.text()
        for e in row.iter()
        if e.text() == "Moderate" and not any(a.get("aria-hidden") for a in [e, *e.ancestors()])
    ]
    assert spoken == ["Moderate"], spoken
    # A row without a word keeps the tone's name.
    (plain,) = by_attr(doc, "data-criterion", "N_3")
    assert not plain.has("data-status-word")
    assert [e.get("aria-label") for e in plain.iter() if e.get("role") == "img"] == ["Pass"]


def test_founder_text_leaves_a_kept_token_as_written() -> None:
    assert ui.founder_text("the widget_count rose") == "the widget count rose"
    assert ui.founder_text("the widget_count rose", frozenset({"widget_count"})) == "the widget_count rose"
    assert ui.founder_text("the widget_count rose", frozenset()) == "the widget count rose"


def test_a_weightless_item_is_listed_but_never_counted() -> None:
    """A criterion that mirrors another is shown once, muted, and counted only where it is owned."""
    groups = [
        {
            "name": "G",
            "count_text": "",
            "items": [
                {"tone": "warn", "title": "Owner", "criterion": "OWN"},
                {
                    "tone": "warn",
                    "title": "Mirror",
                    "criterion": "DUP",
                    "weightless": True,
                    "evidence": "Counts under Owner",
                },
                {"tone": "pass", "title": "P", "criterion": "P1"},
            ],
        }
    ]
    doc = parse(ui.checklist(groups))
    (dup,) = by_attr(doc, "data-criterion", "DUP")
    assert dup.get("data-weight") == "0" and dup.get("data-status") == "warn"
    assert "Counts under Owner" in dup.text()
    (own,) = by_attr(doc, "data-criterion", "OWN")
    assert not own.has("data-weight")
    chips = {e.get("for"): e.text() for e in by_tag(doc, "label")}
    # Warn counts only the owned row; All counts every row it shows, the weightless one included.
    assert chips["ck-f-warn"] == "Warn 1" and chips["ck-f-all"] == "All 3"
    (grp,) = by_tag(doc, "details")
    assert grp.get("data-has") == "warn pass"
    bars = [e for e in grp.iter() if e.tag == "i"]
    assert [b.get("style") for b in bars] == ["--n:1", "--n:1"]
    assert '.ui-ck__item[data-weight="0"]' in ui.UI_CSS
    # A filter other than All hides it, so a chip's count is what the filter shows.
    assert '.ui-ck__r:not(#ck-f-all):checked ~ .ui-ck__groups .ui-ck__item[data-weight="0"]' in ui.UI_CSS
    # A group holding only a weightless problem says nothing about problems (it neither opens nor
    # answers the Fail / Warn filters for it).
    mirror = {"tone": "warn", "title": "Mirror", "criterion": "DUP", "weightless": True}
    only = [{"name": "H", "count_text": "", "items": [mirror, {"tone": "pass", "title": "P", "criterion": "P1"}]}]
    (grp2,) = by_tag(parse(ui.checklist(only)), "details")
    assert grp2.get("data-has") == "pass"


@pytest.mark.parametrize(
    ("token", "label"),
    [
        ("seed", "Seed"),
        ("pre_seed", "Pre-seed"),
        ("pre-seed", "Pre-seed"),
        ("series_a", "Series A"),
        ("series-b", "Series B"),
        ("Series C", "Series C"),
        ("growth", "Growth"),
        ("later", "Later"),
        ("", ""),
        (None, ""),
    ],
)
def test_a_stage_token_reads_as_words(token: object, label: str) -> None:
    assert ui.stage_label(token) == label


def test_the_founder_text_policy_rewrites_and_leaves_clean_text_alone() -> None:
    import sys

    before = list(sys.path)
    assert ui.founder_text("the moat_count is high") == "the moat count is high"
    assert ui.founder_text("Plain sentence, nothing to fix.") == "Plain sentence, nothing to fix."
    assert ui.founder_text("") == ""
    assert sys.path == before, "loading the policy must not change the import path"


@pytest.mark.parametrize("where", ["skill-copy", "flat-mount"])
def test_the_founder_text_policy_is_found_from_a_copy_and_degrades_without_one(tmp_path: Path, where: str) -> None:
    """A skill's copy finds the plugin-root policy three levels up; with no plugin root (the flat mount)
    it returns the text as written rather than failing the page."""
    if where == "skill-copy":
        scripts = tmp_path / "plugin" / "skills" / "s" / "scripts"
        (tmp_path / "plugin" / "scripts").mkdir(parents=True)
        (tmp_path / "plugin" / "scripts" / "_founder_text.py").write_bytes(
            (REPO_ROOT / "founder-skills" / "scripts" / "_founder_text.py").read_bytes()
        )
    else:
        scripts = tmp_path / "mnt" / "skills" / "plugin-s"
    scripts.mkdir(parents=True)
    (scripts / "_ui.py").write_bytes(_UI_PATH.read_bytes())
    spec = importlib.util.spec_from_file_location(f"_ui_copy_{where.replace('-', '_')}", scripts / "_ui.py")
    assert spec is not None and spec.loader is not None
    copy = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(copy)
    out = copy.founder_text("the switching_costs score")
    if where == "skill-copy":
        assert out == "the switching costs score"
        assert copy.founder_text_policy() is not None
    else:
        assert out == "the switching_costs score"
        assert copy.founder_text_policy() is None
