"""Compare-time host/path remapping (ticket 122).

The crawler stores artifacts truthfully — each side is crawled as-is. To compare
"the same site on two hosts" (``dev.domain.com`` vs ``domain.com``, a local
build vs production), differences that are purely host-derived have to be
neutralised at *compare* time, not baked into the crawl. :class:`Remap` holds an
ordered list of literal ``FROM=TO`` replacements applied to text and URLs before
they are diffed, and re-hashes remapped page text so a staging banner or a host
mentioned in visible copy stops breaking the sha256/simhash equality checks.

Replacements are **literal strings, applied in order** — no regex in v1 (the
constraint is deliberate; a regex mode can be a follow-up flag).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .hashing import (
    normalize_html_for_hashing,
    sha256_of_normalized,
    simhash64_of_normalized,
)


@dataclass(slots=True)
class Remap:
    """An ordered list of literal ``(from, to)`` string replacements."""

    replacements: list[tuple[str, str]] = field(default_factory=list)

    @classmethod
    def from_specs(cls, specs: list[str] | None) -> "Remap":
        """Parse ``FROM=TO`` specs (as passed to repeated ``--replace`` flags).

        Fails fast on a malformed spec — an empty ``FROM`` would match nothing
        (or, for ``str.replace``, everywhere), so it is rejected rather than
        silently ignored. Splits on the first ``=`` only, so a ``TO`` may itself
        contain ``=``.
        """
        replacements: list[tuple[str, str]] = []
        for spec in specs or []:
            if "=" not in spec:
                raise ValueError(f"Invalid --replace spec (expected FROM=TO): {spec!r}")
            frm, to = spec.split("=", 1)
            if not frm:
                raise ValueError(f"Invalid --replace spec (empty FROM): {spec!r}")
            replacements.append((frm, to))
        return cls(replacements)

    def __bool__(self) -> bool:
        return bool(self.replacements)

    def apply_to_text(self, text: str | None) -> str | None:
        if text is None:
            return None
        for frm, to in self.replacements:
            text = text.replace(frm, to)
        return text

    # URLs are literal strings too; a separate name keeps call sites readable
    # and leaves room for URL-aware normalization if v2 ever needs it.
    apply_to_url = apply_to_text

    def rehash(self, *, raw_html: str | None, text: str | None) -> tuple[str | None, int | None]:
        """Recompute ``(sha256, simhash64)`` from remapped page content.

        Prefers ``raw_html`` (normalized the same way the crawler hashes it) and
        falls back to already-extracted ``text``. Stored hashes were computed
        *without* replacements, so they cannot be reused once a remap is in play
        — this recomputes them. Returns ``(None, None)`` when there is nothing to
        hash.
        """
        if raw_html is not None:
            normalized = normalize_html_for_hashing(raw_html)
        elif text and text.strip():
            normalized = " ".join(text.split())
        else:
            # Nothing to re-hash (e.g. a store-loaded row carries no raw_html and
            # an empty extracted text) — signal the caller to keep stored hashes.
            return None, None
        normalized = self.apply_to_text(normalized) or ""
        return sha256_of_normalized(normalized), simhash64_of_normalized(normalized)
