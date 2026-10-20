# Decisions

Binding decisions for Mailspider beyond docs/SPEC.md. New entries get the next number; a changed decision gets a new entry that names the one it replaces.

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
