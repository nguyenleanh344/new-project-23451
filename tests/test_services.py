"""Tests for BoreHoleService, RecordNotFoundError and StateFilter."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from app.models import BoreHoleRecord, DepthSort, RecordCounts, StateFilter
from app.repository import CsvBoreHoleRepository
from app.services import BoreHoleService, RecordNotFoundError
from tests.conftest import (
    AVERAGE_DEPTH_ALL,
    AVERAGE_DEPTH_REVIEW,
    AVERAGE_DEPTH_VERIFIED,
    FIXTURE_IDS,
    HIGH_TO_LOW_IDS,
    LOW_TO_HIGH_IDS,
    REVIEW_IDS,
    VERIFIED_IDS,
)

UTC = timezone.utc


def ids(records: list[BoreHoleRecord]) -> list[str]:
    return [r.record_id for r in records]


# -- fetch / get_all -----------------------------------------------------------------


def test_service_starts_empty_until_fetch(repository: CsvBoreHoleRepository) -> None:
    svc = BoreHoleService(repository)
    assert svc.get_all_records() == []
    assert svc.repository is repository


def test_fetch_borehole_records_loads_six_and_returns_them(
    repository: CsvBoreHoleRepository,
) -> None:
    svc = BoreHoleService(repository)
    fetched = svc.fetch_borehole_records()
    assert len(fetched) == 6
    assert ids(fetched) == FIXTURE_IDS
    assert ids(svc.get_all_records()) == FIXTURE_IDS


def test_fetch_returns_a_copy(service: BoreHoleService) -> None:
    fetched = service.fetch_borehole_records()
    fetched.clear()
    assert len(service.get_all_records()) == 6


def test_get_all_records_returns_a_fresh_copy_each_call(service: BoreHoleService) -> None:
    first = service.get_all_records()
    second = service.get_all_records()
    assert first == second
    assert first is not second
    first.append(first[0])
    first.pop(0)
    assert ids(service.get_all_records()) == FIXTURE_IDS


def test_list_results_are_copies(service: BoreHoleService) -> None:
    listed = service.get_borehole_records_list(None, None)
    listed.clear()
    assert len(service.get_all_records()) == 6
    found = service.search_borehole("")
    found.clear()
    assert len(service.get_all_records()) == 6


# -- search -------------------------------------------------------------------------


def test_search_by_full_record_id(service: BoreHoleService) -> None:
    assert ids(service.search_borehole("GEO-2025-07-0415")) == ["GEO-2025-07-0415"]


def test_search_by_partial_record_id(service: BoreHoleService) -> None:
    assert ids(service.search_borehole("0415")) == ["GEO-2025-07-0415"]
    assert ids(service.search_borehole("041")) == FIXTURE_IDS  # all ids contain 041


def test_search_by_operator(service: BoreHoleService) -> None:
    assert ids(service.search_borehole("Lukas Weber")) == [
        "GEO-2025-07-0415",
        "GEO-2025-07-0414",
    ]


def test_search_by_partial_operator_preserves_original_order(
    service: BoreHoleService,
) -> None:
    assert ids(service.search_borehole("natar")) == ["GEO-2025-07-0413", "GEO-2025-07-0412"]


def test_search_is_case_insensitive(service: BoreHoleService) -> None:
    expected = ["GEO-2025-07-0417", "GEO-2025-07-0416"]
    assert ids(service.search_borehole("MERCER")) == expected
    assert ids(service.search_borehole("mErCeR")) == expected
    assert ids(service.search_borehole("geo-2025-07-0416")) == ["GEO-2025-07-0416"]


@pytest.mark.parametrize("needle", ["", "   ", "\t\n"])
def test_search_empty_or_whitespace_returns_all(service: BoreHoleService, needle: str) -> None:
    assert ids(service.search_borehole(needle)) == FIXTURE_IDS


def test_search_strips_surrounding_whitespace(service: BoreHoleService) -> None:
    assert ids(service.search_borehole("  mercer  ")) == ["GEO-2025-07-0417", "GEO-2025-07-0416"]


def test_search_no_match_returns_empty_list(service: BoreHoleService) -> None:
    assert service.search_borehole("zzz") == []
    assert service.search_borehole("TND-DD-0114") == []  # machine is not searched


# -- list: filter -----------------------------------------------------------------------


def test_list_filter_verified(service: BoreHoleService) -> None:
    assert ids(service.get_borehole_records_list(True, None)) == VERIFIED_IDS


def test_list_filter_review(service: BoreHoleService) -> None:
    assert ids(service.get_borehole_records_list(False, None)) == REVIEW_IDS


def test_list_filter_none_returns_all_in_original_order(service: BoreHoleService) -> None:
    assert ids(service.get_borehole_records_list(None, None)) == FIXTURE_IDS


# -- list: sort -----------------------------------------------------------------------


@pytest.mark.parametrize("depth", ["highToLow", DepthSort.HIGH_TO_LOW])
def test_list_sort_high_to_low_full_ordering(service: BoreHoleService, depth) -> None:
    assert ids(service.get_borehole_records_list(None, depth)) == HIGH_TO_LOW_IDS


@pytest.mark.parametrize("depth", ["lowToHigh", DepthSort.LOW_TO_HIGH])
def test_list_sort_low_to_high_full_ordering(service: BoreHoleService, depth) -> None:
    assert ids(service.get_borehole_records_list(None, depth)) == LOW_TO_HIGH_IDS


def test_list_sort_tie_break_is_record_id_ascending_in_both_directions(
    service: BoreHoleService,
) -> None:
    # 0417 and 0414 share depth 3.42; 0417 comes first in the CSV, so a merely
    # stable sort would put 0417 first. The spec demands recordId ascending.
    assert FIXTURE_IDS.index("GEO-2025-07-0417") < FIXTURE_IDS.index("GEO-2025-07-0414")
    for depth in ("highToLow", "lowToHigh"):
        ordered = ids(service.get_borehole_records_list(None, depth))
        tied = [rid for rid in ordered if rid in ("GEO-2025-07-0417", "GEO-2025-07-0414")]
        assert tied == ["GEO-2025-07-0414", "GEO-2025-07-0417"], depth
        assert ordered.index("GEO-2025-07-0414") + 1 == ordered.index("GEO-2025-07-0417")


def test_list_sort_is_deterministic_across_repeated_calls(service: BoreHoleService) -> None:
    runs = [ids(service.get_borehole_records_list(None, "highToLow")) for _ in range(5)]
    assert all(run == HIGH_TO_LOW_IDS for run in runs)


def test_list_sort_none_keeps_original_order(service: BoreHoleService) -> None:
    assert ids(service.get_borehole_records_list(None, None)) == FIXTURE_IDS
    assert ids(service.get_borehole_records_list(True, None)) == VERIFIED_IDS


def test_list_sort_with_filter(service: BoreHoleService) -> None:
    assert ids(service.get_borehole_records_list(True, "highToLow")) == [
        "GEO-2025-07-0413",  # 4.05
        "GEO-2025-07-0415",  # 3.44
        "GEO-2025-07-0417",  # 3.42
        "GEO-2025-07-0416",  # 3.38
    ]
    assert ids(service.get_borehole_records_list(False, "lowToHigh")) == [
        "GEO-2025-07-0412",  # 2.92
        "GEO-2025-07-0414",  # 3.42
    ]


@pytest.mark.parametrize("bad", ["sideways", "HIGHTOLOW", "high_to_low", "desc", "asc"])
def test_list_invalid_depth_raises_value_error(service: BoreHoleService, bad: str) -> None:
    with pytest.raises(ValueError) as exc_info:
        service.get_borehole_records_list(None, bad)
    message = str(exc_info.value)
    assert bad in message
    assert "highToLow" in message and "lowToHigh" in message


def test_list_invalid_depth_is_rejected_even_when_filter_would_be_empty(
    service: BoreHoleService,
) -> None:
    with pytest.raises(ValueError):
        service.get_borehole_records_list(None, "bogus", "zzz")


# -- list: search + filter + sort ------------------------------------------------------


def test_list_search_filter_and_sort_combined(service: BoreHoleService) -> None:
    # search matches all six (every id contains "geo-2025-07-041"), then keep
    # Verified only, then sort low -> high.
    assert ids(service.get_borehole_records_list(True, "lowToHigh", "geo-2025-07-041")) == [
        "GEO-2025-07-0416",  # 3.38
        "GEO-2025-07-0417",  # 3.42
        "GEO-2025-07-0415",  # 3.44
        "GEO-2025-07-0413",  # 4.05
    ]
    assert ids(service.get_borehole_records_list(False, "highToLow", "weber")) == [
        "GEO-2025-07-0414"
    ]
    assert ids(service.get_borehole_records_list(None, "highToLow", "weber")) == [
        "GEO-2025-07-0415",  # 3.44
        "GEO-2025-07-0414",  # 3.42
    ]
    assert service.get_borehole_records_list(True, "lowToHigh", "zzz") == []


def test_list_search_empty_string_matches_all(service: BoreHoleService) -> None:
    assert ids(service.get_borehole_records_list(None, None, "")) == FIXTURE_IDS
    assert ids(service.get_borehole_records_list(None, None, "   ")) == FIXTURE_IDS


# -- update status ---------------------------------------------------------------------


def test_update_status_flips_state_and_bumps_last_updated(service: BoreHoleService) -> None:
    original = service.get_record_detail("GEO-2025-07-0417")
    assert original.state is True
    assert original.last_updated == datetime(2025, 7, 18, tzinfo=UTC)

    before = datetime.now(UTC)
    updated = service.update_borehole_status("GEO-2025-07-0417", False)
    after = datetime.now(UTC)

    assert updated.record_id == "GEO-2025-07-0417"
    assert updated.state is False
    assert updated.state_label == "Review"
    assert updated.last_updated.tzinfo is not None
    assert updated.last_updated.utcoffset().total_seconds() == 0
    assert before <= updated.last_updated <= after
    assert updated.last_updated > datetime(2025, 7, 18, tzinfo=UTC)
    # everything else untouched
    assert updated.date_created == date(2025, 7, 18)
    assert updated.machine == "TND-DD-0114"
    assert updated.operator == "Jack Mercer"
    assert updated.depth == 3.42


def test_update_status_persists_in_memory(service: BoreHoleService) -> None:
    updated = service.update_borehole_status("GEO-2025-07-0414", True)
    detail = service.get_record_detail("GEO-2025-07-0414")
    assert detail.state is True
    assert detail.last_updated == updated.last_updated
    assert ids(service.get_borehole_records_list(True, None)) == [
        "GEO-2025-07-0417",
        "GEO-2025-07-0416",
        "GEO-2025-07-0415",
        "GEO-2025-07-0414",
        "GEO-2025-07-0413",
    ]
    assert ids(service.get_borehole_records_list(False, None)) == ["GEO-2025-07-0412"]
    assert [r.state for r in service.get_all_records()] == [True, True, True, True, True, False]


def test_update_status_back_and_forth(service: BoreHoleService) -> None:
    first = service.update_borehole_status("GEO-2025-07-0412", True)
    assert service.get_record_detail("GEO-2025-07-0412").state is True
    second = service.update_borehole_status("GEO-2025-07-0412", False)
    assert service.get_record_detail("GEO-2025-07-0412").state is False
    assert second.last_updated >= first.last_updated


def test_update_status_lookup_is_case_insensitive(service: BoreHoleService) -> None:
    updated = service.update_borehole_status("geo-2025-07-0415", False)
    assert updated.record_id == "GEO-2025-07-0415"  # original casing retained
    assert service.get_record_detail("GEO-2025-07-0415").state is False


def test_update_status_unknown_id_raises_record_not_found(service: BoreHoleService) -> None:
    with pytest.raises(RecordNotFoundError) as exc_info:
        service.update_borehole_status("GEO-2025-07-9999", True)
    assert str(exc_info.value) == "Record 'GEO-2025-07-9999' not found"
    assert exc_info.value.record_id == "GEO-2025-07-9999"
    assert isinstance(exc_info.value, KeyError)
    # nothing changed
    assert [r.state for r in service.get_all_records()] == [True, True, True, False, True, False]


def test_update_status_does_not_write_to_csv(
    service: BoreHoleService, fixture_csv_path
) -> None:
    before = fixture_csv_path.read_bytes()
    service.update_borehole_status("GEO-2025-07-0417", False)
    assert fixture_csv_path.read_bytes() == before


def test_fetch_again_resets_updated_status(service: BoreHoleService) -> None:
    service.update_borehole_status("GEO-2025-07-0417", False)
    assert service.get_record_detail("GEO-2025-07-0417").state is False

    reloaded = service.fetch_borehole_records()

    assert len(reloaded) == 6
    detail = service.get_record_detail("GEO-2025-07-0417")
    assert detail.state is True
    assert detail.last_updated == datetime(2025, 7, 18, tzinfo=UTC)
    assert service.get_filtered_record_count(None, None).verified_count == 4


# -- detail ----------------------------------------------------------------------------


def test_get_record_detail_found(service: BoreHoleService) -> None:
    assert service.get_record_detail("GEO-2025-07-0413") == BoreHoleRecord(
        record_id="GEO-2025-07-0413",
        machine="TND-DD-0121",
        operator="Priya Natarajan",
        position="52.4055° N",
        depth=4.05,
        plumb="0.11° verticality",
        state=True,
        date_created=date(2025, 7, 17),
        last_updated=datetime(2025, 7, 17, tzinfo=UTC),
    )


def test_get_record_detail_is_case_insensitive_exact_match(service: BoreHoleService) -> None:
    assert service.get_record_detail("geo-2025-07-0413").record_id == "GEO-2025-07-0413"
    with pytest.raises(RecordNotFoundError):
        service.get_record_detail("0413")  # substring is not a match
    with pytest.raises(RecordNotFoundError):
        service.get_record_detail(" GEO-2025-07-0413")  # no stripping either


def test_get_record_detail_not_found(service: BoreHoleService) -> None:
    with pytest.raises(RecordNotFoundError, match=r"Record 'NOPE-1' not found"):
        service.get_record_detail("NOPE-1")


def test_record_not_found_error_message_has_no_keyerror_quotes() -> None:
    exc = RecordNotFoundError("X-1")
    assert str(exc) == "Record 'X-1' not found"
    assert exc.args == ("Record 'X-1' not found",)


# -- counts ------------------------------------------------------------------------------


def test_counts_no_filter(service: BoreHoleService) -> None:
    counts = service.get_filtered_record_count(None, None)
    assert isinstance(counts, RecordCounts)
    assert counts == RecordCounts(
        total_count=6,
        filtered_count=6,
        verified_count=4,
        review_count=2,
        average_depth=AVERAGE_DEPTH_ALL,
    )


def test_counts_average_is_rounded_to_two_decimals(service: BoreHoleService) -> None:
    raw = sum(r.depth for r in service.get_all_records()) / 6
    assert raw != round(raw, 2)  # 3.43833... really needs rounding
    assert service.get_filtered_record_count(None, None).average_depth == 3.44


def test_counts_filtered_verified(service: BoreHoleService) -> None:
    counts = service.get_filtered_record_count(True, None)
    assert counts.total_count == 6
    assert counts.filtered_count == 4
    assert counts.verified_count == 4
    assert counts.review_count == 2
    assert counts.average_depth == AVERAGE_DEPTH_VERIFIED


def test_counts_filtered_review(service: BoreHoleService) -> None:
    counts = service.get_filtered_record_count(False, None)
    assert counts.model_dump() == {
        "totalCount": 6,
        "filteredCount": 2,
        "verifiedCount": 4,
        "reviewCount": 2,
        "averageDepth": AVERAGE_DEPTH_REVIEW,
    }


def test_counts_with_search(service: BoreHoleService) -> None:
    counts = service.get_filtered_record_count(None, None, "mercer")
    assert counts.filtered_count == 2
    assert counts.average_depth == 3.4  # (3.42 + 3.38) / 2
    assert (counts.total_count, counts.verified_count, counts.review_count) == (6, 4, 2)

    counts = service.get_filtered_record_count(False, "lowToHigh", "weber")
    assert counts.filtered_count == 1
    assert counts.average_depth == 3.42


def test_counts_sort_does_not_change_numbers(service: BoreHoleService) -> None:
    assert (
        service.get_filtered_record_count(None, "highToLow")
        == service.get_filtered_record_count(None, "lowToHigh")
        == service.get_filtered_record_count(None, None)
    )


def test_counts_empty_filtered_set_has_zero_average(service: BoreHoleService) -> None:
    counts = service.get_filtered_record_count(None, None, "zzz")
    assert counts.filtered_count == 0
    assert counts.average_depth == 0.0
    assert (counts.total_count, counts.verified_count, counts.review_count) == (6, 4, 2)


def test_counts_invalid_depth_raises_value_error(service: BoreHoleService) -> None:
    with pytest.raises(ValueError, match="bogus"):
        service.get_filtered_record_count(None, "bogus")


def test_counts_reflect_status_updates(service: BoreHoleService) -> None:
    service.update_borehole_status("GEO-2025-07-0417", False)
    counts = service.get_filtered_record_count(None, None)
    assert (counts.verified_count, counts.review_count) == (3, 3)
    assert service.get_filtered_record_count(True, None).filtered_count == 3
    assert service.get_filtered_record_count(False, None).filtered_count == 3


def test_counts_on_empty_service(repository: CsvBoreHoleRepository) -> None:
    counts = BoreHoleService(repository).get_filtered_record_count(None, None)
    assert counts == RecordCounts(
        total_count=0, filtered_count=0, verified_count=0, review_count=0, average_depth=0.0
    )


# -- StateFilter ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("token", "expected"),
    [
        ("all", StateFilter.ALL),
        ("All", StateFilter.ALL),
        ("ALL", StateFilter.ALL),
        ("Verified", StateFilter.VERIFIED),
        ("verified", StateFilter.VERIFIED),
        ("VERIFIED", StateFilter.VERIFIED),
        ("true", StateFilter.VERIFIED),
        ("True", StateFilter.VERIFIED),
        ("TRUE", StateFilter.VERIFIED),
        ("Review", StateFilter.REVIEW),
        ("review", StateFilter.REVIEW),
        ("REVIEW", StateFilter.REVIEW),
        ("false", StateFilter.REVIEW),
        ("False", StateFilter.REVIEW),
        ("FALSE", StateFilter.REVIEW),
        ("  review  ", StateFilter.REVIEW),
    ],
)
def test_state_filter_parse_accepts_known_tokens(token: str, expected: StateFilter) -> None:
    assert StateFilter.parse(token) is expected


@pytest.mark.parametrize("token", ["", "bogus", "1", "0", "yes", "no", "none", "verify"])
def test_state_filter_parse_rejects_unknown_tokens(token: str) -> None:
    with pytest.raises(ValueError, match="Invalid state filter"):
        StateFilter.parse(token)


@pytest.mark.parametrize(
    ("member", "expected"),
    [(StateFilter.ALL, None), (StateFilter.VERIFIED, True), (StateFilter.REVIEW, False)],
)
def test_state_filter_to_bool(member: StateFilter, expected: bool | None) -> None:
    assert member.to_bool() is expected


def test_enum_wire_values() -> None:
    assert [m.value for m in DepthSort] == ["highToLow", "lowToHigh"]
    assert [m.value for m in StateFilter] == ["all", "Verified", "Review"]
