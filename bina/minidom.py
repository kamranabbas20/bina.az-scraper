"""A very small HTML tree, built on the stdlib ``html.parser``.

The project has no third-party dependencies, so this stands in for the little
bit of BeautifulSoup that the parsers actually need: walk a document, find
elements by tag/class, read attributes, and collect visible text.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Iterator, Optional

# Elements that never have a closing tag.
VOID_TAGS = frozenset(
    """area base br col embed hr img input link meta param source track wbr""".split()
)

# Subtrees whose text is never visible content.
NON_TEXT_TAGS = frozenset({"script", "style", "template", "noscript"})

_WS = re.compile(r"\s+")


class Node:
    """One element (or the synthetic document root)."""

    __slots__ = ("tag", "attrs", "children", "parent")

    def __init__(self, tag: str, attrs: Optional[dict] = None, parent: "Node | None" = None):
        self.tag = tag
        self.attrs = attrs or {}
        self.children: list = []  # Node | str, in document order
        self.parent = parent

    # -- attributes ------------------------------------------------------

    def get(self, name: str, default=None):
        return self.attrs.get(name, default)

    @property
    def classes(self) -> frozenset:
        return frozenset((self.attrs.get("class") or "").split())

    def has_class(self, name: str) -> bool:
        return name in self.classes

    def class_contains(self, fragment: str) -> bool:
        """True if any class token contains ``fragment``.

        Sites rename classes (``card_params-price`` -> ``product-price``), so
        matching on a fragment survives more redesigns than an exact match.
        """
        return any(fragment in token for token in self.classes)

    # -- traversal -------------------------------------------------------

    def elements(self) -> Iterator["Node"]:
        """Every descendant element, in document order."""
        for child in self.children:
            if isinstance(child, Node):
                yield child
                yield from child.elements()

    def ancestors(self) -> Iterator["Node"]:
        node = self.parent
        while node is not None:
            yield node
            node = node.parent

    def find_all(
        self,
        tag: Optional[str] = None,
        cls: Optional[str] = None,
        cls_contains: Optional[str] = None,
        has_attr: Optional[str] = None,
    ) -> list["Node"]:
        out = []
        for node in self.elements():
            if tag is not None and node.tag != tag:
                continue
            if cls is not None and not node.has_class(cls):
                continue
            if cls_contains is not None and not node.class_contains(cls_contains):
                continue
            if has_attr is not None and has_attr not in node.attrs:
                continue
            out.append(node)
        return out

    def find(self, **kwargs) -> "Node | None":
        found = self.find_all(**kwargs)
        return found[0] if found else None

    # -- text ------------------------------------------------------------

    def text(self, sep: str = " ") -> str:
        """Visible text of this subtree, whitespace-collapsed."""
        parts: list[str] = []

        def walk(node: "Node") -> None:
            for child in node.children:
                if isinstance(child, str):
                    piece = _WS.sub(" ", child).strip()
                    if piece:
                        parts.append(piece)
                elif child.tag not in NON_TEXT_TAGS:
                    walk(child)

        walk(self)
        return sep.join(parts)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        cls = " ".join(sorted(self.classes))
        return f"<Node {self.tag}{' .' + cls if cls else ''}>"


class _TreeBuilder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Node("[document]")
        self._stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = Node(tag, dict(attrs), self._stack[-1])
        self._stack[-1].children.append(node)
        if tag not in VOID_TAGS:
            self._stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self._stack[-1].children.append(Node(tag, dict(attrs), self._stack[-1]))

    def handle_endtag(self, tag):
        # Close the nearest open element with this tag; drop anything left
        # open inside it. Unmatched end tags are ignored, which is what
        # browsers do and what real-world markup needs.
        for index in range(len(self._stack) - 1, 0, -1):
            if self._stack[index].tag == tag:
                del self._stack[index:]
                return

    def handle_data(self, data):
        self._stack[-1].children.append(data)


def parse_html(markup: str) -> Node:
    """Parse ``markup`` into a :class:`Node` tree rooted at the document."""
    builder = _TreeBuilder()
    builder.feed(markup)
    builder.close()
    return builder.root
