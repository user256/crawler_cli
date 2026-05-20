import json

from crawler_cli.extract import extract_page_data
from crawler_cli.schema import extract_schema_data, identify_schema_relationships


def test_extract_json_ld_graph_expands_entities():
    graph = {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "WebPage",
                "@id": "https://example.com/page#webpage",
                "url": "https://example.com/page",
                "name": "Example Page",
            },
            {
                "@type": "Organization",
                "@id": "https://example.com/#org",
                "name": "Example Org",
            },
            {
                "@type": "BreadcrumbList",
                "itemListElement": [
                    {"@type": "ListItem", "position": 1, "name": "Home", "item": "https://example.com/"},
                    {"@type": "ListItem", "position": 2, "name": "Page", "item": "https://example.com/page"},
                ],
            },
        ],
    }
    html = f"""
    <html>
      <head>
        <script type="application/ld+json">{json.dumps(graph)}</script>
      </head>
      <body><h1>Example</h1></body>
    </html>
    """

    items = extract_schema_data(html, "https://example.com/page")
    json_ld = [item for item in items if item.get("format") == "json-ld" and item.get("is_valid")]
    types = {item["type"] for item in json_ld}

    assert {"WebPage", "Organization", "BreadcrumbList"}.issubset(types)
    assert len(json_ld) >= 3

    relationships = identify_schema_relationships(json_ld)
    assert relationships["main_entity"] is not None
    assert relationships["main_entity"]["type"] in {"WebPage", "Article", "WebSite"}


def test_extract_page_data_includes_schema_data():
    html = """
    <html>
      <head>
        <script type="application/ld+json">
        {"@context": "https://schema.org", "@type": "Article", "headline": "Test", "author": "Jane"}
        </script>
      </head>
      <body><p>Body</p></body>
    </html>
    """
    extracted = extract_page_data(html, "https://example.com/article", {})
    assert extracted.schema_data
    assert any(item.get("type") == "Article" for item in extracted.schema_data)


def test_extract_microdata_and_rdfa():
    close_div = "</" + "div" + ">"
    html = f"""
    <html><body>
      <div itemscope itemtype="https://schema.org/Product">
        <span itemprop="name">Widget</span>
        <span itemprop="offers">9.99</span>
      {close_div}
      <div typeof="https://schema.org/Organization">
        <span property="name">Acme</span>
      {close_div}
    </body></html>
    """
    items = extract_schema_data(html, "https://example.com/products/widget")
    formats = {item.get("format") for item in items if item.get("is_valid")}
    assert "microdata" in formats
    assert "rdfa" in formats
