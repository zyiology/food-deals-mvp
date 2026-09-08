"""Local FastAPI application; publication is a separate offline operation."""

import logging
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import Field

from .api_models import DealsResponse, HealthResponse, Validity
from .api_settings import ApiSettings
from .deal_repository import DealRepository
from .location_search import (
    DeviceLocation,
    LocationResult,
    LocationResults,
    LocationSearchError,
    reverse_location,
    search_locations,
)
from .models import Contract

logger = logging.getLogger(__name__)
STATIC_DIR = Path(__file__).resolve().parent / "static"


class DealQuery(Contract):
    # Validate the wire format before parsing: timestamps/numeric dates are not
    # accepted as substitutes for an explicit Singapore calendar date.
    as_of: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    validity: Validity = "all"


def create_app(settings: ApiSettings | None = None) -> FastAPI:
    repository: DealRepository | None = None
    unavailable = "Prepare a dataset first"

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        nonlocal repository, unavailable
        repository = None
        try:
            configuration = settings or ApiSettings.from_env()
        except OSError, ValueError:
            unavailable = "Application configuration is invalid"
            logger.error(
                "Invalid API configuration; check FOOD_DEALS environment variables"
            )
        else:
            try:
                repository = DealRepository(configuration)
            except FileNotFoundError:
                unavailable = "Prepare a dataset first"
                logger.warning("Published dataset is missing")
            except OSError, ValueError, RuntimeError:
                unavailable = "Published dataset is invalid"
                logger.error("Published dataset failed startup validation")
        yield
        repository = None

    app = FastAPI(title="Food deals", lifespan=lifespan)

    def require_repository() -> DealRepository:
        if repository is None:
            raise HTTPException(status_code=503, detail=unavailable)
        return repository

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception):
        # Avoid dumping snapshot content, filesystem paths, or credentials.
        logger.error("Unexpected API error (%s)", type(exc).__name__)
        return JSONResponse(
            status_code=500, content={"detail": "Internal server error"}
        )

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(
            STATIC_DIR / "index.html", headers={"Cache-Control": "no-cache"}
        )

    @app.get("/api/health", response_model=HealthResponse)
    def health(response: Response) -> HealthResponse:
        response.headers["Cache-Control"] = "no-store"
        return HealthResponse(dataset_id=require_repository().dataset_id)

    @app.post("/api/locations/reverse", response_model=LocationResult | None)
    def reverse_address(
        location: DeviceLocation, response: Response
    ) -> LocationResult | None:
        response.headers["Cache-Control"] = "no-store"
        try:
            return reverse_location(location)
        except LocationSearchError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from None

    @app.get("/api/locations", response_model=LocationResults)
    def locations(
        q: Annotated[str, Query(min_length=2, max_length=120)], response: Response
    ) -> LocationResults:
        response.headers["Cache-Control"] = "no-store"
        query = q.strip()
        if len(query) < 2:
            raise HTTPException(
                status_code=422, detail="Enter at least two characters."
            )
        try:
            return search_locations(query)
        except LocationSearchError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from None

    @app.get("/api/deals", response_model=DealsResponse)
    def deals(
        query: Annotated[DealQuery, Query()], response: Response
    ) -> DealsResponse:
        reference = None
        if query.as_of is not None:
            try:
                reference = date.fromisoformat(query.as_of)
            except ValueError:
                raise HTTPException(
                    status_code=422, detail="as_of must be a valid YYYY-MM-DD date"
                ) from None
        response.headers["Cache-Control"] = "no-store"
        return require_repository().query(reference, query.validity)

    @app.get("/media/{media_id}", include_in_schema=False)
    def media(media_id: str, request: Request) -> Response:
        if repository is None or (asset := repository.image(media_id)) is None:
            raise HTTPException(status_code=404, detail="Image not found")
        content, mime_type, digest = asset
        etag = f'"{digest}"'
        # IDs belong to source attachments and can point to different bytes after
        # republication. Revalidate instead of caching these URLs as immutable.
        headers = {
            "Cache-Control": "no-cache",
            "ETag": etag,
            "X-Content-Type-Options": "nosniff",
        }
        candidates = request.headers.get("if-none-match", "").split(",")
        if any(value.strip().removeprefix("W/") in {etag, "*"} for value in candidates):
            return Response(status_code=304, headers=headers)
        return Response(content=content, media_type=mime_type, headers=headers)

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app


app = create_app()
