"""A small stdlib DOM for asserting on generated HTML pages by meaning, not by class name.

Page tests read elements by `id`, by `data-*` attribute, by tag and by text. Class names are
presentation: an assert whose only target is a shared UI class belongs in `test_ui.py`, so a restyle
cannot break a test that checks a fact. Script and style bodies are kept as raw text inside their
element and never parsed as markup.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from html.parser import HTMLParser

_VOID = frozenset(
    {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
)


class Element:
    def __init__(self, tag: str, attrs: dict[str, str], parent: Element | None) -> None:
        self.tag = tag
        self.attrs = attrs
        self.parent = parent
        self.children: list[Element | str] = []

    def get(self, name: str, default: str | None = None) -> str | None:
        return self.attrs.get(name, default)

    def has(self, name: str) -> bool:
        return name in self.attrs

    def iter(self) -> Iterator[Element]:
        """This element and every element below it, in document order."""
        yield self
        for c in self.children:
            if isinstance(c, Element):
                yield from c.iter()

    def text(self) -> str:
        """The element's text, whitespace squashed (script and style bodies included)."""
        parts: list[str] = []

        def walk(e: Element) -> None:
            for c in e.children:
                if isinstance(c, str):
                    parts.append(c)
                else:
                    walk(c)

        walk(self)
        return " ".join("".join(parts).split())

    def find_all(self, pred: Callable[[Element], bool]) -> list[Element]:
        return [e for e in self.iter() if pred(e)]

    def ancestors(self) -> Iterator[Element]:
        p = self.parent
        while p is not None:
            yield p
            p = p.parent

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<{self.tag} {self.attrs}>"


class _Builder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Element("#document", {}, None)
        self.cur = self.root

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        el = Element(tag, {k: (v if v is not None else "") for k, v in attrs}, self.cur)
        self.cur.children.append(el)
        if tag not in _VOID:
            self.cur = el

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        el = Element(tag, {k: (v if v is not None else "") for k, v in attrs}, self.cur)
        self.cur.children.append(el)

    def handle_endtag(self, tag: str) -> None:
        node: Element | None = self.cur
        while node is not None and node.tag != tag:
            node = node.parent
        if node is not None and node.parent is not None:
            self.cur = node.parent

    def handle_data(self, data: str) -> None:
        self.cur.children.append(data)


def parse(html: str) -> Element:
    b = _Builder()
    b.feed(html)
    b.close()
    return b.root


def by_id(doc: Element, element_id: str) -> Element | None:
    found = doc.find_all(lambda e: e.get("id") == element_id)
    assert len(found) <= 1, f"id {element_id!r} appears {len(found)} times"
    return found[0] if found else None


def by_attr(doc: Element, name: str, value: str | None = None) -> list[Element]:
    """Elements carrying attribute `name` (with exactly `value`, when given)."""
    return doc.find_all(lambda e: e.has(name) and (value is None or e.get(name) == value))


def by_tag(doc: Element, tag: str) -> list[Element]:
    return doc.find_all(lambda e: e.tag == tag)


def visible_text(doc: Element) -> str:
    """Text a reader sees: every text node outside script and style, whitespace squashed."""
    parts: list[str] = []

    def walk(e: Element) -> None:
        if e.tag in ("script", "style"):
            return
        for c in e.children:
            if isinstance(c, str):
                parts.append(c)
            else:
                walk(c)

    walk(doc)
    return " ".join(" ".join(parts).split())
