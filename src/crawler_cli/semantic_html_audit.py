"""Pure stored-HTML facts for the semantic-markup audit questions.

The normal crawl extraction intentionally normalises page content.  These
facts retain the small pieces of document structure that are needed for the
semantic HTML questions without making a judgement about a site's templates,
rendered DOM, or editorial intent.  Consumers can therefore group these
per-page facts by a URL pattern and apply the question-specific thresholds.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import re

from bs4 import BeautifulSoup, Tag

from .schema import _PARSER


LONG_PAGE_MINIMUM_WORDS = 1_500
"""Q58's long-form boundary: the question says *over* this word count."""

LONG_PAGE_MINIMUM_H2S = 4
"""Q58's minimum number of H2 sections."""

TOC_MINIMUM_LINKED_H2S = 2

MAX_LISTED_IMAGES = 50
"""Uncaptioned image sources kept per page; the count is always exact."""
"""One fragment link can be an ordinary cross-reference, not a TOC."""

_WORD = re.compile(r"\b[\w'-]+\b", re.UNICODE)


@dataclass(frozen=True)
class SemanticHtmlFacts:
    """Deterministic semantic-HTML facts for one saved response.

    ``None`` means the question is not eligible for this response; it never
    means that the page passed.  Counts are intentionally exposed alongside
    the booleans so callers can choose a denominator and retain evidence.
    """

    url: str
    body_present: bool

    landmark_eligible: bool
    main_count: int
    header_count: int
    footer_count: int
    missing_main: bool | None
    missing_header_and_footer: bool | None
    missing_required_landmarks: bool | None

    main_image_eligible: bool
    main_image_count: int
    main_images_with_figure_and_figcaption: int
    main_images_without_figure_and_figcaption: int
    uncaptioned_main_image_srcs: tuple[str, ...]

    content_word_count: int
    content_h2_count: int
    h2_with_id_count: int
    linked_h2_ids: tuple[str, ...]
    linked_h2_count: int
    toc_eligible: bool
    has_h2_fragment_toc: bool | None
    missing_h2_fragment_toc: bool | None

    def as_dict(self) -> dict[str, object]:
        """Return JSON-friendly evidence without making report-layer choices."""
        return asdict(self)


def _content_root(soup: BeautifulSoup, body: Tag | None) -> Tag | None:
    """Prefer the semantic content region, then an article, then the body."""
    if body is None:
        return None
    return body.find("main") or body.find("article") or body


def _content_word_count(root: Tag | None) -> int:
    if root is None:
        return 0
    # Work on an isolated parse so this function does not mutate the document
    # used by the other facts.
    fragment = BeautifulSoup(str(root), _PARSER)
    for ignored in fragment.find_all(("script", "style", "template", "noscript")):
        ignored.decompose()
    return len(_WORD.findall(fragment.get_text(" ", strip=True)))


def _has_figure_caption(image: Tag) -> bool:
    """Whether an image is enclosed in a figure with a figcaption element."""
    figure = image.find_parent("figure")
    return figure is not None and figure.find("figcaption") is not None


def inspect_semantic_html(url: str, html: str) -> SemanticHtmlFacts:
    """Inspect saved HTML and return reusable Q51/Q54/Q58 evidence.

    This looks only at source HTML.  It deliberately does not infer template
    identity, evaluate JavaScript, classify decorative images, or decide that
    a fragment menu is visually presented as a table of contents.
    """
    soup = BeautifulSoup(html, _PARSER)
    body = soup.find("body")

    mains = body.find_all("main") if body else []
    headers = body.find_all("header") if body else []
    footers = body.find_all("footer") if body else []
    landmark_eligible = body is not None
    missing_main = not mains if landmark_eligible else None
    missing_header_and_footer = (not headers and not footers) if landmark_eligible else None
    missing_required_landmarks = bool(missing_main or missing_header_and_footer) if landmark_eligible else None

    # Q54 concerns images in main content.  A page without main is ineligible
    # for this image denominator; Q51 records that separate landmark defect.
    main = mains[0] if mains else None
    main_images = main.find_all("img") if main else []
    captioned_count = sum(_has_figure_caption(image) for image in main_images)
    uncaptioned_srcs = tuple(
        str(image.get("src") or image.get("data-src") or "") for image in main_images if not _has_figure_caption(image)
    )[:MAX_LISTED_IMAGES]

    root = _content_root(soup, body)
    h2s = root.find_all("h2") if root else []
    h2_ids = {str(h2.get("id", "")).strip() for h2 in h2s if str(h2.get("id", "")).strip()}
    linked_h2_ids = tuple(
        sorted(
            {
                href[1:]
                for link in (root.find_all("a", href=True) if root else [])
                if (href := str(link.get("href", "")).strip()).startswith("#") and href[1:] in h2_ids
            }
        )
    )
    word_count = _content_word_count(root)
    toc_eligible = word_count > LONG_PAGE_MINIMUM_WORDS and len(h2s) >= LONG_PAGE_MINIMUM_H2S
    has_h2_fragment_toc = len(linked_h2_ids) >= TOC_MINIMUM_LINKED_H2S if toc_eligible else None

    return SemanticHtmlFacts(
        url=url,
        body_present=body is not None,
        landmark_eligible=landmark_eligible,
        main_count=len(mains),
        header_count=len(headers),
        footer_count=len(footers),
        missing_main=missing_main,
        missing_header_and_footer=missing_header_and_footer,
        missing_required_landmarks=missing_required_landmarks,
        main_image_eligible=main is not None,
        main_image_count=len(main_images),
        main_images_with_figure_and_figcaption=captioned_count,
        main_images_without_figure_and_figcaption=len(main_images) - captioned_count,
        uncaptioned_main_image_srcs=uncaptioned_srcs,
        content_word_count=word_count,
        content_h2_count=len(h2s),
        h2_with_id_count=len(h2_ids),
        linked_h2_ids=linked_h2_ids,
        linked_h2_count=len(linked_h2_ids),
        toc_eligible=toc_eligible,
        has_h2_fragment_toc=has_h2_fragment_toc,
        missing_h2_fragment_toc=(not has_h2_fragment_toc) if toc_eligible else None,
    )
