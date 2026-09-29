# Ticket 265: Deliver reconciliation results to recipient Sheets

**Status:** Open — remediation from concluded ticket 262.
**State:** Open
**Priority:** P2
**Module:** reports

Add an optional, explicit Google Sheets destination for `reconcile-sources`, reusing the repository's authenticated publishing path. Publish deterministic summary and URL-detail tabs without changing JSON/CSV output or treating a publication failure as a reconciliation result.

## Acceptance criteria

- [ ] A fake publisher receives stable summary and detail table shapes.
- [ ] Authentication, permission, and publication errors remain actionable and do not suppress local output.
- [ ] JSON and CSV schemas remain byte-for-byte compatible for identical inputs.
