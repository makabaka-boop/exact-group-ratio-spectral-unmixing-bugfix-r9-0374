"""Request/response models and exact (float-free) serialisation helpers."""

from __future__ import annotations

import json
from fractions import Fraction
from typing import Annotated

from pydantic import BaseModel, BeforeValidator, Field

# Pydantic accepts ``bool`` where ``int`` is expected; spectra are integer
# valued, so reject booleans explicitly.
_Int = Annotated[int, BeforeValidator(lambda v: _reject_bool(v))]


def _reject_bool(v: object) -> object:
    if isinstance(v, bool):
        raise ValueError("boolean is not an integer observation")
    return v


class SolveRequest(BaseModel):
    wavelengths: list[_Int] = Field(
        ..., description="Shared wavelength positions, strictly increasing."
    )
    observations: list[_Int] = Field(
        ..., description="Integer observed intensities, 20..80 points."
    )
    references: list[list[_Int]] = Field(
        ..., description="2..6 non-negative integer reference curves."
    )


class Rational(BaseModel):
    """Exact rational number: fraction strings plus an approximate decimal."""

    numerator: int
    denominator: int
    fraction: str  # "p/q" or "p"
    decimal: str  # rounded display value, never used for arithmetic


class Point(BaseModel):
    wavelength: int
    observed: int
    reconstructed: Rational
    residual: Rational  # observed - reconstructed


class Coefficient(BaseModel):
    index: int
    value: Rational


class SolveResponse(BaseModel):
    coefficients: list[Coefficient]
    points: list[Point]
    rss: Rational
    active_set: list[int]
    subsets_scanned: int
    feasible_candidates: int
    # SHA-256 of the canonical request body; ties the displayed/downloaded
    # result to exactly the input that produced it.
    input_digest: str


def rational_to_payload(value: Fraction) -> Rational:
    num, den = value.numerator, value.denominator
    frac = str(num) if den == 1 else f"{num}/{den}"
    return Rational(
        numerator=num,
        denominator=den,
        fraction=frac,
        decimal=_rounded_decimal(value, 12),
    )


def _rounded_decimal(value: Fraction, digits: int) -> str:
    """Round to ``digits`` significant digits using integer arithmetic only.

    A sign plus ``digits`` significant figures; trailing zeros and the
    decimal point are trimmed.  This is for display only.
    """
    if value == 0:
        return "0"
    sign = "-" if value < 0 else ""
    v = abs(value)
    num, den = v.numerator, v.denominator
    # Magnitude: floor(log10(v)), computed with integer adjustments.
    q, r = divmod(num, den)  # q >= 0; r < den
    if q > 0:
        scale = len(str(q)) - 1
    else:
        # v < 1: count leading zeros in the decimal expansion via
        # successive integer scaling (exact, no float log).
        scale = 0
        probe = num
        while probe < den:
            probe *= 10
            scale -= 1
    # Compute digits+1 significant figures as an integer, then round.
    shift = digits - 1 - scale
    if shift >= 0:
        scaled_num = num * 10**shift
        rounded, rem = divmod(scaled_num, den)
        if rem * 2 >= den:
            rounded += 1
        digits_str = str(rounded)
    else:
        trunc = 10 ** (-shift)
        rounded = num // trunc
        rem_pos = num % trunc
        if rem_pos * 2 >= den * trunc:
            rounded += 1
        digits_str = str(rounded)
    # Place the decimal point according to scale.
    if scale >= 0:
        if scale + 1 >= len(digits_str):
            digits_str += "0" * (scale + 1 - len(digits_str))
            out = digits_str
        else:
            out = digits_str[: scale + 1] + "." + digits_str[scale + 1 :]
    else:
        out = "0." + "0" * (-scale - 1) + digits_str
    out = out.rstrip(".").rstrip("0").rstrip(".") if "." in out else out
    if out in ("", "0"):
        out = "0"
    return sign + out


def canonical_payload(req: SolveRequest) -> bytes:
    """Canonical JSON encoding used for the input digest."""
    return json.dumps(
        {
            "wavelengths": req.wavelengths,
            "observations": req.observations,
            "references": req.references,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
