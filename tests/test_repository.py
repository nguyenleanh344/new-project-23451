"""Tests for CsvBoreHoleRepository and parse_state."""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from app.models import BoreHoleRecord
from app.repository import CsvBoreHoleRepository, parse_state
from tests.conftest import DEPTHS, FIXTURE_IDS, REVIEW_IDS, VERIFIED_IDS

UTC = timezone.utc

ROW_TEMPLATE = (
    "GEO-2025-07-04{n},TND-DD-0114,Jack Mercer,52.4042° N,{depth},"
    "0.04° verticality,{state},2025-07-18,{last_updated}"
)


def row(n: str, depth: str = "3.42", state: str = "Verified", last_updated: str = "") -> str:
    return ROW_TEMPLATE.format(n=n, depth=depth, state=state, last_updated=last_updated)


# -- loading the fixture ------------------------------------------------------


def test_load_returns_six_rows_in_file_order(repository: CsvBoreHoleRepository) -> None:
    records = repository.load()
    assert len(records) == 6
    assert [r.record_id for r in records] == FIXTURE_IDS


def test_load_returns_borehole_record_models_with_correct_types(
    repository: CsvBoreHoleRepository,
) -> None:
    for record in repository.load():
        assert isinstance(record, BoreHoleRecord)
        assert isinstance(record.record_id, str)
        assert isinstance(record.machine, str)
        assert isinstance(record.operator, str)
        assert isinstance(record.position, str)
        assert isinstance(record.depth, float)
        assert isinstance(record.plumb, str)
        assert isinstance(record.state, bool)
        assert type(record.date_created) is date  # not datetime
        assert isinstance(record.last_updated, datetime)
        assert record.last_updated.tzinfo is not None
        assert record.last_updated.utcoffset().total_seconds() == 0


def test_load_parses_field_values_exactly(repository: CsvBoreHoleRepository) -> None:
    first = repository.load()[0]
    assert first == BoreHoleRecord(
        record_id="GEO-2025-07-0417",
        machine="TND-DD-0114",
        operator="Jack Mercer",
        position="52.4042° N",
        depth=3.42,
        plumb="0.04° verticality",
        state=True,
        date_created=date(2025, 7, 18),
        last_updated=datetime(2025, 7, 18, 0, 0, tzinfo=UTC),
    )


def test_load_parses_depths_as_floats(repository: CsvBoreHoleRepository) -> None:
    assert {r.record_id: r.depth for r in repository.load()} == DEPTHS


def test_load_parses_states(repository: CsvBoreHoleRepository) -> None:
    records = repository.load()
    assert [r.record_id for r in records if r.state] == VERIFIED_IDS
    assert [r.record_id for r in records if not r.state] == REVIEW_IDS
    assert {r.record_id: r.state_label for r in records} == {
        **dict.fromkeys(VERIFIED_IDS, "Verified"),
        **dict.fromkeys(REVIEW_IDS, "Review"),
    }


def test_blank_last_updated_defaults_to_date_created_midnight_utc(
    repository: CsvBoreHoleRepository,
) -> None:
    by_id = {r.record_id: r for r in repository.load()}
    blank = by_id["GEO-2025-07-0416"]  # lastUpdated column is empty in the fixture
    assert blank.date_created == date(2025, 7, 18)
    assert blank.last_updated == datetime(2025, 7, 18, 0, 0, 0, tzinfo=UTC)
    assert blank.last_updated.tzinfo is not None


def test_explicit_last_updated_is_parsed_with_timezone(
    repository: CsvBoreHoleRepository,
) -> None:
    by_id = {r.record_id: r for r in repository.load()}
    assert by_id["GEO-2025-07-0413"].last_updated == datetime(2025, 7, 17, tzinfo=UTC)
    assert by_id["GEO-2025-07-0413"].date_created == date(2025, 7, 17)


def test_csv_path_property_and_load_does_not_write(
    repository: CsvBoreHoleRepository, fixture_csv_path: Path
) -> None:
    assert repository.csv_path == fixture_csv_path
    before = fixture_csv_path.read_bytes()
    repository.load()
    repository.load()
    assert fixture_csv_path.read_bytes() == before


# -- error handling --------------------------------------------------------------


