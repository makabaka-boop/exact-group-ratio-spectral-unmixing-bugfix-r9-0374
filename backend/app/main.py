"""FastAPI application: exact non-negative rational spectral fitting."""

from __future__ import annotations

import hashlib
import io
import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from .models import (
    SolveRequest,
    SolveResponse,
    canonical_payload,
    rational_to_payload,
)
from .solver import rational_rank, solve_nonnegative_least_squares

from .grouped import solve_grouped

app = FastAPI(
    title="Spectrum NNLS Solver",
    version="0.1.0",
    description=(
        "Exact (floating-point-free) non-negative least squares for small "
        "integer spectral datasets. Supports are enumerated; each candidate "
        "solves rational normal equations and is compared by exact residual."
    ),
)


class ApiError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


@app.exception_handler(ApiError)
async def api_error_handler(_request: Request, exc: ApiError):
    return JSONResponse(
        status_code=422,
        content={"error": {"code": exc.code, "message": exc.message}},
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_request: Request, exc: RequestValidationError):
    # Whole-request rejection for any schema-level violation (missing
    # field, non-integer value, wrong container type, ...).
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "invalid_schema",
                "message": "request rejected; all fields must be valid",
                "details": jsonable_encoder(exc.errors()),
            }
        },
    )


def _validate(req: SolveRequest) -> None:
    n = len(req.observations)
    if not 20 <= n <= 80:
        raise ApiError(
            "invalid_dimension",
            f"observations must contain 20..80 points, got {n}",
        )
    if len(req.wavelengths) != n:
        raise ApiError(
            "invalid_dimension",
            "wavelengths and observations must have the same length "
            f"({len(req.wavelengths)} vs {n})",
        )
    if len(req.wavelengths) != len(set(req.wavelengths)):
        raise ApiError("invalid_wavelengths", "wavelengths must be unique")
    if any(req.wavelengths[i] >= req.wavelengths[i + 1] for i in range(n - 1)):
        raise ApiError("invalid_wavelengths", "wavelengths must be strictly increasing")
    k = len(req.references)
    if not 2 <= k <= 6:
        raise ApiError(
            "invalid_dimension",
            f"references must contain 2..6 curves, got {k}",
        )
    for j, curve in enumerate(req.references):
        if len(curve) != n:
            raise ApiError(
                "invalid_dimension",
                f"reference curve {j} has length {len(curve)}, expected {n}",
            )
        if any(v < 0 for v in curve):
            raise ApiError(
                "invalid_reference",
                f"reference curve {j} contains negative values",
            )
    # Linear independence is required of the whole bundle; reject entirely
    # rather than dropping a curve silently.
    rank = rational_rank(req.references)
    if rank < k:
        raise ApiError(
            "linearly_dependent",
            f"reference curves are linearly dependent "
            f"(rank {rank} for {k} curves); whole request rejected",
        )


def _build_response(req: SolveRequest) -> tuple[SolveResponse, str]:
    result = solve_nonnegative_least_squares(req.observations, req.references)
    digest = hashlib.sha256(canonical_payload(req)).hexdigest()
    resp = SolveResponse(
        coefficients=[
            {
                "index": j,
                "value": rational_to_payload(result.coefficients[j]).model_dump(),
            }
            for j in range(len(req.references))
        ],
        points=[
            {
                "wavelength": req.wavelengths[i],
                "observed": req.observations[i],
                "reconstructed": rational_to_payload(
                    result.reconstructed[i]
                ).model_dump(),
                "residual": rational_to_payload(result.residuals[i]).model_dump(),
            }
            for i in range(len(req.observations))
        ],
        rss=rational_to_payload(result.rss).model_dump(),
        active_set=result.active,
        subsets_scanned=result.subsets_scanned,
        feasible_candidates=result.feasible_candidates,
        input_digest=digest,
    )
    return resp, digest


@app.post("/api/solve", response_model=SolveResponse)
async def solve(req: SolveRequest):
    _validate(req)
    resp, _ = _build_response(req)
    return resp


@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.post("/api/download")
async def download(req: SolveRequest):
    """CSV download computed from the *same* validated input/response pair.

    The client posts the exact request it solved; the server recomputes, so
    a download can never be fabricated from a stale response to new input.
    """
    _validate(req)
    resp, digest = _build_response(req)
    buf = io.StringIO()
    buf.write(f"# input_digest,{digest}\n")
    buf.write(
        "# coefficients,"
        + ";".join(f"{c.index}={c.value.fraction}" for c in resp.coefficients)
        + "\n"
    )
    buf.write(f"# rss,{resp.rss.fraction}\n")
    buf.write(
        "wavelength,observed,reconstructed_num,reconstructed_den,"
        "reconstructed_fraction,residual_num,residual_den,"
        "residual_fraction\n"
    )
    for p in resp.points:
        buf.write(
            f"{p.wavelength},{p.observed},"
            f"{p.reconstructed.numerator},{p.reconstructed.denominator},"
            f"{p.reconstructed.fraction},"
            f"{p.residual.numerator},{p.residual.denominator},"
            f"{p.residual.fraction}\n"
        )
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={
            "Content-Disposition": (
                f'attachment; filename="spectrum-{digest[:12]}.csv"'
            )
        },
    )


# ---------------------------------------------------------------------------
# Optional production hosting of the built React review page.
#
# Set SPECTRUM_WEB_DIST to the frontend ``dist`` directory (or keep the
# default repo layout).  API routes above always take precedence; only a
# present build directory is mounted.
# ---------------------------------------------------------------------------

_DIST = Path(
    os.environ.get(
        "SPECTRUM_WEB_DIST",
        Path(__file__).resolve().parents[2] / "frontend" / "dist",
    )
)

if _DIST.is_dir():
    app.mount(
        "/assets",
        StaticFiles(directory=_DIST / "assets"),
        name="assets",
    )

    @app.get("/", include_in_schema=False)
    async def index():
        return FileResponse(_DIST / "index.html")


@app.post("/api/grouped")
async def grouped(body: dict):
    try:
        return solve_grouped(body, _validate)
    except ApiError:
        raise
    except (ValueError, TypeError, KeyError, IndexError) as error:
        raise ApiError("invalid_grouped_request", str(error)) from error


@app.get("/groups")
async def grouped_page():
    return FileResponse(Path(__file__).with_name("groups.html"))
