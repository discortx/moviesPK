"""Terms-page fingerprint shared by ``scripts/snapshot_evidence.py`` (P0-07) and the canary
(P2-03): the SHA-256 of the page's visible text, normalized, so markup, script and
whitespace changes do not count as a terms change. No copy of the page is stored."""

from __future__ import annotations

from selectolax.lexbor import LexborHTMLParser

from .robots import normalized_text_sha256


def html_text(html: str) -> str:
    """Visible text of an HTML page (scripts and styles removed)."""
    tree = LexborHTMLParser(html)
    for node in tree.css("script, style, noscript, template"):
        node.decompose()
    root = tree.body or tree.root
    return root.text(separator="\n") if root is not None else ""


def terms_sha256(html: str) -> str:
    return normalized_text_sha256(html_text(html))
