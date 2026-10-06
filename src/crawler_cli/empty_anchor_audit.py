"""Pure, bounded evidence for Q91 empty internal anchors.

Normal crawl link extraction has historically represented an image link using
synthetic anchor text.  That is useful for discovery, but it cannot distinguish
an image with a meaningful ``alt`` from an image whose alternative text was
never retained.  This evaluator therefore accepts those facts explicitly and
keeps the latter state unknown rather than treating it as a passing link.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class EmptyAnchorFinding:
    """One confirmed Q91 finding, with only saved-link evidence."""

    source_url: str
    target_url: str
    xpath: str | None
    anchor_text: str | None
    linked_image_alt_texts: tuple[str | None, ...]

    def as_dict(self) -> dict[str, object]:
        """Return a JSON-safe evidence row."""

        return asdict(self)


@dataclass(frozen=True)
class EmptyAnchorCoverage:
    """Coverage needed to interpret an empty-anchor result safely.

    ``unknown_image_alt_count`` is deliberately separate from findings: when
    image-alt evidence was not retained, an empty anchor is neither known good
    nor a confirmed Q91 defect.
    """

    input_record_count: int
    valid_record_count: int
    invalid_record_count: int
    empty_anchor_count: int
    empty_anchor_with_meaningful_image_alt_count: int
    empty_anchor_without_meaningful_image_alt_count: int
    unknown_image_alt_count: int
    findings_truncated: bool

    @property
    def complete(self) -> bool:
        """Whether saved input can rule out an unreported empty-anchor defect."""

        return self.invalid_record_count == 0 and self.unknown_image_alt_count == 0 and not self.findings_truncated

    def as_dict(self) -> dict[str, object]:
        """Return JSON-safe coverage including its derived completion state."""

        return {**asdict(self), "complete": self.complete}


@dataclass(frozen=True)
class EmptyAnchorAudit:
    """Bounded Q91 output from :func:`evaluate_empty_anchors`."""

    findings: tuple[EmptyAnchorFinding, ...]
    finding_count: int
    coverage: EmptyAnchorCoverage

    def as_dict(self) -> dict[str, object]:
        """Return stable audit evidence suitable for a report payload."""

        return {
            "findings": [finding.as_dict() for finding in self.findings],
            "finding_count": self.finding_count,
            "coverage": self.coverage.as_dict(),
        }


def evaluate_empty_anchors(
    links: Sequence[Mapping[str, object]],
    *,
    max_findings: int = 500,
) -> EmptyAnchorAudit:
    """Evaluate saved internal links for Q91 without making accessibility guesses.

    A record must supply non-empty ``source_url`` and ``target_url`` strings.
    ``anchor_text`` is empty when absent, ``None`` or whitespace-only.  For
    such a record, ``linked_image_alt_texts`` has a deliberately three-state
    contract:

    * ``None`` or omitted: no image-alt evidence was retained (unknown);
    * a sequence (including ``[]``): image facts were retained;
    * at least one non-whitespace string in that sequence: the link has a
      meaningful image alternative and is not a Q91 finding.

    The evaluator returns only confirmed rows.  Unknown image-alt evidence and
    invalid records make coverage incomplete, so a consumer cannot claim that
    a zero-finding result is healthy.  Output ordering is independent of input
    order and emitted rows are capped by ``max_findings``.
    """

    if max_findings < 1:
        raise ValueError("max_findings must be at least 1")

    input_count = len(links)
    invalid_count = 0
    empty_count = 0
    meaningful_alt_count = 0
    no_meaningful_alt_count = 0
    unknown_alt_count = 0
    confirmed: list[EmptyAnchorFinding] = []

    for record in links:
        parsed = _parse_record(record)
        if parsed is None:
            invalid_count += 1
            continue
        source_url, target_url, xpath, anchor_text, image_alts = parsed
        if _has_text(anchor_text):
            continue
        empty_count += 1
        if image_alts is None:
            unknown_alt_count += 1
            continue
        if any(_has_text(alt) for alt in image_alts):
            meaningful_alt_count += 1
            continue
        no_meaningful_alt_count += 1
        confirmed.append(
            EmptyAnchorFinding(
                source_url=source_url,
                target_url=target_url,
                xpath=xpath,
                anchor_text=anchor_text,
                linked_image_alt_texts=image_alts,
            )
        )

    confirmed.sort(
        key=lambda finding: (
            finding.source_url,
            finding.target_url,
            finding.xpath or "",
            finding.anchor_text or "",
            finding.linked_image_alt_texts,
        )
    )
    finding_count = len(confirmed)
    findings_truncated = finding_count > max_findings
    coverage = EmptyAnchorCoverage(
        input_record_count=input_count,
        valid_record_count=input_count - invalid_count,
        invalid_record_count=invalid_count,
        empty_anchor_count=empty_count,
        empty_anchor_with_meaningful_image_alt_count=meaningful_alt_count,
        empty_anchor_without_meaningful_image_alt_count=no_meaningful_alt_count,
        unknown_image_alt_count=unknown_alt_count,
        findings_truncated=findings_truncated,
    )
    return EmptyAnchorAudit(
        findings=tuple(confirmed[:max_findings]),
        finding_count=finding_count,
        coverage=coverage,
    )


def _parse_record(
    record: Mapping[str, object],
) -> tuple[str, str, str | None, str | None, tuple[str | None, ...] | None] | None:
    source_url = _required_text(record.get("source_url"))
    target_url = _required_text(record.get("target_url"))
    if source_url is None or target_url is None:
        return None
    xpath = _optional_text(record.get("xpath"))
    anchor_text = _optional_text(record.get("anchor_text"))
    image_alts = _image_alts(record)
    if image_alts is _INVALID:
        return None
    return source_url, target_url, xpath, anchor_text, image_alts


_INVALID = object()


def _image_alts(record: Mapping[str, object]) -> tuple[str | None, ...] | None | object:
    """Decode image-alternative facts while preserving uncollected evidence."""

    if "linked_image_alt_texts" not in record or record["linked_image_alt_texts"] is None:
        return None
    values = record["linked_image_alt_texts"]
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        return _INVALID
    parsed: list[str | None] = []
    for value in values:
        if value is None:
            parsed.append(None)
        elif isinstance(value, str):
            parsed.append(value)
        else:
            return _INVALID
    return tuple(parsed)


def _has_text(value: str | None) -> bool:
    return value is not None and bool(value.strip())


def _required_text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _optional_text(value: object) -> str | None:
    return value if isinstance(value, str) else None
