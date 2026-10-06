"""CSV-backed repository: the mocked "remote API" for borehole records."""

from __future__ import annotations

import csv
import math
from datetime import date, datetime, time, timezone
from pathlib import Path

from app.models import BoreHoleRecord

_TRUE_TOKENS = frozenset({"verified", "true", "1", "yes"})
_FALSE_TOKENS = frozenset({"review", "false", "0", "no"})

CSV_COLUMNS: tuple[str, ...] = (
    "recordId",
    "machine",
    "operator",
    "position",
    "depth",
    "plumb",
    "state",
    "dateCreated",
    "lastUpdated",
)
_REQUIRED_COLUMNS = frozenset(CSV_COLUMNS) - {"lastUpdated"}


def parse_state(value: str) -> bool:
    """Parse a CSV state token into a bool.

    Accepts ``Verified``/``Review`` and ``true``/``false``, ``1``/``0``,
    ``yes``/``no`` case-insensitively. Raises ``ValueError`` otherwise.
    """
    token = ("" if value is None else str(value)).strip().lower()
    if token in _TRUE_TOKENS:
        return True
    if token in _FALSE_TOKENS:
        return False
    raise ValueError(
        f"Unrecognised state value {value!r}; expected Verified/Review, "
        "true/false, 1/0 or yes/no"
    )


def _parse_last_updated(value: str | None, date_created: date) -> datetime:
    """Parse ``lastUpdated``; blank defaults to ``dateCreated`` at midnight UTC."""
    token = ("" if value is None else str(value)).strip()
    if not token:
        return datetime.combine(date_created, time.min, tzinfo=timezone.utc)
    parsed = datetime.fromisoformat(token)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _cell(row: dict[str, str | None], column: str) -> str:
    value = row.get(column)
    return "" if value is None else str(value).strip()


def _parse_depth(value: str) -> float:
    """Parse ``depth`` as a plain, finite number of metres.

    ``float()`` happily accepts ``nan``/``inf``/``Infinity`` (and overflows such
    as ``1e400`` become ``inf``); those are not valid depths and would serialise
    as JSON ``null``, so they are rejected as malformed.
    """
    depth = float(value)
    if not math.isfinite(depth):
        raise ValueError(f"depth must be a finite number, got {value!r}")
    return depth


def _parse_row(row: dict[str, str | None]) -> BoreHoleRecord:
    record_id = _cell(row, "recordId")
    if not record_id:
        raise ValueError("recordId is empty")
    date_created = date.fromisoformat(_cell(row, "dateCreated"))
    depth = _parse_depth(_cell(row, "depth"))
    return BoreHoleRecord(
        record_id=record_id,
        machine=_cell(row, "machine"),
        operator=_cell(row, "operator"),
        position=_cell(row, "position"),
        depth=depth,
        plumb=_cell(row, "plumb"),
        state=parse_state(_cell(row, "state")),
        date_created=date_created,
        last_updated=_parse_last_updated(row.get("lastUpdated"), date_created),
    )


class CsvBoreHoleRepository:
    """Reads borehole records from a CSV file. Read-only; never writes."""

    def __init__(self, csv_path: str | Path) -> None:
        self._csv_path = Path(csv_path)

    @property
    def csv_path(self) -> Path:
        return self._csv_path

    def load(self) -> list[BoreHoleRecord]:
        """Read every record from the CSV.

        Raises ``FileNotFoundError`` if the file is missing and ``ValueError``
        (mentioning the row number) on a malformed row. Fully blank lines are
        skipped.
        """
        path = self._csv_path
        if not path.is_file():
            raise FileNotFoundError(f"CSV file not found: {path}")

        records: list[BoreHoleRecord] = []
        with path.open(newline="", encoding="utf-8-sig") as handle:  # utf-8-sig also strips an Excel BOM
            reader = csv.DictReader(handle)
            fieldnames = [name.strip() for name in (reader.fieldnames or [])]
            if not fieldnames:
                return records  # empty file: no header, no rows
            missing = _REQUIRED_COLUMNS.difference(fieldnames)
            if missing:
                raise ValueError(
                    f"CSV file {path} is missing required column(s): "
                    f"{', '.join(sorted(missing))}"
                )
            reader.fieldnames = fieldnames

            row_number = 0
            for row in reader:
                row_number += 1
                if all(not _cell(row, column) for column in fieldnames):
                    continue  # fully blank line (e.g. only separators)
                try:
                    records.append(_parse_row(row))
                except (ValueError, TypeError) as exc:
                    raise ValueError(
                        f"Malformed row {row_number} (line {reader.line_num}) "
                        f"in {path}: {exc}"
                    ) from exc
        return records
