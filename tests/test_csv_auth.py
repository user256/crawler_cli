import pytest

from crawler_cli.auth import AuthConfig
from crawler_cli.backends import _request_headers
from crawler_cli.config import CrawlConfig
from crawler_cli.csv_urls import load_urls_from_csv


def test_load_urls_from_csv_with_header(tmp_path):
    csv_path = tmp_path / "urls.csv"
    csv_path.write_text("url,note\nhttps://example.com/a,one\nhttps://example.com/b,two\n", encoding="utf-8")
    assert load_urls_from_csv(csv_path) == ["https://example.com/a", "https://example.com/b"]


def test_load_urls_from_plain_lines(tmp_path):
    csv_path = tmp_path / "urls.txt"
    csv_path.write_text("https://example.com/x\n# comment\nhttps://example.com/y\n", encoding="utf-8")
    assert load_urls_from_csv(csv_path) == ["https://example.com/x", "https://example.com/y"]


def test_auth_bearer_headers():
    config = CrawlConfig(
        auth=AuthConfig(auth_type="bearer", token="secret-token"),
    )
    headers = _request_headers(config, "https://example.com/page")
    assert headers["Authorization"] == "Bearer secret-token"


def test_auth_basic_credentials():
    auth = AuthConfig(auth_type="basic", username="user", password="pass")
    assert auth.basic_credentials() == ("user", "pass")
