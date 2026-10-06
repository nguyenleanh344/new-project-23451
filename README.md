# BoreHole Records

A small FastAPI service plus a plain HTML/CSS/JS frontend for browsing, filtering,
searching and reviewing borehole records. Storage is a **mock**: records are read from
a CSV file into memory, and status updates only change the in-memory copy.

## Overview

- **Backend** — FastAPI app (`app/`) exposing the borehole API under `/boreHoleRecords`,
  a mocked "fetch from remote" endpoint (`/fetchData`) and a `/health` check.
- **Storage** — `CsvBoreHoleRepository` reads `data/boreholes.csv`; `BoreHoleService`
  keeps the records in memory and implements search, filter, sort, detail, counts and
  status updates.
- **Frontend** — `static/` (vanilla JS, no build step, no CDN) served by the same app at
  `/`: count badges, state filter, depth sort, debounced search, a records table with an
  **Open** action that shows the record detail, and a toggle to mark a record as
  Verified / Review.
- **Tests** — pytest suite under `tests/` covering the repository, the service and the
  HTTP API.

Record schema: `recordId` (str), `machine` (str), `operator` (str), `position` (str),
`depth` (float, metres), `plumb` (str), `state` (bool: `true` = Verified, `false` =
Review), plus the metadata `dateCreated` (date) and `lastUpdated` (datetime). Responses
also carry a derived `stateLabel` ("Verified" / "Review").

## Requirements

