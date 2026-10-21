# Mailrobbe

Local web software that imports large MBOX archives (target: about 400,000 mails, 280 GB in roughly 70 files), verifies DKIM, groups mails by person and shows a relationship graph. The specification is [docs/SPEC.md](docs/SPEC.md) (German); the UI prototype is [docs/mockup/](docs/mockup/). Read the spec before changing behaviour; its milestones (section 8) are the plan. [docs/DECISIONS.md](docs/DECISIONS.md) records the decisions taken since (frontend stack, alias merging, HTML bodies, access, export, workflow, target machine, DKIM, importer, API, relationship map, import dashboard, research file, attachments, run progress, previews); it wins where the spec leaves a point open.

## Stack

- Python 3.12, managed with uv (`pyproject.toml`, `uv.lock`)
- FastAPI, SQLAlchemy 2 async with asyncpg, Pydantic v2 and pydantic-settings
- PostgreSQL 16 with `tsvector` full text search and `pg_trgm`; schema via Alembic
- dkimpy and dnspython for DKIM; cryptography for generating test keys
- ruff (lint and format), mypy (strict), pytest with pytest-asyncio
- Docker Compose for Postgres and the backend

## Layout

- `src/mailrobbe/enums.py`: shared status vocabularies (`DkimStatus`, `best_dkim_status`, ...)
- `src/mailrobbe/db/`: ORM models mirroring the migrations, engine and session helpers
- `src/mailrobbe/migrations/`: Alembic environment and hand-written revisions (the schema's source of truth)
- `src/mailrobbe/api/`: FastAPI app (`create_app`). `schemas.py` is the HTTP contract (endpoint list in its docstring), mirrored by hand in `frontend/src/api/types.ts`; `deps.py` (session, settings, `api_error`, editor name), `query.py` (search syntax), `filters.py` (filters to SQL, keyset cursor, bounded walk), `mails.py` (list, counts, neighbours, CSV), `stats.py` (global figures), `selection.py` (the mails of a bulk change or export), `detail.py` (one mail, recheck, its research data), `documents.py` (document list, summary, page, text, attachment downloads), `body.py` (text/HTML/headers/raw views of a raw mail), `persons.py` (person list, profile, contacts, mail counts, alias suggestions, merges), `research.py` (research file: overview, themes, tags, Akten, saved searches, permalinks), `marks.py` (review status and bookmark, tag and Akte links, bulk changes), `notes.py` (notes and the note list), `exports.py` (export ZIP and PDF of one mail), `graph.py` (map excerpt, size, GraphML download), `timeline.py` (timeline: total, series, marks, first mentions), `imports.py` (import dashboard: status, summary, errors, start, pause, rescan, DKIM run), `processes.py` (the dashboard's runs as child processes), `auth.py` (Basic Auth), `frontend.py` (serves the built UI)
- `frontend/`: React + TypeScript + Vite (D1, D27); `src/api/` (contract types, client, hooks), `src/components/` (shell and shared parts), `src/features/<screen>/`, `src/routes.tsx` (one line per screen); the map (`features/graph/`) draws with Cytoscape.js in its own lazy chunk, with layouts and SVG export of its own (D41 to D45); the Akten screens (`features/research/`), the attachment screens (`features/documents/`) and the timeline (`features/timeline/`, D90) load lazily too; `src/lib/editor.ts` keeps the editor name (D54)
- `src/mailrobbe/generator/`: synthetic MBOX test data (SPEC 3.6). `model.py` documents the stage pipeline; `population.py` (persons, domains, aliases), `planner.py` (streaming plan: threads, lists, Cc chains), `render.py` (MIME), `faults.py` (defects, duplicates), `dkim.py` (keys, selectors, signing), `writer.py` (mboxrd, manifest), `pipeline.py` (worker pool)
- `src/mailrobbe/dkim/`: DKIM verification (SPEC 3.4, decisions D10 to D13); the package docstring lists the modules. `verify_mail` is pure, `DkimChecker` (one per process) adds the cached key sources, `store.py` writes `dkim_result`/`dns_cache`, `mailrobbe dkim` rechecks. `override.py` is the DNS override table for tests and generated data
- `src/mailrobbe/mbox.py`: the one definition of an MBOX record; `read_message(path, byte_offset, byte_length)` reads a stored mail back (API, tests), `read_verified` only while its SHA-256 is the imported one
- `src/mailrobbe/importer/`: MBOX importer (SPEC 3.5, decisions D14 to D18); the package docstring shows the pipeline. `split.py` (framing), `parse.py` and `text.py` (one message to `ParsedMail`), `dkim_hook.py` (seam to `dkim/`), `scan.py`, `headers.py` (header refresh of older imports, D52), `store.py` (COPY per batch, progress in the same transaction), `runner.py` (worker pool, resume), `finalize.py` (duplicates, threads, display names), `cli.py`
- `src/mailrobbe/graph/`: relationship map (SPEC 5.4, decisions D36 to D40); the package docstring lists the modules. `edges.py` fills `edge`, `edge_year` and `person.kind` (whole or for some persons), `excerpt.py` computes the excerpt the API shows, `graphml.py` writes GraphML, `cli.py` is `mailrobbe graph`
- `src/mailrobbe/attachments/`: attachments and documents (milestone 9, D70 to D77); the package docstring shows the flow. `kinds.py` (file format and kind, the one place deciding them), `content.py` (an attachment's bytes back from the MBOX file: `read_attachment`, `attachment_source`, `document_sources`), `documents.py` (`refresh_documents` in finalize), `extract/` (text extraction per format family, sandboxed in a child process), `phase.py` (the import's attachments phase)
- `src/mailrobbe/preview/`: attachments shown in the browser (D120 to D124); the package docstring shows the five kinds. `kinds.py` (`preview_kind`, the one place deciding image, pdf, html, audio or video), `api/previews.py` serves the converted HTML and the media with Range requests; the PDF viewer is a bundle of its own (`frontend/src/viewer/`, pdf.js on an opaque origin) that `api/frontend.py` serves below `/viewer/` with its own policy
- `src/mailrobbe/timeline/`: timeline (milestone 11, D90 to D95), pure helpers of `api/timeline.py`: `buckets.py` (axis, bucket choice, days summed to weeks and months), `marks.py` (moving mean, high and low buckets, silence)
- `src/mailrobbe/persons/`: persons (milestone 5, D28 to D33); `roots.py` (root person of an address), `stats.py` (`person_stats`, `person_year`), `suggestions.py` (alias suggestions), `merge.py` (merge, unmerge, dismiss)
- `src/mailrobbe/export/`: export for lawyers and archives (D62, D63); `records.py` (what an export reads per mail), `pdf.py` (one mail as PDF with the DejaVu font in `fonts/`), `manifest.py`, `readme.py` (LIESMICH.txt), `bundle.py` (the streamed ZIP with SHA256SUMS)
- `src/mailrobbe/themes.toml`: the research themes with word fields and search templates (D64), read through `themes.py` (`load_themes`); the one source for later milestones too
- `src/mailrobbe/jobs.py`: runs of `mailrobbe import` and `mailrobbe dkim` in the `job` table (D46, D47): lock keys, options and live figures with their steps (D110), `begin_job`/`report_job`/`end_job` for the runs, `request_stop`/`latest_job`/`job_alive` for the API, `db_activity`/`end_leftovers` on `pg_stat_activity` (D111, D113)
- `src/mailrobbe/jobrun.py`: the run side of both commands: `job_run` (lock, job row, 2 s reports, stop on Ctrl-C, SIGTERM or the dashboard's request), `RateWindow`, `Steps` (`job.steps`: every step of a run with its counter, rate and estimate, D110)
- `src/mailrobbe/bench.py`: `mailrobbe bench`, response times of a running server's API (D51); procedure and results of the load test in [docs/LOADTEST.md](docs/LOADTEST.md)
- `src/mailrobbe/aggregates.py`: aggregation tables; `refresh_aggregates` runs edges, person figures, alias suggestions and `global_stats` in that order (finalize, `mailrobbe dkim`, merges; D33), and `global_stats` is also refreshed lazily by the API (D19)
- `src/mailrobbe/cli.py`: the `mailrobbe` command (`serve`, `migrate`, `generate`, `import`, `dkim`, `graph`, `bench`)
- `tests/`: mirrors the package; `tests/db` needs PostgreSQL

## Commands

```sh
uv sync                                  # install everything, including dev tools
uv run ruff check . && uv run ruff format --check .
uv run mypy                              # strict, covers src and tests
uv run pytest                            # DB tests skip without a test database
uv run pytest -m "not slow"              # quick run while iterating
uv run mailrobbe generate --mails 10000 # test data into data/mbox (see --help)
docker compose up -d --build             # Postgres + backend on http://127.0.0.1:8000
docker compose run --rm backend mailrobbe import   # importer; Ctrl-C pauses, the next run resumes
uv run mailrobbe dkim --help             # DKIM recheck of imported mails (D13)
uv run mailrobbe graph --help            # recompute edges, full GraphML export for Gephi (D38)
uv run mailrobbe bench --rounds 5        # API response times against a running server (D51)
cd frontend && npm ci                    # Node 22; then, inside frontend/:
npm run dev                              # Vite on :5173, /api proxied to 127.0.0.1:8000
npm run lint && npm run format:check && npm run typecheck && npm test
npm run build                            # frontend/dist, served by `mailrobbe serve`
```

Database tests need `MAILROBBE_TEST_DATABASE_URL`, for example `postgresql+asyncpg://mailrobbe:mailrobbe@127.0.0.1:5432/mailrobbe` against `docker compose up -d db`. The tests create and drop their own temporary database on that server and never touch the one they connect to. CI runs them against a Postgres 16 service and sets `MAILROBBE_REQUIRE_DB=1`, which turns the skip into a failure.

Check exit codes explicitly (`uv run mypy; echo $?`); piping into `tail` hides a red run.

## Conventions

- Code, comments, commit messages, CLI output and logs in English. Web UI texts in German.
- No emojis. No model names anywhere in the repository (code, docs, commits, PR texts).
- Clean and lean: no speculative abstractions, no new dependencies without a reason in the PR.
- Schema changes are new Alembic revisions written by hand; `db/models.py` must match them, and the drift test in `tests/db` fails otherwise. `offset`/`length` are spelled `byte_offset`/`byte_length` because OFFSET is reserved in SQL.
- Raw mails never go into the database; it stores metadata, byte offsets, the full text index and aggregations (SPEC 2 and 6). Every view must stay fast at 400,000 mails.
- Generated domains use reserved TLDs (`.example`, `.test`) so nothing ever queries real DNS for them.
- Generator output is deterministic: the same options give byte-identical files whatever `--jobs` is. Every random choice comes from `stage_rng`/`derive_seed`; never use the global `random`, wall-clock time or `uuid4` for generated content.
- `_generator/manifest.jsonl` is the ground truth for every generated mail (file, offset, length, SHA-256, expected DKIM result per signature, faults, duplicates); importer and DKIM tests should assert against it.

## Target machine

The import runs on macOS (Docker Desktop) or Linux with about 10 GB RAM for Postgres and the importer together. Compose defaults follow that: `shared_buffers` 2 GB, `maintenance_work_mem` 1 GB, importer workers `min(8, CPU count)` (`MAILROBBE_IMPORT_WORKERS`). Bind mounts are slow on macOS, so the importer must read MBOX files sequentially and in large blocks. All values can be overridden in `.env`.
