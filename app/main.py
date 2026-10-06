"""Application factory for the BoreHole Records API.

Run with: ``uvicorn app.main:app --reload``
"""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.repository import CsvBoreHoleRepository
from app.routers import boreholes
from app.services import BoreHoleService

logger = logging.getLogger(__name__)

PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_DIR.parent
DEFAULT_CSV_PATH = PROJECT_ROOT / "data" / "boreholes.csv"
STATIC_DIR = PROJECT_ROOT / "static"
CSV_PATH_ENV_VAR = "BOREHOLE_CSV_PATH"


def resolve_csv_path(csv_path: str | Path | None = None) -> Path:
    """Explicit argument, else ``$BOREHOLE_CSV_PATH``, else ``<project>/data/boreholes.csv``.

    The default is resolved relative to the ``app`` package, never the CWD.
    """
    if csv_path is not None:
        return Path(csv_path)
    env_value = os.environ.get(CSV_PATH_ENV_VAR, "").strip()
    if env_value:
        return Path(env_value)
    return DEFAULT_CSV_PATH


def create_app(csv_path: str | Path | None = None) -> FastAPI:
    """Build the FastAPI app wired to a CSV-backed service."""
    path = resolve_csv_path(csv_path)
    service = BoreHoleService(CsvBoreHoleRepository(path))

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        try:
            records = service.fetch_borehole_records()
        except FileNotFoundError:
            logger.warning("CSV file %s not found; starting with zero records", path)
        except ValueError as exc:
            logger.warning("CSV file %s is malformed (%s); starting with zero records", path, exc)
        else:
            logger.info("Loaded %d borehole record(s) from %s", len(records), path)
        yield

    app = FastAPI(
        title="BoreHole Records API",
        version="0.1.0",
        description="Mock borehole record store backed by a CSV file.",
        lifespan=lifespan,
    )
    app.state.service = service
    app.state.csv_path = path

    app.include_router(boreholes.router)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    return app


app = create_app()
