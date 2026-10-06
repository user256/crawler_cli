# Ticket 217: Weight failing URLs by supplied backlink data

## Goal

Accept third-party backlink exports and rank failing or redirecting URLs by the
link equity they hold, so remediation starts where it matters.

## Background

The rainbet Ahrefs "best by links" export (top 2,500 rows, UTF-16 tab-separated)
contained 625 non-200 URLs. A live check found 562 dead, together carrying about
34,800 referring domains summed per page, with single game URLs holding over
2,000 each. The same export exposed a whole subdomain (`blog.rainbet.com`) that
no longer resolves in DNS. Without this weighting, 3,000+ archive 404s are an
unprioritised list.

## Tasks

- Add `--backlink-export CSV` (repeatable) with adapters for Ahrefs best-by-links
  and backlinks exports, Semrush indexed pages, and a Search Console
  "Top linked pages" export. Detect UTF-16 and tab delimiters.
- Normalise target URLs to the run's URL identity, including other hosts on the
  audited registrable domain.
- Carry referring domains, dofollow counts and source/export date per URL.
  Never add referring-domain counts across pages as if they were unique
  domains; report a per-page figure and label any sum as non-unique.
- Record DNS resolution failures as a distinct live state.
- Use the weight to order failing-URL and redirect actions (ticket 218).

- Allow a `backlinks` source in the known-URL inventory, which currently
  rejects anything other than `analytics` and `search_console`.

## Definition of Done

- Fixture exports from each adapter parse with correct numeric fields.
- A failing URL with backlinks sorts above one without.
- A host that no longer resolves is reported with its linked URL count.
- Row-limited exports are labelled as partial populations in the output.
