# Mailspider

Local web software that imports large MBOX archives (target: about 400,000 mails, 280 GB in roughly 70 files), verifies DKIM, groups mails by person and shows a relationship graph. The specification is [docs/SPEC.md](docs/SPEC.md) (German); the UI prototype is [docs/mockup/](docs/mockup/). Read the spec before changing behaviour; its milestones (section 8) are the plan.

## Stack

- Python 3.12, managed with uv (`pyproject.toml`, `uv.lock`)
- FastAPI, SQLAlchemy 2 async with asyncpg, Pydantic v2 and pydantic-settings
- PostgreSQL 16 with `tsvector` full text search and `pg_trgm`; schema via Alembic
- dkimpy and dnspython for DKIM; cryptography for generating test keys
- ruff (lint and format), mypy (strict), pytest with pytest-asyncio
- Docker Compose for Postgres and the backend

## Layout

- `src/mailspider/enums.py`: shared status vocabularies (`DkimStatus`, `best_dkim_status`, ...)
- `src/mailspider/db/`: ORM models mirroring the migrations, engine and session helpers
- `src/mailspider/migrations/`: Alembic environment and hand-written revisions (the schema's source of truth)
- `src/mailspider/api/`: FastAPI app (`create_app`), currently `GET /api/health`
- `src/mailspider/generator/`: synthetic MBOX test data (SPEC 3.6); `model.py` documents the stage pipeline
- `src/mailspider/dkim/`: DKIM support; `override.py` is the DNS override table for tests and generated data
- `src/mailspider/cli.py`: the `mailspider` command (`serve`, `migrate`, `generate`, `import`)
- `tests/`: mirrors the package; `tests/db` needs PostgreSQL

## Commands

```sh
uv sync                                  # install everything, including dev tools
uv run ruff check . && uv run ruff format --check .
uv run mypy                              # strict, covers src and tests
uv run pytest                            # DB tests skip without a test database
uv run mailspider generate --mails 10000 # test data into data/mbox (see --help)
docker compose up -d --build             # Postgres + backend on http://127.0.0.1:8000
docker compose run --rm backend mailspider import   # importer (milestone 2)
```

Database tests need `MAILSPIDER_TEST_DATABASE_URL`, for example `postgresql+asyncpg://mailspider:mailspider@127.0.0.1:5432/mailspider` against `docker compose up -d db`. The tests create and drop their own temporary database on that server and never touch the one they connect to. CI runs them against a Postgres 16 service and sets `MAILSPIDER_REQUIRE_DB=1`, which turns the skip into a failure.

Check exit codes explicitly (`uv run mypy; echo $?`); piping into `tail` hides a red run.

## Conventions

- Code, comments, commit messages, CLI output and logs in English. Web UI texts in German.
- No emojis. No model names anywhere in the repository (code, docs, commits, PR texts).
- Clean and lean: no speculative abstractions, no new dependencies without a reason in the PR.
- Schema changes are new Alembic revisions written by hand; `db/models.py` must match them, and the drift test in `tests/db` fails otherwise. `offset`/`length` are spelled `byte_offset`/`byte_length` because OFFSET is reserved in SQL.
- Raw mails never go into the database; it stores metadata, byte offsets, the full text index and aggregations (SPEC 2 and 6). Every view must stay fast at 400,000 mails.
- Generated domains use reserved TLDs (`.example`, `.test`) so nothing ever queries real DNS for them.

## Target machine

The import runs on macOS (Docker Desktop) or Linux with about 10 GB RAM for Postgres and the importer together. Compose defaults follow that: `shared_buffers` 2 GB, `maintenance_work_mem` 1 GB, importer workers `min(8, CPU count)` (`MAILSPIDER_IMPORT_WORKERS`). Bind mounts are slow on macOS, so the importer must read MBOX files sequentially and in large blocks. All values can be overridden in `.env`.
