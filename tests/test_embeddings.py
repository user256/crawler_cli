from crawler_cli.embeddings import clean_text_from_html


def test_clean_text_from_html_strips_scripts():
    html = """
    <html><head><script>alert(1)</script><style>.x{}</style></head>
    <body><h1>Title</h1><p>Hello   world</p></body></html>
    """
    text = clean_text_from_html(html)
    assert "alert" not in text
    assert "Title" in text
    assert "Hello world" in text
