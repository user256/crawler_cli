from crawler_cli.persistence import encode_html_for_storage
from crawler_cli.compression import decompress_html, is_compressed


def test_encode_html_for_storage_compressed():
    blob = encode_html_for_storage("<html>hi</html>", compress=True)
    assert blob is not None
    assert is_compressed(blob)
    assert decompress_html(blob) == "<html>hi</html>"


def test_encode_html_for_storage_raw():
    blob = encode_html_for_storage("<html>hi</html>", compress=False)
    assert blob == b"<html>hi</html>"
    assert not is_compressed(blob)
