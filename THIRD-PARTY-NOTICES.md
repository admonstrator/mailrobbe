# Third-party components

Mailrobbe itself is licensed under the GNU AGPL-3.0 (see `LICENSE`). It uses the parts below under their own licences. The list names the licence families, not every transitive package; `uv.lock` and `frontend/package-lock.json` list the exact versions.

This file is no legal advice. Where a component's licence is marked with an asterisk, the entry comes from general knowledge and was not read off the package.

## Python packages

| Package | Licence |
|---|---|
| FastAPI, Pydantic, pydantic-settings, SQLAlchemy, Alembic, httpx, mammoth, msoffcrypto-tool, onnxruntime, onnx-asr, dkimpy* | MIT or BSD |
| uvicorn, numpy, pypdf, PyAV (`av`) | BSD |
| asyncpg, cryptography | Apache-2.0 (cryptography: Apache-2.0 or BSD) |
| dnspython | ISC |
| Pillow | HPND |
| fpdf2 | LGPL-3.0 |
| gmpy2 | LGPL-3.0-or-later (bundles GMP, LGPL and GPL) |

PyAV's wheels bundle FFmpeg libraries*, whose licence depends on the build (LGPL, or GPL with some codecs). fpdf2 and gmpy2 are used as installed libraries and can be replaced by the user.

## Frontend

| Package | Licence |
|---|---|
| React, React DOM, React Router, TanStack Query, Cytoscape.js | MIT |
| MapLibre GL JS, PMTiles, @protomaps/basemaps | BSD-3-Clause |
| pdf.js (`pdfjs-dist`) | Apache-2.0 |
| Inter, JetBrains Mono (`@fontsource-variable`) | SIL OFL-1.1 |
| Noto Sans (map glyphs in `frontend/public/map/fonts/`) | SIL OFL-1.1 |
| Map sprites (`frontend/public/map/sprites/`, from tangrams/icons) | MIT |
| DejaVu Sans (`src/mailrobbe/export/fonts/`) | Bitstream Vera licence |
| Logos of the payment services in the welcome note (from Simple Icons) | CC0-1.0; the marks belong to their owners |

## System packages in the image

| Package | Licence | Use |
|---|---|---|
| PostgreSQL 16 with pg_trgm | PostgreSQL License | database |
| Tesseract and its German and English data | Apache-2.0 | OCR |
| Poppler (`pdftoppm`) | GPL-2.0 or GPL-3.0 | page images, run as a separate process |
| 7-Zip (`7zip`) | LGPL with the unRAR restriction | archives, run as a separate process |

If a pre-built image is ever published, the source of its GPL and LGPL parts and these notices must go with it.

## Models and data

| Item | Licence | Note |
|---|---|---|
| Parakeet TDT 0.6B v3 (NVIDIA), int8 ONNX export | CC-BY-4.0 | downloaded on first use, not shipped |
| Silero VAD | MIT | |
| GeoNames | CC-BY-4.0 | place names, see `src/mailrobbe/places/data/SOURCES.md` |
| Natural Earth | public domain | overview map |
| OpenStreetMap data | ODbL | optional detail map, downloaded by the user, "(c) OpenStreetMap contributors" |

## Test data

The recordings and pictures in `src/mailrobbe/generator/media/` are synthetic (tones, test patterns, speech of a formant synthesizer); see the README there.
