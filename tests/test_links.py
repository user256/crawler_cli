from crawler_cli.extract import extract_links, generate_xpath
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


def test_generate_xpath_disambiguates_siblings():
    html = "<div><a href='/a'>A</a><a href='/b'>B</a></div>"
    soup = BeautifulSoup(html, "html.parser")
    anchors = soup.find_all("a")
    paths = [generate_xpath(anchor) for anchor in anchors]
    assert paths[0] != paths[1]
