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
| D10 | MBOX discovery and changed files (milestone 2) | Every regular file below `MAILROBBE_MBOX_DIR` whose first bytes are `From ` is an MBOX file, whatever its name; hidden entries and `_generator/` are skipped. `mbox_file.path` is relative to that directory. A file that grew is continued at its last committed record; one whose first MiB changed or that shrank below its progress is imported again from scratch. | 2026-10-20 |
| D11 | Importer parallelism | One worker process per MBOX file (no byte ranges), started with spawn; each batch commits its mails together with the file's progress, which makes interrupted imports resumable and idempotent. | 2026-10-20 |
| D12 | Duplicates | A mail is a duplicate of the earliest mail (by file path, then byte offset) with the same Message-ID and subject, or, when it has no Message-ID, the same SHA-256 of the raw message. Computed after the import, not while it runs. | 2026-10-20 |
| D13 | Threads | Mails are linked through Message-ID, In-Reply-To and References; `thread_id` is the smallest mail id of a thread with at least two mails and NULL for a single mail. Duplicates take the thread of their original. | 2026-10-20 |
| D14 | Full text and size limits | `mail.tsv` is a generated column with the German text search configuration, subject weighted A, body B; `body_text` is cut at 50,000 characters. Attachments above 50 MiB are not hashed; mails above 256 MiB are imported with their headers only. Both limits are settings. | 2026-10-20 |
