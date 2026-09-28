from __future__ import annotations

from crawler_cli.compare_renders import RenderFinding, RenderParityComparison
from crawler_cli.models import BrowserRequestObservation, ExtractedContent, ImageReference, RobotsDirectives
from crawler_cli.rendered_audit import render_audit_records


def _content(images: list[ImageReference]) -> ExtractedContent:
    return ExtractedContent(
        title="Title",
        meta_description="Description",
        meta_robots=RobotsDirectives(),
        x_robots_tag=RobotsDirectives(),
        canonical="https://example.test/page",
        x_canonical=None,
        hreflang_links=[],
        html_lang="en",
        headings={"h1": ["Heading"], "h2": []},
        text="Body",
        word_count=1,
        metadata={},
        image_references=images,
    )


def _comparison(state: str = "complete") -> RenderParityComparison:
    empty_alt = ImageReference(
        url="https://example.test/decorative.svg",
        source="img_src",
        alt="",
        alt_present=True,
        xpath="/html/body/img[1]",
    )
    missing_alt = ImageReference(
        url="https://example.test/hero.jpg",
        source="img_src",
        alt=None,
        alt_present=False,
        xpath="/html/body/img[2]",
    )
    result = type(
        "Result",
        (),
        {
            "observed_requests": [
                BrowserRequestObservation(
                    url="http://cdn.example.test/content.json?token=secret",
                    method="GET",
                    resource_type="xhr",
                    outcome="failed",
                    failure="net::ERR_FAILED",
                    content_type="application/json",
                )
            ]
        },
    )()
    return RenderParityComparison(
        url="https://example.test/page",
        final_url="https://example.test/page",
        status=200,
        state=state,  # type: ignore[arg-type]
        state_reason="render_settle_timeout" if state != "complete" else None,
        raw=_content([empty_alt, missing_alt]),
        rendered=_content([empty_alt, missing_alt]),
        only_in_rendered={"https://example.test/new?token=secret"},
        findings=[
            RenderFinding(
                code="metadata_render_dependency",
                severity="medium",
                field="title",
                explanation="Title changed after rendering.",
                remediation="Review the template.",
                completeness="partial" if state != "complete" else "complete",  # type: ignore[arg-type]
            )
        ],
        crawl_result=result,  # type: ignore[arg-type]
    )


def test_render_observations_keep_devices_distinct_and_empty_alt_is_not_a_defect():
    records = render_audit_records([_comparison()], device="mobile_viewport", viewport=(390, 844))
    coverage = records[0]
    candidates = [row for row in records if row.get("record_type") == "candidate"]
    images = [row for row in records if row.get("record_kind") == "image_reference"]
    requests = [row for row in records if row.get("record_kind") == "browser_request"]

    assert coverage["device"] == "mobile_viewport"
    assert coverage["viewport_width"] == 390
    assert len([row for row in candidates if row["candidate_type"] == "image_missing_alt_attribute_review"]) == 1
    assert any(row.get("intentional_empty_alt") is True for row in images)
    assert requests[0]["mixed_content_candidate"] is True
    assert requests[0]["failure_observed"] is True
    assert "token" in requests[0]["target_url"]
    assert "secret" not in str(records)


def test_unsettled_render_never_emits_divergence_or_image_defect_candidates():
    records = render_audit_records([_comparison("partial")], device="desktop_viewport", viewport=(1280, 720))

    assert records[0]["complete"] is False
    assert not [row for row in records if row.get("record_type") == "candidate"]
    assert any(row.get("record_kind") == "image_reference" for row in records)


def test_empty_hydrated_page_is_inconclusive_not_complete_parity():
    comparison = _comparison()
    comparison.rendered_main_text = None
    comparison.rendered.headings = {"h1": [], "h2": []}
    comparison.rendered_internal_links.clear()

    records = render_audit_records([comparison], device="desktop_viewport", viewport=(1280, 720))

    assert records[0]["complete"] is False
    assert records[1]["state"] == "inconclusive"
    assert records[1]["state_reason"] == "empty_rendered_primary_content"
    assert not [row for row in records if row.get("record_type") == "candidate"]


def test_scroll_link_observations_keep_reveal_state_device_and_redaction():
    comparison = _comparison()
    comparison.crawl_result.render_link_observations = [
        {
            "capture_phase": "pre_interaction",
            "href": "https://example.test/initial?token=secret",
            "anchor_text": "Initial link",
            "dom_path": "/html/body/a[1]",
            "rendered_visible": True,
            "in_viewport": True,
        },
        {
            "capture_phase": "after_bounded_scroll",
            "reveal_state": "scroll_revealed",
            "href": "https://example.test/revealed?token=secret",
            "anchor_text": "Revealed link",
            "dom_path": "/html/body/a[2]",
            "rendered_visible": True,
            "in_viewport": True,
        },
    ]
    comparison.crawl_result.render_link_capture = {
        "state": "complete",
        "scroll_revealed_link_count": 1,
        "controls_activated": False,
    }

    records = render_audit_records([comparison], device="mobile_viewport", viewport=(390, 844))
    coverage = records[0]
    links = [row for row in records if row.get("record_kind") == "rendered_link"]

    assert coverage["scroll_link_state_capture"] == "complete"
    assert coverage["interaction_state"] == "bounded_scroll_only"
    assert coverage["controls_activated"] == "not_tested"
    assert coverage["scroll_revealed_link_count"] == 1
    assert len(links) == 2
    revealed = next(row for row in links if row["reveal_state"] == "scroll_revealed")
    assert revealed["device"] == "mobile_viewport"
    assert revealed["same_host"] is True
    assert "token" in revealed["target_url"]
    assert "secret" not in str(records)
