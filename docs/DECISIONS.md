# Decisions

Binding decisions for Mailrobbe beyond docs/SPEC.md. New entries get the next number; a changed decision gets a new entry that names the one it replaces.

| No. | Question | Decision | Date |
|---|---|---|---|
| D1 | Frontend stack | React + TypeScript + Vite, built as a static bundle served by FastAPI. | 2026-10-20 |
| D2 | Alias merging (SPEC 9) | Automatic suggestions (same display name, same local part across domains); merging only manually by the user. | 2026-10-20 |
| D3 | HTML bodies (SPEC 9) | Displayed only in a sandboxed iframe. Text is extracted from HTML for the full-text index only when the mail has no text part. | 2026-10-20 |
| D4 | Access protection (SPEC 9) | No login by default; optional HTTP Basic Auth via two environment variables. | 2026-10-20 |
| D5 | Gephi export (SPEC 9) | GraphML export of the current graph excerpt in the UI, plus a CLI command exporting the complete graph from the `edge` table. | 2026-10-20 |
| D6 | Repository workflow | One pull request per milestone against `main`, merged by Claude once lint, typecheck, tests and CI are green. Aaron is assigned and requested as reviewer but not waited for. | 2026-10-20 |
| D7 | Target machine | macOS or Linux, about 10 GB RAM for Postgres and the importer together, Docker Desktop or Linux Docker. Compose defaults: `shared_buffers` 2 GB, `maintenance_work_mem` 1 GB, importer workers `min(8, CPU count)`. | 2026-10-20 |
| D8 | Stack details | uv, Python 3.12, SQLAlchemy 2 async with asyncpg, Alembic, ruff, mypy (strict), pytest. Graph rendering with Cytoscape.js only (no Sigma.js), with the hard limit of 2,000 nodes per view from SPEC 5.4. | 2026-10-20 |
| D9 | Name | The tool is called Mailrobbe (formerly Mailspider). Package, CLI and environment prefix follow (`mailrobbe`, `MAILROBBE_`); Aaron renames the GitHub repository later. | 2026-10-20 |
| D10 | DKIM verdicts for archived mail (SPEC 3.4) | The check is cryptographic: `t=` and `x=` are recorded but do not decide, so an expired signature that still verifies is `pass`. rsa-sha256, rsa-sha1 and ed25519-sha256 are verified; RSA keys below 1024 bits are `fail`. A signature that cannot be parsed is `fail` (no separate permerror status). Every non-pass result carries a stable reason code (`DkimReason`). Mails without a signature get `unsigned` and no `dkim_result` rows. | 2026-10-20 |
| D11 | DKIM key lookups and cache (SPEC 3.4) | Key sources in order: the in-process cache (preloaded from `dns_cache`), the DNS override table (`MAILROBBE_DKIM_DNS_OVERRIDE`, or the generator's table in the MBOX directory), reserved TLDs (`.example`, `.test`, `.invalid`, `.localhost`) as not found without a query, then real DNS via dnspython (5 s per name). Answers are reused: found 7 days, not found 1 day, temp_error 10 minutes. `MAILROBBE_DKIM_OFFLINE=1` uses the cache only and turns misses into `temp_error` (`dns_offline`). A recheck asks again for every key that was missing or timed out. | 2026-10-20 |
| D12 | DKIM alignment (SPEC 3.4) | `aligned` is true when the From domain equals `d=` or one is a subdomain of the other (relaxed alignment without a public suffix list); unknown without exactly one From address. | 2026-10-20 |
| D13 | DKIM recheck (SPEC 3.4) | `mailrobbe dkim` reads mails back from their MBOX files and checks them in a process pool; by default those not checked yet and those with `no_key` or `temp_error`, selectable by status or mail id. The importer checks inline with one `DkimChecker` per worker. | 2026-10-20 |
