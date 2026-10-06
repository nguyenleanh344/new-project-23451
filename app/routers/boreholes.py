"""Routes for /boreHoleRecords, /fetchData and /health. JSON keys are camelCase."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status

from app.dependencies import get_service
from app.models import (
    BoreHoleRecord,
    DepthSort,
    ErrorResponse,
    FetchResult,
    HealthResponse,
    RecordCounts,
    StateFilter,
    UpdateStatusRequest,
)
from app.services import BoreHoleService, RecordNotFoundError

router = APIRouter()

ServiceDep = Annotated[BoreHoleService, Depends(get_service)]

_STATE_HELP = "all | Verified | Review (case-insensitive; true/false also accepted)"
_DEPTH_HELP = "highToLow | lowToHigh (omit to keep the original order)"
_SEARCH_HELP = "Case-insensitive substring match on record ID or operator"


# -- query dependencies ----------------------------------------------------


def state_query(
    state: Annotated[str | None, Query(description=_STATE_HELP)] = "all",
) -> bool | None:
    """Parse ``state`` into the boolean filter (``None`` = all). 422 on garbage."""
    if state is None or not state.strip():
        return None
    try:
        return StateFilter.parse(state).to_bool()
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc


def depth_query(
    depth: Annotated[str | None, Query(description=_DEPTH_HELP)] = None,
) -> DepthSort | None:
    """Parse ``depth`` into a :class:`DepthSort` (``None`` = no sort). 422 on garbage."""
    if depth is None or not depth.strip():
        return None
    try:
        return DepthSort(depth.strip())
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                f"Invalid depth sort {depth!r}; expected one of: "
                + ", ".join(option.value for option in DepthSort)
            ),
        ) from None


StateDep = Annotated[bool | None, Depends(state_query)]
DepthDep = Annotated[DepthSort | None, Depends(depth_query)]
SearchDep = Annotated[str | None, Query(description=_SEARCH_HELP)]


# -- /fetchData --------------------------------------------------------------


# One handler for both GET and POST. Registered once per method (stacked
# decorators) rather than methods=["GET", "POST"] in a single call because
# FastAPI derives one operation id per route, which would make /openapi.json
# warn about a duplicate operation id.
_FETCH_ROUTE = dict(
    response_model=FetchResult,
    responses={500: {"model": ErrorResponse}},
    summary="Reload records from the CSV (mocked remote fetch)",
    tags=["data"],
)


@router.api_route("/fetchData", methods=["GET"], operation_id="fetch_data_get", **_FETCH_ROUTE)
@router.api_route("/fetchData", methods=["POST"], operation_id="fetch_data_post", **_FETCH_ROUTE)
def fetch_data(service: ServiceDep) -> FetchResult:
    try:
        records = service.fetch_borehole_records()
    except FileNotFoundError as exc:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"CSV file is malformed: {exc}"
        ) from exc
    return FetchResult(count=len(records), source="csv", path=str(service.repository.csv_path))


# -- /boreHoleRecords ---------------------------------------------------------
# Route ORDER matters: /search, /counts and /updateStatus are declared BEFORE
# /{recordId} so they are not swallowed by the path parameter.


@router.get(
    "/boreHoleRecords",
    response_model=list[BoreHoleRecord],
    summary="List records, filtered by state and sorted by depth",
    tags=["boreholes"],
)
def list_records(
    service: ServiceDep,
    state: StateDep,
    depth: DepthDep,
    q: SearchDep = None,
) -> list[BoreHoleRecord]:
    return service.get_borehole_records_list(state, depth, q)


@router.get(
    "/boreHoleRecords/search",
    response_model=list[BoreHoleRecord],
    summary="Search by record ID or operator",
    tags=["boreholes"],
)
def search_records(
    service: ServiceDep,
    q: Annotated[str, Query(description=f"{_SEARCH_HELP} (empty returns all)")],
) -> list[BoreHoleRecord]:
    return service.search_borehole(q)


@router.get(
    "/boreHoleRecords/counts",
    response_model=RecordCounts,
    summary="Record counts and average depth for the current filter",
    tags=["boreholes"],
)
def record_counts(
    service: ServiceDep,
    state: StateDep,
    depth: DepthDep,
    q: SearchDep = None,
) -> RecordCounts:
    return service.get_filtered_record_count(state, depth, q)


@router.put(
    "/boreHoleRecords/updateStatus",
    response_model=BoreHoleRecord,
    responses={404: {"model": ErrorResponse}},
    summary="Update a record's state (in memory only)",
    tags=["boreholes"],
)
def update_status(payload: UpdateStatusRequest, service: ServiceDep) -> BoreHoleRecord:
    try:
        return service.update_borehole_status(payload.record_id, payload.state)
    except RecordNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get(
    "/boreHoleRecords/{recordId}",
    response_model=BoreHoleRecord,
    responses={404: {"model": ErrorResponse}},
    summary="Record detail",
    tags=["boreholes"],
)
def get_record(
    record_id: Annotated[str, Path(alias="recordId", description="Record ID")],
    service: ServiceDep,
) -> BoreHoleRecord:
    try:
        return service.get_record_detail(record_id)
    except RecordNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


# -- /health -----------------------------------------------------------------


@router.get("/health", response_model=HealthResponse, summary="Liveness check", tags=["meta"])
def health(service: ServiceDep) -> HealthResponse:
    return HealthResponse(status="ok", records=len(service.get_all_records()))
