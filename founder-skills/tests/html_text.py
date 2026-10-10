"""The text of a generated HTML page with its <script> and <style> bodies left out.

Tests read a page's founder-visible text this way. It uses the standard library's HTML parser, which
handles tag case, attributes and odd spacing in an end tag, rather than a regular expression over the
markup.
"""

from __future__ import annotations

from html.parser import HTMLParser

_SKIPPED = frozenset({"script", "style"})


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIPPED:
            self._depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIPPED and self._depth:
            self._depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._depth:
            self.parts.append(data)


def visible_text(html: str, sep: str = " ") -> str:
    """The page's text outside <script> and <style>, pieces joined by `sep`. Tags themselves are dropped."""
    parser = _Text()
    parser.feed(html)
    parser.close()
    return sep.join(parser.parts)
