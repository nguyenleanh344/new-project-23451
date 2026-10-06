"""Business logic for borehole records (in-memory store fed by the repository)."""

from __future__ import annotations

from datetime import datetime, timezone

from app.models import BoreHoleRecord, DepthSort, RecordCounts
from app.repository import CsvBoreHoleRepository


class RecordNotFoundError(KeyError):
    """Raised when a record id is not in the in-memory store."""

    def __init__(self, record_id: str) -> None:
        self.record_id = record_id
        self.message = f"Record '{record_id}' not found"
        super().__init__(self.message)

    def __str__(self) -> str:  # KeyError.__str__ would wrap the message in quotes
        return self.message


class BoreHoleService:
    """Service layer mirroring the user's required functions.

    User name              -> Python name
    fetchBoreHoleRecords   -> fetch_borehole_records
    searchBoreHole         -> search_borehole
    getBoreHoleRecordsList -> get_borehole_records_list
    update borehole status -> update_borehole_status
    getRecordDetail        -> get_record_detail
    getFilterRecordCount   -> get_filtered_record_count
    """

    def __init__(self, repository: CsvBoreHoleRepository) -> None:
        self._repository = repository
        self._records: list[BoreHoleRecord] = []  # empty until fetch_borehole_records()

    @property
    def repository(self) -> CsvBoreHoleRepository:
        return self._repository

    # -- loading ---------------------------------------------------------

    def fetch_borehole_records(self) -> list[BoreHoleRecord]:
        """Reload all records from the repository ("fetch from API", mocked by CSV).

        Replaces the in-memory store, so any status updates made with
        :meth:`update_borehole_status` since the last fetch are discarded.
        Returns a copy of the freshly loaded list.
        """
        self._records = list(self._repository.load())
        return list(self._records)

    def get_all_records(self) -> list[BoreHoleRecord]:
        """Copy of the in-memory list in original (CSV) order."""
        return list(self._records)

    # -- querying --------------------------------------------------------

    def search_borehole(self, search_value: str) -> list[BoreHoleRecord]:
        """Case-insensitive substring match on record_id OR operator.

        ``search_value`` is stripped; empty / whitespace returns all records.
        Original order is preserved.
        """
        needle = ("" if search_value is None else str(search_value)).strip().lower()
        if not needle:
            return list(self._records)
        return [
            record
            for record in self._records
            if needle in record.record_id.lower() or needle in record.operator.lower()
        ]

    def get_borehole_records_list(
        self,
        state: bool | None,
        depth: str | DepthSort | None,
        search_value: str | None = None,
    ) -> list[BoreHoleRecord]:
        """Search (optional), then filter by state (None = all), then sort by depth.

        ``depth`` is ``"highToLow"`` / ``"lowToHigh"`` (or a :class:`DepthSort`);
        ``None`` keeps the original order. The sort is stable and ties are
        broken by ``record_id`` ascending. An invalid depth string raises
        ``ValueError``.
        """
        sort = self._coerce_depth(depth)
        records = (
            self.search_borehole(search_value)
            if search_value is not None
            else list(self._records)
        )
        if state is not None:
            records = [record for record in records if record.state == state]
        if sort is DepthSort.HIGH_TO_LOW:
            records.sort(key=lambda record: (-record.depth, record.record_id))
        elif sort is DepthSort.LOW_TO_HIGH:
            records.sort(key=lambda record: (record.depth, record.record_id))
        return records

    def get_record_detail(self, record_id: str) -> BoreHoleRecord:
        """Return the record with the given id (case-insensitive exact match)."""
        return self._find(record_id)

    def get_filtered_record_count(
        self,
        state: bool | None,
        depth: str | DepthSort | None,
        search_value: str | None = None,
    ) -> RecordCounts:
        """Counts: total/verified/review over all records; filtered/avg over the filtered set."""
        filtered = self.get_borehole_records_list(state, depth, search_value)
        total = len(self._records)
        verified = sum(1 for record in self._records if record.state)
        average = (
            round(sum(record.depth for record in filtered) / len(filtered), 2)
            if filtered
            else 0.0
        )
        return RecordCounts(
            total_count=total,
            filtered_count=len(filtered),
            verified_count=verified,
            review_count=total - verified,
            average_depth=average,
        )

    # -- mutation --------------------------------------------------------

    def update_borehole_status(self, record_id: str, state: bool) -> BoreHoleRecord:
        """Set ``state`` and bump ``last_updated`` on the in-memory record.

        Nothing is written back to the CSV. Raises :class:`RecordNotFoundError`.
        """
        record = self._find(record_id)
        record.state = bool(state)
        record.last_updated = datetime.now(timezone.utc)
        return record

    # -- helpers ---------------------------------------------------------

    def _find(self, record_id: str) -> BoreHoleRecord:
        wanted = ("" if record_id is None else str(record_id)).lower()
        for record in self._records:
            if record.record_id.lower() == wanted:
                return record
        raise RecordNotFoundError(record_id)

    @staticmethod
    def _coerce_depth(depth: str | DepthSort | None) -> DepthSort | None:
        if depth is None:
            return None
        if isinstance(depth, DepthSort):
            return depth
        try:
            return DepthSort(str(depth).strip())
        except ValueError:
            raise ValueError(
                f"Invalid depth sort {depth!r}; expected one of: "
                + ", ".join(option.value for option in DepthSort)
            ) from None
