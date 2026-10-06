"""Shared fixtures.

Every fixture is function-scoped: each test gets its own repository, service
and FastAPI app wired to the same read-only fixture CSV, so in-memory status
updates made by one test can never leak into another.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.repository import CsvBoreHoleRepository
from app.services import BoreHoleService

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"

# The fixture CSV, in file order. Tests assert against these constants so an
# accidental edit to the CSV fails loudly instead of silently shifting results.
FIXTURE_IDS = [
    "GEO-2025-07-0417",  # Jack Mercer      3.42  Verified
    "GEO-2025-07-0416",  # Jack Mercer      3.38  Verified  (blank lastUpdated)
    "GEO-2025-07-0415",  # Lukas Weber      3.44  Verified
    "GEO-2025-07-0414",  # Lukas Weber      3.42  Review    (depth ties with 0417)
    "GEO-2025-07-0413",  # Priya Natarajan  4.05  Verified
    "GEO-2025-07-0412",  # Priya Natarajan  2.92  Review
]
VERIFIED_IDS = ["GEO-2025-07-0417", "GEO-2025-07-0416", "GEO-2025-07-0415", "GEO-2025-07-0413"]
REVIEW_IDS = ["GEO-2025-07-0414", "GEO-2025-07-0412"]
# Depth descending; the 3.42 tie is broken by recordId ascending (0414 < 0417),
# which is the *opposite* of their CSV order, so plain stability is not enough.
HIGH_TO_LOW_IDS = [
    "GEO-2025-07-0413",  # 4.05
    "GEO-2025-07-0415",  # 3.44
    "GEO-2025-07-0414",  # 3.42
    "GEO-2025-07-0417",  # 3.42
    "GEO-2025-07-0416",  # 3.38
    "GEO-2025-07-0412",  # 2.92
]
LOW_TO_HIGH_IDS = [
    "GEO-2025-07-0412",  # 2.92
    "GEO-2025-07-0416",  # 3.38
    "GEO-2025-07-0414",  # 3.42
    "GEO-2025-07-0417",  # 3.42
    "GEO-2025-07-0415",  # 3.44
    "GEO-2025-07-0413",  # 4.05
]
DEPTHS = {
    "GEO-2025-07-0417": 3.42,
    "GEO-2025-07-0416": 3.38,
    "GEO-2025-07-0415": 3.44,
    "GEO-2025-07-0414": 3.42,
    "GEO-2025-07-0413": 4.05,
    "GEO-2025-07-0412": 2.92,
}
AVERAGE_DEPTH_ALL = 3.44  # 20.63 / 6 = 3.43833... -> rounded to 2 dp
AVERAGE_DEPTH_VERIFIED = 3.57  # 14.29 / 4 = 3.5725 -> 3.57
AVERAGE_DEPTH_REVIEW = 3.17  # 6.34 / 2 = 3.17

CSV_HEADER = "recordId,machine,operator,position,depth,plumb,state,dateCreated,lastUpdated"


@pytest.fixture
def fixture_csv_path() -> Path:
    """Absolute path to the 6-row fixture CSV (independent of the CWD)."""
    path = FIXTURES_DIR / "boreholes_test.csv"
    assert path.is_file(), f"fixture CSV missing: {path}"
    return path


@pytest.fixture
def repository(fixture_csv_path: Path) -> CsvBoreHoleRepository:
    return CsvBoreHoleRepository(fixture_csv_path)


@pytest.fixture
def service(repository: CsvBoreHoleRepository) -> BoreHoleService:
    """A fresh service with the fixture records already loaded."""
    svc = BoreHoleService(repository)
    svc.fetch_borehole_records()
    return svc


@pytest.fixture
def client(fixture_csv_path: Path) -> Iterator[TestClient]:
    """TestClient on a brand-new app bound to the fixture CSV; lifespan runs."""
    app = create_app(csv_path=fixture_csv_path)
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def write_csv(tmp_path: Path) -> Callable[[str, str], Path]:
    """Factory writing an ad-hoc CSV (header + body text) into a temp dir."""

    def _write(body: str, name: str = "boreholes.csv") -> Path:
        path = tmp_path / name
        path.write_text(f"{CSV_HEADER}\n{body}", encoding="utf-8")
        return path

    return _write
