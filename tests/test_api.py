"""HTTP tests against a fresh app per test (see conftest.client)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
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

RECORD_KEYS = [
    "recordId",
    "machine",
    "operator",
    "position",
    "depth",
    "plumb",
    "state",
    "dateCreated",
    "lastUpdated",
    "stateLabel",
]

RECORD_0417 = {
    "recordId": "GEO-2025-07-0417",
    "machine": "TND-DD-0114",
    "operator": "Jack Mercer",
    "position": "52.4042° N",
    "depth": 3.42,
    "plumb": "0.04° verticality",
    "state": True,
    "dateCreated": "2025-07-18",
    "lastUpdated": "2025-07-18T00:00:00Z",
    "stateLabel": "Verified",
}


def ids(payload: list[dict]) -> list[str]:
    return [item["recordId"] for item in payload]


# -- meta ------------------------------------------------------------------------------


def test_health(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "records": 6}


def test_root_serves_html(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "<" in response.text and "html" in response.text.lower()


def test_openapi_documents_routes_and_404s(client: TestClient) -> None:
    response = client.get("/openapi.json")
    assert response.status_code == 200
    spec = response.json()
    assert spec["info"]["title"] == "BoreHole Records API"
    assert spec["info"]["version"] == "0.1.0"
    paths = spec["paths"]
    assert {"get", "post"} <= set(paths["/fetchData"])
    assert "get" in paths["/boreHoleRecords"]
    assert "get" in paths["/boreHoleRecords/search"]
    assert "get" in paths["/boreHoleRecords/counts"]
    assert "put" in paths["/boreHoleRecords/updateStatus"]
    assert "get" in paths["/boreHoleRecords/{recordId}"]
    assert "get" in paths["/health"]
    assert "404" in paths["/boreHoleRecords/{recordId}"]["get"]["responses"]
    assert "404" in paths["/boreHoleRecords/updateStatus"]["put"]["responses"]
    assert "/" not in paths  # index page is hidden from the schema
    assert client.get("/docs").status_code == 200


# -- /fetchData -------------------------------------------------------------------------


@pytest.mark.parametrize("method", ["GET", "POST"])
def test_fetch_data(client: TestClient, fixture_csv_path: Path, method: str) -> None:
    response = client.request(method, "/fetchData")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"count", "source", "path"}
    assert body["count"] == 6
    assert body["source"] == "csv"
    assert Path(body["path"]) == fixture_csv_path


def test_fetch_data_resets_an_in_memory_update(client: TestClient) -> None:
    put = client.put("/boreHoleRecords/updateStatus", json={"recordId": "GEO-2025-07-0417", "state": False})
    assert put.status_code == 200
    assert client.get("/boreHoleRecords/GEO-2025-07-0417").json()["state"] is False

    assert client.post("/fetchData").status_code == 200

    assert client.get("/boreHoleRecords/GEO-2025-07-0417").json() == RECORD_0417
    assert client.get("/boreHoleRecords/counts").json()["verifiedCount"] == 4


def test_missing_csv_starts_empty_and_fetch_returns_500(tmp_path: Path) -> None:
    missing = tmp_path / "nope.csv"
    with TestClient(create_app(csv_path=missing)) as client:
        assert client.get("/health").json() == {"status": "ok", "records": 0}
        assert client.get("/boreHoleRecords").json() == []
        response = client.post("/fetchData")
        assert response.status_code == 500
        assert str(missing) in response.json()["detail"]


def test_malformed_csv_fetch_returns_500_with_row_number(write_csv) -> None:
    path = write_csv(
        "GEO-2025-07-0401,TND-DD-0114,Jack Mercer,52.4042° N,3.42,0.04° verticality,"
        "Verified,2025-07-18,\n"
        "GEO-2025-07-0402,TND-DD-0114,Jack Mercer,52.4042° N,abc,0.04° verticality,"
        "Verified,2025-07-18,\n"
    )
    with TestClient(create_app(csv_path=path)) as client:
        assert client.get("/health").json()["records"] == 0
        response = client.get("/fetchData")
        assert response.status_code == 500
        detail = response.json()["detail"]
        assert "row 2" in detail
        assert "abc" in detail


# -- GET /boreHoleRecords (list) ----------------------------------------------------


def test_list_default_returns_all_in_csv_order(client: TestClient) -> None:
    response = client.get("/boreHoleRecords")
    assert response.status_code == 200
    body = response.json()
    assert ids(body) == FIXTURE_IDS
    assert body[0] == RECORD_0417


def test_list_json_keys_are_camel_case(client: TestClient) -> None:
    for item in client.get("/boreHoleRecords").json():
        assert list(item) == RECORD_KEYS
        assert "action" not in item  # "Open" is a UI button, not a data field
        assert "record_id" not in item and "state_label" not in item


@pytest.mark.parametrize("value", ["Verified", "verified", "VERIFIED", "true", "True"])
def test_list_state_verified_tokens(client: TestClient, value: str) -> None:
    response = client.get("/boreHoleRecords", params={"state": value})
    assert response.status_code == 200
    assert ids(response.json()) == VERIFIED_IDS
    assert all(item["state"] is True and item["stateLabel"] == "Verified" for item in response.json())


@pytest.mark.parametrize("value", ["Review", "review", "REVIEW", "false", "FALSE"])
def test_list_state_review_tokens(client: TestClient, value: str) -> None:
    response = client.get("/boreHoleRecords", params={"state": value})
    assert response.status_code == 200
    assert ids(response.json()) == REVIEW_IDS
    assert all(item["state"] is False and item["stateLabel"] == "Review" for item in response.json())


@pytest.mark.parametrize("value", ["all", "All", ""])
def test_list_state_all_tokens(client: TestClient, value: str) -> None:
    response = client.get("/boreHoleRecords", params={"state": value})
    assert response.status_code == 200
    assert ids(response.json()) == FIXTURE_IDS


def test_list_depth_high_to_low(client: TestClient) -> None:
    response = client.get("/boreHoleRecords", params={"depth": "highToLow"})
    assert response.status_code == 200
    assert ids(response.json()) == HIGH_TO_LOW_IDS
    depths = [item["depth"] for item in response.json()]
    assert depths == sorted(depths, reverse=True)


def test_list_depth_low_to_high(client: TestClient) -> None:
    response = client.get("/boreHoleRecords", params={"depth": "lowToHigh"})
    assert response.status_code == 200
    assert ids(response.json()) == LOW_TO_HIGH_IDS


def test_list_depth_empty_keeps_order(client: TestClient) -> None:
    assert ids(client.get("/boreHoleRecords", params={"depth": ""}).json()) == FIXTURE_IDS


@pytest.mark.parametrize("bad", ["bogus", "1", "yes", "verifiedd"])
def test_list_invalid_state_returns_422(client: TestClient, bad: str) -> None:
    response = client.get("/boreHoleRecords", params={"state": bad})
    assert response.status_code == 422
    assert response.json() == {
        "detail": f"Invalid state filter '{bad}'; expected one of: all, Verified, Review, true, false"
    }


@pytest.mark.parametrize("bad", ["bogus", "HIGHTOLOW", "asc"])
def test_list_invalid_depth_returns_422(client: TestClient, bad: str) -> None:
    response = client.get("/boreHoleRecords", params={"depth": bad})
    assert response.status_code == 422
    assert response.json() == {
        "detail": f"Invalid depth sort '{bad}'; expected one of: highToLow, lowToHigh"
    }


def test_list_q_search(client: TestClient) -> None:
    assert ids(client.get("/boreHoleRecords", params={"q": "merc"}).json()) == [
        "GEO-2025-07-0417",
        "GEO-2025-07-0416",
    ]
    assert ids(client.get("/boreHoleRecords", params={"q": "0415"}).json()) == ["GEO-2025-07-0415"]
    assert ids(client.get("/boreHoleRecords", params={"q": "NATARAJAN"}).json()) == [
        "GEO-2025-07-0413",
        "GEO-2025-07-0412",
    ]
    assert client.get("/boreHoleRecords", params={"q": "zzz"}).json() == []
    assert ids(client.get("/boreHoleRecords", params={"q": ""}).json()) == FIXTURE_IDS


def test_list_q_state_and_depth_combined(client: TestClient) -> None:
    response = client.get(
        "/boreHoleRecords", params={"q": "geo-2025-07-041", "state": "Verified", "depth": "lowToHigh"}
    )
    assert response.status_code == 200
    assert ids(response.json()) == [
        "GEO-2025-07-0416",
        "GEO-2025-07-0417",
        "GEO-2025-07-0415",
        "GEO-2025-07-0413",
    ]
    response = client.get("/boreHoleRecords", params={"q": "weber", "state": "review", "depth": "highToLow"})
    assert ids(response.json()) == ["GEO-2025-07-0414"]


# -- GET /boreHoleRecords/search -----------------------------------------------------


def test_search_endpoint(client: TestClient) -> None:
    response = client.get("/boreHoleRecords/search", params={"q": "weber"})
    assert response.status_code == 200
    assert ids(response.json()) == ["GEO-2025-07-0415", "GEO-2025-07-0414"]
    assert list(response.json()[0]) == RECORD_KEYS


def test_search_endpoint_empty_q_returns_all(client: TestClient) -> None:
    response = client.get("/boreHoleRecords/search", params={"q": ""})
    assert response.status_code == 200
    assert ids(response.json()) == FIXTURE_IDS


def test_search_endpoint_no_match(client: TestClient) -> None:
    assert client.get("/boreHoleRecords/search", params={"q": "zzz"}).json() == []


def test_search_endpoint_requires_q(client: TestClient) -> None:
    response = client.get("/boreHoleRecords/search")
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["query", "q"]


# -- GET /boreHoleRecords/counts -----------------------------------------------------


def test_counts_no_filter(client: TestClient) -> None:
    response = client.get("/boreHoleRecords/counts")
    assert response.status_code == 200
    assert response.json() == {
        "totalCount": 6,
        "filteredCount": 6,
        "verifiedCount": 4,
        "reviewCount": 2,
        "averageDepth": AVERAGE_DEPTH_ALL,
    }


def test_counts_with_state_filter(client: TestClient) -> None:
    verified = client.get("/boreHoleRecords/counts", params={"state": "Verified"}).json()
    assert verified == {
        "totalCount": 6,
        "filteredCount": 4,
        "verifiedCount": 4,
        "reviewCount": 2,
        "averageDepth": AVERAGE_DEPTH_VERIFIED,
    }
    review = client.get("/boreHoleRecords/counts", params={"state": "review", "depth": "lowToHigh"}).json()
    assert review == {
        "totalCount": 6,
        "filteredCount": 2,
        "verifiedCount": 4,
        "reviewCount": 2,
        "averageDepth": AVERAGE_DEPTH_REVIEW,
    }


def test_counts_with_search(client: TestClient) -> None:
    body = client.get("/boreHoleRecords/counts", params={"q": "mercer"}).json()
    assert body["filteredCount"] == 2
    assert body["averageDepth"] == 3.4
    assert (body["totalCount"], body["verifiedCount"], body["reviewCount"]) == (6, 4, 2)


def test_counts_empty_set_average_is_zero(client: TestClient) -> None:
    body = client.get("/boreHoleRecords/counts", params={"q": "zzz"}).json()
    assert body == {
        "totalCount": 6,
        "filteredCount": 0,
        "verifiedCount": 4,
        "reviewCount": 2,
        "averageDepth": 0.0,
    }


def test_counts_invalid_params_return_422(client: TestClient) -> None:
    assert client.get("/boreHoleRecords/counts", params={"state": "bogus"}).status_code == 422
    assert client.get("/boreHoleRecords/counts", params={"depth": "bogus"}).status_code == 422


# -- PUT /boreHoleRecords/updateStatus ------------------------------------------------


def test_update_status_happy_path(client: TestClient) -> None:
    response = client.put(
        "/boreHoleRecords/updateStatus", json={"recordId": "GEO-2025-07-0417", "state": False}
    )
    assert response.status_code == 200
    body = response.json()
    assert list(body) == RECORD_KEYS
    assert body["recordId"] == "GEO-2025-07-0417"
    assert body["state"] is False
    assert body["stateLabel"] == "Review"
    assert body["lastUpdated"] != RECORD_0417["lastUpdated"]
    assert body["lastUpdated"] > RECORD_0417["lastUpdated"]  # ISO-8601 sorts lexically
    assert body["lastUpdated"].endswith("Z")
    assert body["dateCreated"] == "2025-07-18"
    assert {k: body[k] for k in ("machine", "operator", "position", "depth", "plumb")} == {
        k: RECORD_0417[k] for k in ("machine", "operator", "position", "depth", "plumb")
    }

    # subsequent reads reflect the change
    detail = client.get("/boreHoleRecords/GEO-2025-07-0417").json()
    assert detail == body
    assert ids(client.get("/boreHoleRecords", params={"state": "Review"}).json()) == [
        "GEO-2025-07-0417",
        "GEO-2025-07-0414",
        "GEO-2025-07-0412",
    ]
    counts = client.get("/boreHoleRecords/counts").json()
    assert (counts["verifiedCount"], counts["reviewCount"]) == (3, 3)


def test_update_status_to_verified(client: TestClient) -> None:
    response = client.put(
        "/boreHoleRecords/updateStatus", json={"recordId": "GEO-2025-07-0412", "state": True}
    )
    assert response.status_code == 200
    assert response.json()["state"] is True
    assert response.json()["stateLabel"] == "Verified"
    assert ids(client.get("/boreHoleRecords", params={"state": "Review"}).json()) == ["GEO-2025-07-0414"]


def test_update_status_is_case_insensitive_on_record_id(client: TestClient) -> None:
    response = client.put(
        "/boreHoleRecords/updateStatus", json={"recordId": "geo-2025-07-0415", "state": False}
    )
    assert response.status_code == 200
    assert response.json()["recordId"] == "GEO-2025-07-0415"
    assert client.get("/boreHoleRecords/GEO-2025-07-0415").json()["state"] is False


def test_update_status_unknown_record_returns_404(client: TestClient) -> None:
    response = client.put("/boreHoleRecords/updateStatus", json={"recordId": "NOPE-1", "state": True})
    assert response.status_code == 404
    assert response.json() == {"detail": "Record 'NOPE-1' not found"}


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"recordId": "GEO-2025-07-0417"},  # missing state
        {"state": True},  # missing recordId
        {"recordId": "", "state": True},  # empty recordId
        {"recordId": "GEO-2025-07-0417", "state": "maybe"},  # non-boolean state
        {"recordId": "GEO-2025-07-0417", "state": None},
        {"recordId": "GEO-2025-07-0417", "state": 2},
        {"recordId": 417, "state": True},  # recordId must be a string
    ],
)
def test_update_status_bad_body_returns_422(client: TestClient, payload: dict) -> None:
    response = client.put("/boreHoleRecords/updateStatus", json=payload)
    assert response.status_code == 422
    assert "detail" in response.json()


def test_update_status_accepts_snake_case_field_name(client: TestClient) -> None:
    # populate_by_name=True: the Python field name is accepted alongside the alias.
    response = client.put(
        "/boreHoleRecords/updateStatus", json={"record_id": "GEO-2025-07-0414", "state": True}
    )
    assert response.status_code == 200
    assert response.json()["recordId"] == "GEO-2025-07-0414"
    assert response.json()["state"] is True


def test_update_status_bad_body_does_not_mutate(client: TestClient) -> None:
    client.put("/boreHoleRecords/updateStatus", json={"recordId": "GEO-2025-07-0417", "state": "maybe"})
    assert client.get("/boreHoleRecords/GEO-2025-07-0417").json() == RECORD_0417


# -- GET /boreHoleRecords/{recordId} ------------------------------------------------------


def test_get_detail_happy_path(client: TestClient) -> None:
    response = client.get("/boreHoleRecords/GEO-2025-07-0417")
    assert response.status_code == 200
    assert response.json() == RECORD_0417


def test_get_detail_blank_last_updated_row_defaults(client: TestClient) -> None:
    body = client.get("/boreHoleRecords/GEO-2025-07-0416").json()
    assert body["dateCreated"] == "2025-07-18"
    assert body["lastUpdated"] == "2025-07-18T00:00:00Z"


def test_get_detail_is_case_insensitive(client: TestClient) -> None:
    response = client.get("/boreHoleRecords/geo-2025-07-0417")
    assert response.status_code == 200
    assert response.json() == RECORD_0417


def test_get_detail_not_found(client: TestClient) -> None:
    response = client.get("/boreHoleRecords/GEO-2025-07-9999")
    assert response.status_code == 404
    assert response.json() == {"detail": "Record 'GEO-2025-07-9999' not found"}


def test_get_detail_static_routes_are_not_shadowed(client: TestClient) -> None:
    # /search, /counts and /updateStatus must be matched before /{recordId}.
    assert client.get("/boreHoleRecords/search", params={"q": ""}).status_code == 200
    assert client.get("/boreHoleRecords/counts").status_code == 200
    put = client.put("/boreHoleRecords/updateStatus", json={"recordId": "x", "state": True})
    assert put.status_code == 404
    assert put.json() == {"detail": "Record 'x' not found"}
    # A GET on /updateStatus has no GET route of its own, so it falls through to
    # /{recordId} and is looked up as a record id (not a 405).
    fallthrough = client.get("/boreHoleRecords/updateStatus")
    assert fallthrough.status_code == 404
    assert fallthrough.json() == {"detail": "Record 'updateStatus' not found"}


# -- isolation -------------------------------------------------------------------------------


def test_state_update_in_one_test(client: TestClient) -> None:
    client.put("/boreHoleRecords/updateStatus", json={"recordId": "GEO-2025-07-0416", "state": False})
    assert client.get("/boreHoleRecords/GEO-2025-07-0416").json()["state"] is False


def test_state_does_not_leak_into_the_next_test(client: TestClient) -> None:
    # runs after the test above (file order); a shared app would show False here
    body = client.get("/boreHoleRecords/GEO-2025-07-0416").json()
    assert body["state"] is True
    assert body["lastUpdated"] == "2025-07-18T00:00:00Z"
    assert client.get("/health").json() == {"status": "ok", "records": 6}