def test_missing_file_raises_file_not_found(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist.csv"
    with pytest.raises(FileNotFoundError) as exc_info:
        CsvBoreHoleRepository(missing).load()
    assert str(missing) in str(exc_info.value)


def test_malformed_depth_raises_value_error_mentioning_the_row(write_csv) -> None:
    path = write_csv(
        "\n".join(
            [
                row("01", depth="3.42"),
                row("02", depth="abc"),  # second data row is malformed
                row("03", depth="3.44"),
            ]
        )
    )
    with pytest.raises(ValueError) as exc_info:
        CsvBoreHoleRepository(path).load()
    message = str(exc_info.value)
    assert "row 2" in message
    assert "abc" in message
    assert str(path) in message


@pytest.mark.parametrize("token", ["nan", "NaN", "inf", "-inf", "Infinity", "1e400"])
def test_non_finite_depth_raises_value_error_mentioning_the_row(write_csv, token: str) -> None:
    # float() accepts these tokens, but a depth must be a plain finite number of
    # metres; otherwise it would leak as JSON null and break averageDepth/sorting.
    path = write_csv("\n".join([row("01"), row("02", depth=token), row("03")]))
    with pytest.raises(ValueError) as exc_info:
        CsvBoreHoleRepository(path).load()
    message = str(exc_info.value)
    assert "row 2" in message
    assert token in message
    assert "finite" in message


def test_malformed_state_raises_value_error_mentioning_the_row(write_csv) -> None:
    path = write_csv("\n".join([row("01"), row("02"), row("03", state="maybe")]))
    with pytest.raises(ValueError, match=r"row 3"):
        CsvBoreHoleRepository(path).load()


def test_malformed_date_raises_value_error_mentioning_the_row(write_csv) -> None:
    bad = row("01").replace("2025-07-18,", "18 Jul 2025,", 1)
    path = write_csv(bad)
    with pytest.raises(ValueError, match=r"row 1"):
        CsvBoreHoleRepository(path).load()


def test_missing_required_column_raises_value_error(tmp_path: Path) -> None:
    path = tmp_path / "no-depth.csv"
    path.write_text(
        "recordId,machine,operator,position,plumb,state,dateCreated,lastUpdated\n"
        "GEO-2025-07-0401,TND-DD-0114,Jack Mercer,52.4042° N,0.04° verticality,"
        "Verified,2025-07-18,\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="depth"):
        CsvBoreHoleRepository(path).load()


# -- lenient parsing -------------------------------------------------------------


def test_fully_blank_lines_are_skipped(write_csv) -> None:
    path = write_csv("\n".join([row("01"), "", row("02"), ",,,,,,,,", "   ", row("03"), ""]))
    records = CsvBoreHoleRepository(path).load()
    assert [r.record_id for r in records] == [
        "GEO-2025-07-0401",
        "GEO-2025-07-0402",
        "GEO-2025-07-0403",
    ]


def test_state_tokens_in_csv_are_accepted(write_csv) -> None:
    tokens = ["Verified", "Review", "true", "FALSE", "1", "0", "yes", "No"]
    path = write_csv("\n".join(row(f"{i:02d}", state=tok) for i, tok in enumerate(tokens, 1)))
    records = CsvBoreHoleRepository(path).load()
    assert [r.state for r in records] == [True, False, True, False, True, False, True, False]


def test_naive_last_updated_is_treated_as_utc(write_csv) -> None:
    path = write_csv(row("01", last_updated="2025-07-18T10:30:00"))
    (record,) = CsvBoreHoleRepository(path).load()
    assert record.last_updated == datetime(2025, 7, 18, 10, 30, tzinfo=UTC)


def test_empty_file_loads_zero_records(tmp_path: Path) -> None:
    path = tmp_path / "empty.csv"
    path.write_text("", encoding="utf-8")
    assert CsvBoreHoleRepository(path).load() == []


def test_header_only_file_loads_zero_records(write_csv) -> None:
    assert CsvBoreHoleRepository(write_csv("")).load() == []


def test_utf8_bom_from_excel_export_is_ignored(tmp_path: Path) -> None:
    """Excel's "CSV UTF-8" export prefixes a BOM; it must not corrupt the first header."""
    path = tmp_path / "bom.csv"
    body = (
        "recordId,machine,operator,position,depth,plumb,state,dateCreated,lastUpdated\n"
        "GEO-2025-07-0499,TND-DD-0114,Edward,52.4040° N,3.10,0.05° verticality,Review,2025-07-18,\n"
    )
    path.write_text(body, encoding="utf-8-sig")  # utf-8-sig writes the BOM
    assert path.read_bytes().startswith(b"\xef\xbb\xbf")
    records = CsvBoreHoleRepository(path).load()
    assert [r.record_id for r in records] == ["GEO-2025-07-0499"]
    assert records[0].operator == "Edward"


# -- parse_state -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("token", "expected"),
    [
        ("Verified", True),
        ("verified", True),
        ("VERIFIED", True),
        ("  Verified  ", True),
        ("true", True),
        ("True", True),
        ("TRUE", True),
        ("1", True),
        ("yes", True),
        ("YES", True),
        ("Review", False),
        ("review", False),
        ("REVIEW", False),
        ("false", False),
        ("False", False),
        ("0", False),
        ("no", False),
        ("No", False),
    ],
)
def test_parse_state_accepts_known_tokens(token: str, expected: bool) -> None:
    result = parse_state(token)
    assert result is expected


@pytest.mark.parametrize("token", ["", "   ", "maybe", "2", "verify", "reviewed", "t", "f"])
def test_parse_state_rejects_unknown_tokens(token: str) -> None:
    with pytest.raises(ValueError, match="state"):
        parse_state(token)
