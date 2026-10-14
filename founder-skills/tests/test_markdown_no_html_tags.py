"""No plugin markdown file may carry a bare placeholder that a markdown renderer reads as an HTML tag.

A placeholder written `<B>` outside code is an unclosed bold tag to GitHub's renderer: everything after it
renders bold, and `<A>` / `<source>` vanish. The model reads the raw text, so nothing behaves differently;
the file only reads wrongly to a person. Write placeholders inside backticks, or as `[name]`.
"""

from __future__ import annotations

import re
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1]

# Every HTML element name a renderer would honour, lower-cased. A placeholder such as `<company>` or
# `<RUN_ID>` is not one, so it is left alone.
HTML_TAGS = frozenset(
    [
        "a",
        "abbr",
        "article",
        "aside",
        "audio",
        "b",
        "bdi",
        "bdo",
        "big",
        "blockquote",
        "body",
        "br",
        "button",
        "canvas",
        "caption",
        "center",
        "cite",
        "code",
        "col",
        "colgroup",
        "data",
        "datalist",
        "dd",
        "del",
        "details",
        "dfn",
        "dialog",
        "div",
        "dl",
        "dt",
        "em",
        "embed",
        "fieldset",
        "figcaption",
        "figure",
        "font",
        "footer",
        "form",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "head",
        "header",
        "hr",
        "html",
        "i",
        "iframe",
        "img",
        "input",
        "ins",
        "kbd",
        "label",
        "legend",
        "li",
        "link",
        "main",
        "map",
        "mark",
        "menu",
        "meta",
        "meter",
        "nav",
        "object",
        "ol",
        "optgroup",
        "option",
        "output",
        "p",
        "picture",
        "pre",
        "progress",
        "q",
        "rp",
        "rt",
        "ruby",
        "s",
        "samp",
        "script",
        "section",
        "select",
        "slot",
        "small",
        "source",
        "span",
        "strong",
        "style",
        "sub",
        "summary",
        "sup",
        "table",
        "tbody",
        "td",
        "template",
        "textarea",
        "tfoot",
        "th",
        "thead",
        "time",
        "title",
        "tr",
        "track",
        "tt",
        "u",
        "ul",
        "var",
        "video",
        "wbr",
    ]
)

_FENCE = re.compile(r"^\s*(```|~~~)")
_INLINE_CODE = re.compile(r"`[^`]*`", re.S)
_TAG = re.compile(r"<(/?)([A-Za-z][A-Za-z0-9-]*)(\s[^<>]*)?>")
_COMMENT = re.compile(r"<!--.*?-->", re.S)


def html_tags_outside_code(text: str) -> list[str]:
    """Each HTML-element-looking tag in `text` outside fenced blocks, inline code and comments."""
    prose, in_fence = [], False
    for line in text.split("\n"):
        if _FENCE.match(line):
            in_fence = not in_fence
            prose.append("")
            continue
        prose.append("" if in_fence else line)
    body = _COMMENT.sub("", _INLINE_CODE.sub("", "\n".join(prose)))
    return [m.group(0) for m in _TAG.finditer(body) if m.group(2).lower() in HTML_TAGS]


def test_the_scan_finds_a_bare_bold_placeholder() -> None:
    assert html_tags_outside_code("found that <A> and <B> merged, per <source>") == ["<A>", "<B>", "<source>"]
    assert html_tags_outside_code("run `--code <code>` and <RUN_ID>, <!-- <b> -->\n```\n<b>\n```") == []


def test_no_plugin_markdown_carries_an_html_tag_placeholder() -> None:
    found = []
    for path in sorted(PLUGIN.rglob("*.md")):
        if "tests" in path.relative_to(PLUGIN).parts:
            continue
        for tag in html_tags_outside_code(path.read_text(encoding="utf-8")):
            found.append(f"{path.relative_to(PLUGIN)}: {tag}")
    assert not found, "write these placeholders in backticks or as [name]:\n" + "\n".join(found)
