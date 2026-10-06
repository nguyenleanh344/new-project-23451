"""Pydantic models and enums for the BoreHole Records API.

All wire models serialise with camelCase keys (recordId, dateCreated, ...).
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, computed_field
from pydantic.alias_generators import to_camel


class DepthSort(str, Enum):
    """Sort direction for the depth column."""

    HIGH_TO_LOW = "highToLow"
    LOW_TO_HIGH = "lowToHigh"


class StateFilter(str, Enum):
    """State filter accepted by the list / count endpoints."""

    ALL = "all"
    VERIFIED = "Verified"
    REVIEW = "Review"

    def to_bool(self) -> bool | None:
        """Map the filter to the boolean ``state`` field; ``ALL`` maps to ``None``."""
        if self is StateFilter.VERIFIED:
            return True
        if self is StateFilter.REVIEW:
            return False
        return None

    @classmethod
    def parse(cls, value: str) -> StateFilter:
        """Parse a user supplied filter token, case-insensitively.

        Accepts ``all``, ``Verified``, ``Review`` and the booleans ``true`` /
        ``false`` (true -> VERIFIED, false -> REVIEW). Raises ``ValueError``
        for anything else.
        """
        token = str(value).strip().lower()
        mapping = {
            "all": cls.ALL,
            "verified": cls.VERIFIED,
            "true": cls.VERIFIED,
            "review": cls.REVIEW,
            "false": cls.REVIEW,
        }
        try:
            return mapping[token]
        except KeyError:
            raise ValueError(
                f"Invalid state filter {value!r}; expected one of: "
                "all, Verified, Review, true, false"
            ) from None


class CamelModel(BaseModel):
    """Base model: camelCase on the wire, snake_case in Python."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        serialize_by_alias=True,
    )


class BoreHoleRecord(CamelModel):
    """A single borehole record."""

    record_id: str = Field(description="Unique record identifier, e.g. GEO-2025-07-0417")
    machine: str = Field(description="Drilling machine identifier")
    operator: str = Field(description="Operator name")
    position: str = Field(description="Position as recorded, e.g. 52.4042° N")
    depth: float = Field(description="Depth in metres")
    plumb: str = Field(description="Plumb / verticality as recorded")
    state: bool = Field(description="True = Verified, False = Review")
    date_created: date = Field(description="Date the record was created")
    last_updated: datetime = Field(description="Timestamp of the last status update")

    @computed_field(alias="stateLabel", description="Human readable state")
    @property
    def state_label(self) -> str:
        return "Verified" if self.state else "Review"


class UpdateStatusRequest(CamelModel):
    """Body of ``PUT /boreHoleRecords/updateStatus``."""

    record_id: str = Field(min_length=1, description="Record to update")
    state: bool = Field(description="New state: true = Verified, false = Review")


class RecordCounts(CamelModel):
    """Counts returned by ``GET /boreHoleRecords/counts``.

    ``totalCount`` / ``verifiedCount`` / ``reviewCount`` are over ALL loaded
    records; ``filteredCount`` and ``averageDepth`` are over the filtered
    (+ searched) set. ``averageDepth`` is rounded to 2 dp and is 0.0 when the
    filtered set is empty.
    """

    total_count: int
    filtered_count: int
    verified_count: int
    review_count: int
    average_depth: float


class FetchResult(BaseModel):
    """Result of ``/fetchData``."""

    count: int
    source: str = "csv"
    path: str


class ErrorResponse(BaseModel):
    """Standard error body (``{"detail": "..."}``)."""

    detail: str


class HealthResponse(BaseModel):
    """Body of ``GET /health``."""

    status: str
    records: int