- Python 3.12+ (developed on 3.14)
- Packages listed in `requirements.txt` (FastAPI, Uvicorn, Pydantic v2, httpx / httpx2, pytest)
- Optional: [`uv`](https://github.com/astral-sh/uv) for faster installs

## Setup

All commands are run from the project root.

**With uv:**

```bash
uv venv .venv
uv pip install --python .venv/bin/python -r requirements.txt
```

**With the standard library venv:**

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

Always use the interpreter inside `.venv` (`.venv/bin/python`, `.venv/bin/uvicorn`);
there is no need to activate the environment.

## Run

```bash
.venv/bin/uvicorn app.main:app --reload
```

- UI: <http://127.0.0.1:8000/>
- Interactive API docs (Swagger UI): <http://127.0.0.1:8000/docs>
- OpenAPI schema: <http://127.0.0.1:8000/openapi.json>

Use `--port <n>` to run on a different port.

## Test

```bash
.venv/bin/python -m pytest -q
```

`pytest.ini` sets `testpaths = tests` and `pythonpath = .`, so the command works from
the project root without any extra configuration.

## Project layout

```
README.md
requirements.txt
pytest.ini
.gitignore
data/boreholes.csv                 # seed data (13 rows)
app/__init__.py
app/main.py                        # create_app() factory + module-level `app`; serves static/
app/models.py                      # Pydantic models + enums (camelCase on the wire)
app/repository.py                  # CsvBoreHoleRepository (read-only CSV access)
app/services.py                    # BoreHoleService + RecordNotFoundError
app/dependencies.py                # get_service() dependency (singleton on app.state)
app/routers/__init__.py
app/routers/boreholes.py           # /boreHoleRecords routes, /fetchData, /health
static/index.html                  # frontend markup
static/styles.css                  # frontend styles
static/app.js                      # frontend logic (vanilla JS)
tests/__init__.py
tests/conftest.py                  # fixtures: fixture CSV, repository, service, TestClient
tests/fixtures/boreholes_test.csv  # 6-row test data set
tests/test_repository.py
tests/test_services.py
tests/test_api.py
```

## API

All JSON keys are camelCase. Errors use the FastAPI shape `{"detail": "..."}`
(validation errors return a list of error objects under `detail`).

| Method | Path | Parameters | Response |
| --- | --- | --- | --- |
| `GET` / `POST` | `/fetchData` | – | `FetchResult` `{count, source: "csv", path}`. Reloads the CSV into memory (discards in-memory status changes). `500` if the CSV is missing or malformed. |
| `GET` | `/boreHoleRecords` | `state` = `all` (default) \| `Verified` \| `Review` (case-insensitive; `true` / `false` also accepted), `depth` = `highToLow` \| `lowToHigh` (omit = CSV order), `q` = search text (record ID or operator) | `BoreHoleRecord[]`. `422` on an invalid `state` or `depth`. |
| `GET` | `/boreHoleRecords/search` | `q` (required; empty returns all) | `BoreHoleRecord[]` |
| `GET` | `/boreHoleRecords/counts` | `state`, `depth`, `q` as above | `RecordCounts` `{totalCount, filteredCount, verifiedCount, reviewCount, averageDepth}` |
| `PUT` | `/boreHoleRecords/updateStatus` | JSON body `{"recordId": "GEO-2025-07-0417", "state": false}` | Updated `BoreHoleRecord`. `404` if the ID is unknown, `422` on a bad body. |
| `GET` | `/boreHoleRecords/{recordId}` | path `recordId` (case-insensitive) | `BoreHoleRecord`. `404` if unknown. |
| `GET` | `/health` | – | `{"status": "ok", "records": <n>}` |
| `GET` | `/` | – | The frontend (`static/index.html`); assets under `/static/` |

`BoreHoleRecord` example:

```json
{
  "recordId": "GEO-2025-07-0417",
  "machine": "TND-DD-0114",
  "operator": "Jack Mercer",
  "position": "52.4042° N",
  "depth": 3.42,
  "plumb": "0.04° verticality",
  "state": true,
  "dateCreated": "2025-07-18",
  "lastUpdated": "2025-07-18T00:00:00Z",
  "stateLabel": "Verified"
}
```

`RecordCounts` semantics: `totalCount`, `verifiedCount` and `reviewCount` are over
**all** loaded records; `filteredCount` and `averageDepth` (2 dp, `0.0` when nothing
matches) are over the filtered + searched set.

Examples:

```bash
curl "http://127.0.0.1:8000/boreHoleRecords?state=Review&depth=lowToHigh&q=weber"
curl "http://127.0.0.1:8000/boreHoleRecords/counts?state=Verified"
curl -X PUT -H "Content-Type: application/json" \
     -d '{"recordId": "GEO-2025-07-0417", "state": false}' \
     http://127.0.0.1:8000/boreHoleRecords/updateStatus
curl -X POST http://127.0.0.1:8000/fetchData
```

## Function mapping

The functions from the original requirements map onto `BoreHoleService`
(`app/services.py`) and the routes in `app/routers/boreholes.py`:

| Requested function | Python implementation | HTTP route |
| --- | --- | --- |
| `fetchBoreHoleRecords()` | `BoreHoleService.fetch_borehole_records()` | `GET` / `POST /fetchData` |
| `searchBoreHole(searchValue)` | `BoreHoleService.search_borehole(search_value)` | `GET /boreHoleRecords/search?q=` (also `q=` on the list and counts routes) |
| `getBoreHoleRecordsList(state, depth)` | `BoreHoleService.get_borehole_records_list(state, depth, search_value=None)` | `GET /boreHoleRecords?state=&depth=&q=` |
| update borehole status `(recordId, state)` | `BoreHoleService.update_borehole_status(record_id, state)` | `PUT /boreHoleRecords/updateStatus` |
| `getRecordDetail(recordId)` | `BoreHoleService.get_record_detail(record_id)` | `GET /boreHoleRecords/{recordId}` |
| `getFilterRecordCount()` | `BoreHoleService.get_filtered_record_count(state, depth, search_value=None)` | `GET /boreHoleRecords/counts?state=&depth=&q=` |

Unknown record IDs raise `app.services.RecordNotFoundError` (a `KeyError` subclass),
which the routes translate into `404 {"detail": "Record '<id>' not found"}`.

## Data format

`data/boreholes.csv` is UTF-8 with this exact header:

```
recordId,machine,operator,position,depth,plumb,state,dateCreated,lastUpdated
```

| Column | Type | Notes |
| --- | --- | --- |
| `recordId` | text | Unique ID, e.g. `GEO-2025-07-0417` |
| `machine` | text | e.g. `TND-DD-0114` |
| `operator` | text | e.g. `Jack Mercer` |
| `position` | text | As recorded, e.g. `52.4042° N` |
| `depth` | number | Metres as a plain number (`3.42`, **not** `3.42 m`) |
| `plumb` | text | As recorded, e.g. `0.04° verticality` |
| `state` | `Verified` / `Review` | `true`/`false`, `1`/`0` and `yes`/`no` are also accepted (case-insensitive) |
| `dateCreated` | ISO date | `2025-07-18` |
| `lastUpdated` | ISO 8601 datetime | `2025-07-18T00:00:00+00:00`; leave blank to default to `dateCreated` at midnight UTC |

To add a record, append a line in the same format, for example:

```
GEO-2025-07-0418,TND-DD-0121,Sofia Alvarez,52.4050° N,3.60,0.05° verticality,Review,2025-07-19,
```

Then click **Reload from CSV** in the UI (or call `/fetchData`) — or restart the
server. Fully blank lines are skipped; a malformed row (for example a non-numeric
depth) makes the load fail with an error naming the row.

## Notes

- **Mock storage.** The CSV stands in for a remote API. `fetchBoreHoleRecords` /
  `/fetchData` simply re-reads the file and replaces the in-memory list.
- **Updates are not persisted.** `PUT /boreHoleRecords/updateStatus` changes `state`
  and `lastUpdated` on the in-memory record only; nothing is written back to the CSV.
  Reloading (via `/fetchData`, the **Reload from CSV** button, or a restart) discards
  those changes.
- **Pointing at a different CSV.** Set `BOREHOLE_CSV_PATH` before starting the server,
  e.g. `BOREHOLE_CSV_PATH=/path/to/other.csv .venv/bin/uvicorn app.main:app --reload`.
  The default is `data/boreholes.csv` next to the `app` package, independent of the
  current working directory. If the file is missing at startup the app still starts
  with zero records and logs a warning; `/fetchData` then returns `500` until the file
  exists.
- **Frontend.** Served from `static/` by FastAPI, works offline (no CDN assets). The
  **Open** action in each row, or clicking the row itself, opens the record detail
  panel; the button inside it toggles the record between Verified and Review.
