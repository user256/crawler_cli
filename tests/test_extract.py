from crawler_cli.extract import extract_page_data


def test_extract_page_data_captures_indexability_and_hreflang():
    html = """
    <html lang="en">
      <head>
        <title>Example</title>
        <meta name="description" content="Description here">
        <meta name="robots" content="noindex, nofollow">
        <link rel="canonical" href="/canonical-page">
        <link rel="alternate" hreflang="en-gb" href="https://example.com/uk">
      </head>
      <body>
        <h1>Main title</h1>
        <h2>Section</h2>
        <p>Hello world from crawler cli.</p>
      </body>
    </html>
    """
    headers = {
        "Content-Type": "text/html; charset=utf-8",
        "X-Robots-Tag": "noindex",
        "X-Canonical": "https://example.com/header-canonical",
        "Link": '<https://example.com/us>; rel="alternate"; hreflang="en-us"',
    }

    extracted = extract_page_data(html, "https://example.com/page", headers)

    assert extracted.title == "Example"
    assert extracted.meta_description == "Description here"
    assert extracted.meta_robots.noindex is True
    assert extracted.meta_robots.nofollow is True
    assert extracted.x_robots_tag.noindex is True
    assert extracted.canonical == "https://example.com/canonical-page"
    assert extracted.x_canonical == "https://example.com/header-canonical"
    assert extracted.html_lang == "en"
    assert extracted.headings["h1"] == ["Main title"]
    assert {item.hreflang for item in extracted.hreflang_links} == {"en-gb", "en-us"}
    assert extracted.word_count > 0
