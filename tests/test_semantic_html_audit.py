from crawler_cli.semantic_html_audit import inspect_semantic_html


def test_landmark_facts_report_missing_main_or_both_header_and_footer():
    no_main = inspect_semantic_html("https://example.test/no-main", "<body><header></header><p>x</p></body>")
    no_header_or_footer = inspect_semantic_html("https://example.test/no-shell", "<body><main>x</main></body>")

    assert no_main.landmark_eligible is True
    assert no_main.missing_main is True
    assert no_main.missing_header_and_footer is False
    assert no_main.missing_required_landmarks is True
    assert no_header_or_footer.missing_main is False
    assert no_header_or_footer.missing_header_and_footer is True
    assert no_header_or_footer.missing_required_landmarks is True


def test_absent_body_is_not_counted_as_a_semantic_pass():
    facts = inspect_semantic_html("https://example.test/head-only", "<title>Only head</title>")

    assert facts.body_present is False
    assert facts.landmark_eligible is False
    assert facts.missing_required_landmarks is None
    assert facts.main_image_eligible is False
    assert facts.toc_eligible is False
    assert facts.missing_h2_fragment_toc is None


def test_main_images_distinguish_figure_with_figcaption_from_other_images():
    facts = inspect_semantic_html(
        "https://example.test/images",
        """
        <body><main>
          <figure><img src="captioned.jpg"><figcaption>A caption</figcaption></figure>
          <figure><img src="captionless.jpg"></figure>
          <img src="plain.jpg">
        </main></body>
        """,
    )

    assert facts.main_image_eligible is True
    assert facts.main_image_count == 3
    assert facts.main_images_with_figure_and_figcaption == 1
    assert facts.main_images_without_figure_and_figcaption == 2


def _long_page(fragment_links: str) -> str:
    words = " ".join(f"word{index}" for index in range(1_501))
    headings = "".join(f'<h2 id="section-{index}">Section {index}</h2>' for index in range(1, 5))
    return f"<body><main>{fragment_links}{headings}<p>{words}</p></main></body>"


def test_long_h2_page_with_two_h2_fragment_links_has_toc_candidate():
    facts = inspect_semantic_html(
        "https://example.test/guide",
        _long_page('<nav><a href="#section-1">One</a><a href="#section-2">Two</a></nav>'),
    )

    assert facts.content_word_count > 1_500
    assert facts.content_h2_count == 4
    assert facts.toc_eligible is True
    assert facts.linked_h2_ids == ("section-1", "section-2")
    assert facts.has_h2_fragment_toc is True
    assert facts.missing_h2_fragment_toc is False


def test_long_h2_page_without_a_fragment_link_set_is_flagged():
    facts = inspect_semantic_html(
        "https://example.test/no-toc",
        _long_page('<a href="#section-1">An ordinary reference</a>'),
    )

    assert facts.toc_eligible is True
    assert facts.linked_h2_count == 1
    assert facts.has_h2_fragment_toc is False
    assert facts.missing_h2_fragment_toc is True
