# Technical-audit skill coverage map

The generated audit JSON contains `skill_requirements`, a versioned-in-code
inventory with one row for every H2/H3 section in
`skills/technical-seo-audit/SKILL.md`. Each row links that section's distinct
controls to a check-registry ID, implementation state, evidence boundary,
regression/acceptance test, and owning ticket. The `state` describes support
status; the per-run `checks` array separately says whether the current audit
tested, partially tested, or could not test that requirement. An implemented
collector is not evidence that a site's population was tested.

The inventory intentionally preserves gaps. In particular, external-link
integrity, non-production-host exposure, complete sitemap hreflang comparison,
resource impact measurement, field CWV, verified access-log analysis, and
business/content-purpose judgements are not represented as completed merely
because a related collector or candidate inventory exists. Owners for known
follow-up work are included in each row.

`tests/test_technical_audit.py::test_skill_requirement_map_covers_every_skill_section_and_has_owners`
guards heading coverage, source-section digests, mapped control counts, unique
requirement and check-registry IDs, registry references, valid states,
evidence/test pointers, and ticket ownership. Any change to a source section
forces an explicit mapping review and digest update before CI passes.
