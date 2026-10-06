"""Fixed-ratio group unmixing built on the exact NNLS solver.

Lab practice: a few reference spectra are mixed in a *known* rational
ratio to form one group, and the fit then estimates a single non-negative
amount per group.  Curve ``j`` belonging to group ``g`` with ratio
``r_j`` is constrained to ``x_j = g_value * r_j`` with ``g_value >= 0``.
Substituting this into the ordinary objective turns the constrained
problem into a plain NNLS in the group variables with effective columns

    col_g = sum_{j in g} r_j * reference_j,

so the exhaustive-support solver applies unchanged and optimality is
still measured by the exact squared residual against the *original*
observations.  Because the groups partition the (linearly independent)
reference curves and every ratio is strictly positive, the effective
columns stay linearly independent.

Every reference curve must belong to exactly one group: duplicate,
missing or out-of-range members, duplicated or malformed group ids and
non-positive ratios reject the whole request — no partial result is ever
produced.  The response carries the group values, the per-curve
coefficients, the pointwise reconstruction/residuals and the total RSS,
all as exact rationals that are mutually consistent, plus a digest of
the complete request (input + groups) the result belongs to.
"""

from __future__ import annotations

import hashlib
import json
from fractions import Fraction

from .models import SolveRequest, canonical_payload, rational_to_payload
from .solver import solve_nonnegative_least_squares

# Ratios are bounded so a request cannot smuggle in arbitrarily large
# exact arithmetic; both parts must be positive integers within this cap.
MAX_RATIO_PART = 1_000_000


