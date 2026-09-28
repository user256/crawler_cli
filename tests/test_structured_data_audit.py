from crawler_cli.structured_data_audit import structured_data_inventory_report
from crawler_cli.technical_audit import audit_sheet_tables, build_technical_audit


def _item(schema_type, parsed, **kwargs):
    return {
        "url": "https://example.test/page",
        "format": "json-ld",
        "schema_type": schema_type,
        "position": "0",
        "is_valid": True,
        "parsed_data": parsed,
        "raw_data": '{"@type":"' + schema_type + '"}',
        **kwargs,
    }


def _candidates(rows, candidate_type):
    return [row for row in rows if row.get("candidate_type") == candidate_type]


def test_recipe_feature_requirements_are_separate_from_parser_validity_and_recommendations():
    rows = structured_data_inventory_report(
        [
            _item(
                "Recipe",
                '{"@type":"Recipe","name":"Soup","image":"https://example.test/soup.jpg"}',
                is_valid=False,
            )
        ]
    )
    assert not _candidates(rows, "google_feature_required_property_missing")
    item = next(row for row in rows if row.get("record_kind") == "structured_data_item")
    assert item["json_syntax_state"] == "valid"
    assert item["stored_schema_validation"] == "local_check_fail"
    assert "not_a_comprehensive" in item["schema_validation_scope"]
    advisory = _candidates(rows, "google_feature_recommended_property_absent")
    assert len(advisory) == 1
    assert advisory[0]["qualification"] == "advisory_only_no_remediation_action"
    assert advisory[0]["rules_verified_on"] == "2026-09-25"


def test_missing_feature_required_properties_are_candidates_with_exact_source_not_actions():
    rows = structured_data_inventory_report([_item("Recipe", '{"@type":"Recipe","name":"Soup"}')])
    candidate = _candidates(rows, "google_feature_required_property_missing")[0]
    assert candidate["missing_required_properties"] == ["image"]
    assert candidate["source"].endswith("/recipe")


def test_valid_itemlist_summary_positions_and_urls_are_accepted_without_generic_name_rule():
    rows = structured_data_inventory_report(
        [
            _item(
                "ItemList",
                '{"@type":"ItemList","numberOfItems":2,"itemListElement":['
                '{"@type":"ListItem","position":1,"url":"https://example.test/a"},'
                '{"@type":"ListItem","position":2,"url":"https://sub.example.test/b"}]}',
            )
        ]
    )
    candidates = [row for row in rows if row.get("record_type") == "candidate"]
    assert candidates == []


def test_itemlist_structural_defects_identify_exact_items_and_count_mismatch():
    rows = structured_data_inventory_report(
        [
            _item(
                "ItemList",
                '{"@type":"ItemList","numberOfItems":3,"itemListElement":['
                '{"@type":"ListItem","position":2,"url":"https://example.test/a"},'
                '{"@type":"ListItem","position":2,"url":"https://other.test/b"}]}',
            )
        ]
    )
    positions = _candidates(rows, "itemlist_positions_duplicate")[0]
    assert positions["observed_positions"] == [2, 2]
    assert positions["item_indexes"] == [0, 1]
    off_domain = _candidates(rows, "itemlist_summary_url_off_domain")[0]
    assert off_domain["item_index"] == 1
    count = _candidates(rows, "itemlist_declared_count_mismatch")[0]
    assert (count["declared_count"], count["actual_count"]) == (3, 2)


def test_unknown_feature_and_recommendation_candidates_never_enter_client_action_log():
    audit = build_technical_audit(
        crawl_run_id="run-1",
        reports={
            "structured-data-inventory": [
                _item("UnknownFeature", '{"@type":"UnknownFeature","name":"x"}'),
                _item("Recipe", '{"@type":"Recipe","name":"Soup","image":"/soup.jpg"}'),
            ]
        },
        run_context={
            "completion_state": "complete",
            "parsed_html_count": 1,
            "schema_capabilities": {"schema_json": True},
        },
    )
    feature_check = next(row for row in audit["checks"] if row["id"] == "feature-specific-structured-data")
    assert feature_check["qualification"] == "analyst_only"
    assert feature_check["status"] == "pass"
    assert audit["client_publication_gate"]["client_actions"] == []
    assert any(
        row.get("candidate_type") == "google_feature_eligibility_not_evaluated"
        for row in audit["structured_data_report"]
    )
    assert "Structured Data" not in audit_sheet_tables(audit)
    assert any(
        row.get("candidate_type") == "google_feature_eligibility_not_evaluated"
        for row in audit["structured_data_report"]
    )


def test_rendered_structured_data_inventory_is_kept_as_a_separate_channel():
    rows = structured_data_inventory_report(
        [],
        rendered_rows=[
            _item(
                "Recipe",
                '{"@type":"Recipe","name":"Soup","image":"https://example.test/soup.jpg"}',
                source_channel="rendered_dom",
                extraction_state="rendered",
                state="complete",
            )
        ],
    )
    item = next(row for row in rows if row.get("record_kind") == "structured_data_item")
    assert item["source_channel"] == "rendered_dom"
    assert rows[0]["rendered_row_count"] == 1


def test_unsettled_rendered_schema_is_recorded_but_not_feature_checked():
    rows = structured_data_inventory_report(
        [],
        rendered_rows=[
            _item(
                "Recipe",
                '{"@type":"Recipe","name":"Soup"}',
                source_channel="rendered_dom",
                extraction_state="rendered",
                state="inconclusive",
            )
        ],
    )
    assert not _candidates(rows, "google_feature_required_property_missing")
    item = next(row for row in rows if row.get("record_kind") == "structured_data_item")
    assert item["observation_state"] == "inconclusive"
