from crawler_cli.compression import compress_html, decompress_html, is_compressed


def test_compress_round_trip():
    html = "<html><body>" + ("<p>Hello world</p>" * 200) + "</body></html>"
    blob = compress_html(html)
    assert is_compressed(blob)
    assert len(blob) < len(html.encode("utf-8"))
    assert decompress_html(blob) == html


def test_legacy_raw_utf8_still_reads():
    raw = "<html><body>legacy</body></html>".encode("utf-8")
    assert not is_compressed(raw)
    assert decompress_html(raw) == "<html><body>legacy</body></html>"


def test_empty_blob():
    assert decompress_html(b"") == ""