class GroupedError(ValueError):
    """A group-specification failure; ``code`` becomes the API error code."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def _rational(value: Fraction) -> dict:
    return rational_to_payload(value).model_dump()


def _parse_int(value: object, where: str) -> int:
    """Accept a JSON integer or a decimal-string integer; reject the rest."""
    if isinstance(value, bool):
        raise GroupedError("invalid_ratio", f"{where} must be an integer, got boolean")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        text = value.strip()
        digits = text[1:] if text[:1] in ("+", "-") else text
        if digits.isdigit():
            return int(text)
    raise GroupedError("invalid_ratio", f"{where} must be an integer, got {value!r}")


def _parse_ratio(raw: object, where: str) -> Fraction:
    if not isinstance(raw, dict):
        raise GroupedError(
            "invalid_ratio", f"{where}: ratio must be an object {{num, den}}"
        )
    if "num" not in raw or "den" not in raw:
        raise GroupedError("invalid_ratio", f"{where}: ratio needs 'num' and 'den'")
    num = _parse_int(raw["num"], f"{where}: ratio numerator")
    den = _parse_int(raw["den"], f"{where}: ratio denominator")
    if not 1 <= num <= MAX_RATIO_PART:
        raise GroupedError(
            "invalid_ratio",
            f"{where}: numerator {num} outside 1..{MAX_RATIO_PART}",
        )
    if not 1 <= den <= MAX_RATIO_PART:
        raise GroupedError(
            "invalid_ratio",
            f"{where}: denominator {den} outside 1..{MAX_RATIO_PART}",
        )
    return Fraction(num, den)


def _validate_group_id(raw: object, position: int):
    if isinstance(raw, bool) or not isinstance(raw, (str, int)):
        raise GroupedError(
            "invalid_group_id",
            f"group {position}: id must be a non-empty string or an integer",
        )
    if isinstance(raw, str) and not raw.strip():
        raise GroupedError(
            "invalid_group_id", f"group {position}: id must be a non-empty string"
        )
    return raw


def _normalise_groups(raw_groups: object, n_curves: int) -> list[dict]:
    """Validate the group list and return it with ratios as Fractions.

    The returned groups keep the request order; every reference curve
    index 0..n_curves-1 must appear in exactly one member entry.
    """
    if not isinstance(raw_groups, list) or not raw_groups:
        raise GroupedError(
            "invalid_grouped_request", "'groups' must be a non-empty list"
        )
    seen_ids: set[str] = set()
    seen_members: set[int] = set()
    normalised: list[dict] = []
    for position, group in enumerate(raw_groups):
        if not isinstance(group, dict):
            raise GroupedError(
                "invalid_grouped_request", f"group {position} must be an object"
            )
        if "id" not in group:
            raise GroupedError("invalid_group_id", f"group {position} has no 'id'")
        gid = _validate_group_id(group["id"], position)
        id_key = json.dumps(gid)
        if id_key in seen_ids:
            raise GroupedError("invalid_group_id", f"duplicate group id {gid!r}")
        seen_ids.add(id_key)
        members_raw = group.get("members")
        if not isinstance(members_raw, list) or not members_raw:
            raise GroupedError(
                "invalid_membership",
                f"group {gid!r} must list at least one member",
            )
        members: list[tuple[int, Fraction]] = []
        for m_position, member in enumerate(members_raw):
            where = f"group {gid!r} member {m_position}"
            if not isinstance(member, dict):
                raise GroupedError(
                    "invalid_membership", f"{where} must be an object"
                )
            index = member.get("index")
            if isinstance(index, bool) or not isinstance(index, int):
                raise GroupedError(
                    "invalid_membership", f"{where}: index must be an integer"
                )
            if not 0 <= index < n_curves:
                raise GroupedError(
                    "invalid_membership",
                    f"{where}: index {index} out of range 0..{n_curves - 1}",
                )
            if index in seen_members:
                raise GroupedError(
                    "invalid_membership",
                    f"reference curve {index} is assigned more than once; "
                    "every curve must belong to exactly one group",
                )
            seen_members.add(index)
            if "ratio" not in member:
                raise GroupedError("invalid_ratio", f"{where}: missing 'ratio'")
            members.append((index, _parse_ratio(member["ratio"], where)))
        normalised.append({"id": gid, "members": members})
    missing = sorted(set(range(n_curves)) - seen_members)
    if missing:
        raise GroupedError(
            "invalid_membership",
            f"reference curves {missing} belong to no group; "
            "every curve must belong to exactly one group",
        )
    return normalised


def _digest(req: SolveRequest, raw_groups: object) -> str:
    """SHA-256 of the canonical *complete* request (spectrum + groups)."""
    payload = json.dumps(
        {"input": json.loads(canonical_payload(req)), "groups": raw_groups},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _response(
    req: SolveRequest,
    groups: list[dict],
    group_values: list[Fraction],
    coefficients: list[Fraction],
    raw_groups: object,
) -> dict:
    reconstructed = [
        sum(
            (
                Fraction(req.references[j][i]) * coefficients[j]
                for j in range(len(coefficients))
            ),
            Fraction(0),
        )
        for i in range(len(req.observations))
    ]
    residuals = [
        Fraction(y) - value for y, value in zip(req.observations, reconstructed)
    ]
    return {
        "groupCoefficients": [
            {"id": group["id"], "value": _rational(value)}
            for group, value in zip(groups, group_values)
        ],
        "coefficients": [
            {"index": index, "value": _rational(value)}
            for index, value in enumerate(coefficients)
        ],
        "points": [
            {
                "wavelength": wave,
                "observed": observed,
                "reconstructed": _rational(value),
                "residual": _rational(residual),
            }
            for wave, observed, value, residual in zip(
                req.wavelengths, req.observations, reconstructed, residuals
            )
        ],
        "rss": _rational(sum((value * value for value in residuals), Fraction(0))),
        "input_digest": _digest(req, raw_groups),
    }


def solve_grouped(body: object, validate) -> dict:
    """Validate the complete grouped request and solve it exactly."""
    if not isinstance(body, dict):
        raise GroupedError(
            "invalid_grouped_request", "request body must be a JSON object"
        )
    if "input" not in body or "groups" not in body:
        raise GroupedError(
            "invalid_grouped_request", "request needs 'input' and 'groups'"
        )
    req = SolveRequest.model_validate(body["input"])
    validate(req)  # spectrum-level rules; rejects the whole request
    groups = _normalise_groups(body["groups"], len(req.references))

    # Effective group columns col_g = sum_j r_j * reference_j (Fractions).
    columns = [
        [
            sum(
                (ratio * req.references[index][i] for index, ratio in group["members"]),
                Fraction(0),
            )
            for i in range(len(req.observations))
        ]
        for group in groups
    ]
    fitted = solve_nonnegative_least_squares(req.observations, columns)

    # Per-curve coefficients x_j = g_value * r_j, in original curve order.
    # Groups and columns share the request order, so the zip below is
    # aligned no matter how the groups were listed.
    coefficients = [Fraction(0)] * len(req.references)
    for group, value in zip(groups, fitted.coefficients):
        for index, ratio in group["members"]:
            coefficients[index] = value * ratio

    return _response(req, groups, fitted.coefficients, coefficients, body["groups"])
