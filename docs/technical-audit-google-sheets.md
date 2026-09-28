# Technical audit Google Sheets publication

Publishing is optional and creates a new copy; it never writes to the source
template. The selected workbook must implement the checked-in
[`technical-audit-sheets-v1.json`](../templates/technical-audit-sheets-v1.json)
contract. This is not a compatibility promise for arbitrary spreadsheets.

## Access setup

Install the optional client dependencies with `pip install crawler-cli[google-sheets]`.

Choose one credential mode:

- OAuth user credentials: set `GOOGLE_DOCS_OAUTH_TOKEN_FILE` to a valid
  authorized-user token with Google Drive and Sheets scopes. The user must be
  able to view and copy the template and create/edit a spreadsheet in the
  destination folder.
- Service account: pass `--google-sheets-credentials` with its JSON key file,
  share the template with the service-account email, and grant it permission to
  create files in the destination folder. Keep the key out of source control.

The API checks template MIME type/copy access, spreadsheet compatibility, and
destination-folder capability before creating a copy. Authentication and
authorization failures are reported without printing credentials.

## Publish and recover

```bash
crawler-cli technical-audit \
  --postgres-dsn "$CRAWLER_CLI_POSTGRES_DSN" \
  --crawl-run-id crawl-20260925-a \
  --out ./audit-evidence/technical-audit.json \
  --publish-google-sheets \
  --google-sheets-template 'https://docs.google.com/spreadsheets/d/TEMPLATE_ID/edit'
```

The command writes the deterministic JSON first. A local receipt is then
created beside that artifact before the copied workbook is mutated. It records
the template and table digests, copied file ID/URL, per-tab clear state,
completed write chunks, and final publication state. Store the receipt as
carefully as the audit output: it identifies the copied customer workbook.

If publication is interrupted, reuse the same audit inputs and receipt:

```bash
crawler-cli technical-audit \
  --postgres-dsn "$CRAWLER_CLI_POSTGRES_DSN" \
  --crawl-run-id crawl-20260925-a \
  --out ./audit-evidence/technical-audit.json \
  --publish-google-sheets \
  --google-sheets-template 'https://docs.google.com/spreadsheets/d/TEMPLATE_ID/edit' \
  --google-sheets-receipt ./audit-evidence/technical-audit.json.sheets-receipt.json \
  --resume-google-sheets
```

Resume requires exact template and table digests. It checks previously written
chunks before continuing; if a partial/uncheckpointed range differs from both
the expected audit and a blank range, it refuses to overwrite it and leaves the
receipt in `partial` state for manual reconciliation. Readback mismatch also
blocks completion. Cell values use RAW input, including URL-like and
formula-looking strings; only validated HTTP(S) URL columns receive rich-text
links. The combined audit payload is bounded to 8 MB, rows to 50,000 per tab, and writes are
checkpointed in chunks of 500 rows.
