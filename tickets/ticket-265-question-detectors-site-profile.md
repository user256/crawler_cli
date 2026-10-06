# Ticket 265: Site-profile detectors for the question runner

## Goal

Answer the questions whose rule depends on the site: template patterns, hub
lists, parameter families, affiliate routes, staging hosts and declared AI
crawler policy, all read from a site profile
(`templates/site-profile.example.json`).

## Scope

| Question | Detector / answer |
|---|---|
| Q20 | noindex on indexable templates, sitemap or nav targets |
| Q24 | parameter-family sizing and run-over-run growth |
| Q27, Q77 | non-production / cache host exposure |
| Q34 | `lifecycle-pages` |
| Q36 | `profile-subtab-indexability` |
| Q37 | `empty-profile-indexability` |
| Q40 | `nav-hub-links` |
| Q43 | `sitewide-external-links` |
| Q44 | priority-template crawl depth |
| Q48 | `hub-cluster-links` |
| Q49 | `article-to-hub-links` |
| Q52 | `table-markup` (heuristic) |
| Q55 | `disclaimer-placement` |
| Q57 | `stale-title-dates` |
| Q59 | `author-bylines` |
| Q62 | `generic-anchor-text` |
| Q75 | `affiliate-link-qualification` |
| Q78 | noindexed taxonomy hubs |
| Q96 | `ai-crawler-policy` (robots verdict per AI agent vs declared policy) |

## Tasks

- Load and validate the site profile once; report missing keys per question
  (already done by `validate_question_registry`).
- Implement each detector against stored run data; answerers return Pending
  with the missing key when the profile lacks it.
- Write the Rainbet site profile as the first real profile.

## Definition of Done

- [ ] Each question answers on a fixture run with the example profile and
  stays Pending, naming the key, without it.
- [ ] The Rainbet profile validates with no missing keys.
