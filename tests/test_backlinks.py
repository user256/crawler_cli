from __future__ import annotations

import pytest

from crawler_cli.backlinks import BacklinkImportError, load_backlink_import


def test_load_backlink_import_reads_utf16_tab_export(tmp_path):
    path = tmp_path / "backlinks.csv"
    path.write_text(
        "Referring page URL\tTarget URL\n"
        "https://referrer.example/a\thttps://site.example/landing\n"
        "https://referrer.example/b\thttps://site.example/landing\n"
        "\thttps://site.example/other\n",
        encoding="utf-16",
    )

    imported = load_backlink_import(path)

    assert imported.total_rows == 3
    assert imported.skipped_rows == 0
    assert imported.pairs == [
        ("https://site.example/landing", "https://referrer.example/a"),
        ("https://site.example/landing", "https://referrer.example/b"),
        ("https://site.example/other", None),
    ]


def test_load_backlink_import_requires_target_column(tmp_path):
    path = tmp_path / "backlinks.csv"
    path.write_text("URL\nhttps://site.example/\n", encoding="utf-8")

    with pytest.raises(BacklinkImportError, match="missing target column"):
        load_backlink_import(path)
