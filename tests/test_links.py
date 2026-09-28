from crawler_cli.extract import extract_image_references, extract_links, generate_xpath, parse_html
from bs4 import BeautifulSoup


def test_extract_links_returns_anchor_text_and_xpath():
    html = """
    <html><body>
      <nav>
        <a href="/about" id="about-link">About us</a>
        <a href="/logo.png"><img src="/logo.png" alt="Home"></a>
      </nav>
    </body></html>
    """
    links = extract_links(html, "https://example.com/", same_host_only=True)
    assert len(links) == 2

    about = next(link for link in links if link.href.endswith("/about"))
    assert about.anchor_text == "About us"
    assert about.xpath.startswith("/")
    assert about.is_image is False

    image_link = next(link for link in links if "logo" in link.href)
    assert image_link.is_image is True
    assert image_link.anchor_text is not None
    assert image_link.anchor_text.startswith("[IMG:")


def test_extract_links_same_host_only_drops_external():
    html = '<html><body><a href="https://external.com/page">ext</a><a href="/local">local</a></body></html>'
    links = extract_links(html, "https://example.com/", same_host_only=True)
    hrefs = {lnk.href for lnk in links}
    assert "https://external.com/page" not in hrefs
    assert "https://example.com/local" in hrefs


def test_extract_links_allowed_hosts_admits_extra_host():
    html = (
        "<html><body>"
        '<a href="https://blog.example.com/post">blog</a>'
        '<a href="https://external.com/nope">nope</a>'
        '<a href="/local">local</a>'
        "</body></html>"
    )
    links = extract_links(
        html,
        "https://example.com/",
        same_host_only=True,
        allowed_hosts={"blog.example.com"},
    )
    hrefs = {lnk.href for lnk in links}
    assert "https://blog.example.com/post" in hrefs
    assert "https://example.com/local" in hrefs
    assert "https://external.com/nope" not in hrefs


def test_extract_links_no_host_filter_returns_all():
    html = '<html><body><a href="https://a.com/">a</a><a href="https://b.com/">b</a></body></html>'
    links = extract_links(html, "https://a.com/", same_host_only=False)
    hrefs = {lnk.href for lnk in links}
    assert "https://a.com/" in hrefs
    assert "https://b.com/" in hrefs


def test_generate_xpath_disambiguates_siblings():
    html = "<div><a href='/a'>A</a><a href='/b'>B</a></div>"
    soup = BeautifulSoup(html, "html.parser")
    anchors = soup.find_all("a")
    paths = [generate_xpath(anchor) for anchor in anchors]
    assert paths[0] != paths[1]


def test_extract_image_references_captures_srcset_alt_and_dimensions():
    html = """
    <picture>
      <source srcset="/hero.webp 1x, /hero-2x.webp 2x">
      <img src="/hero.jpg" srcset="/hero-small.jpg 480w" alt="Casino lobby"
           width="800" height="450" loading="lazy">
    </picture>
    <img src="/decorative.svg" alt="">
    <img src="/missing-alt.png">
    """
    images = extract_image_references(parse_html(html), "https://example.com/page")
    by_url = {image.url: image for image in images}
    assert by_url["https://example.com/hero.jpg"].alt == "Casino lobby"
    assert by_url["https://example.com/hero.jpg"].width == 800
    assert by_url["https://example.com/hero.jpg"].height == 450
    assert by_url["https://example.com/hero-small.jpg"].source == "img_srcset"
    assert by_url["https://example.com/hero.webp"].source == "picture_source"
    assert by_url["https://example.com/decorative.svg"].alt_present is True
    assert by_url["https://example.com/decorative.svg"].alt == ""
    assert by_url["https://example.com/missing-alt.png"].alt_present is False
