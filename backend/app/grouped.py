"""Fixed-ratio group unmixing, all in exact rational arithmetic.

The experimenter partitions the reference curves into groups and, within
each group, fixes a positive rational ratio for every member.  A single
non-negative *group variable* ``t_g`` is fitted per group; the coefficient
of an original curve ``j`` in group ``g`` with ratio ``r_j`` is forced to
``t_g * r_j``.  The fitted objective is the exact squared residual of the
**original** observations against the **original** curves:

    minimise  sum_i ( y_i - sum_g t_g * (sum_{j in g} r_j A_ij) )^2
    subject to t_g >= 0.

Defining the group blend column ``B_ig = sum_{j in g} r_j A_ij`` turns the
problem into non-negative least squares over the group columns, which the
existing exhaustive exact solver handles.  Everything below is float free.

Invalid spectra, groups or ratios reject the *whole* request: validation
runs before any arithmetic and raises :class:`GroupedError`, so a response
can never describe a partial or silently "repaired" partition.
"""

from __future__ import annotations

import hashlib
import io
import json
from fractions import Fraction
from typing import Callable

from .models import SolveRequest, rational_to_payload
from .solver import solve_nonnegative_least_squares

MAX_RATIO_PART = 1_000_000


class GroupedError(ValueError):
    """A group-list / ratio / membership validation failure."""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def rational(value: Fraction) -> dict:
    return rational_to_payload(value).model_dump()


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _parse_ratio(value: object) -> Fraction:
    if not isinstance(value, dict):
        raise GroupedError(
            "invalid_ratio", "member ratio must be an object {num, den}"
        )
    if set(value.keys()) != {"num", "den"}:
        raise GroupedError(
            "invalid_ratio", "ratio must contain exactly the keys num and den"
        )
    num = _ratio_part(value["num"], "ratio numerator")
    den = _ratio_part(value["den"], "ratio denominator")
    # Both parts are required strictly positive; the parser already bounds
    # them to 1..MAX_RATIO_PART.
    return Fraction(num, den)


def _ratio_part(value: object, what: str) -> int:
    # The documented wire form uses decimal strings ({"num": "1", "den": "2"});
    # bare JSON integers are accepted too.  Floats, booleans and malformed
    # strings are rejected wholesale.
    if isinstance(value, str):
        if not value.isdigit():
            raise GroupedError(
                "invalid_ratio",
                f"{what} must be an integer or decimal string, got {value!r}",
            )
        parsed = int(value)
    elif isinstance(value, bool) or not isinstance(value, int):
        raise GroupedError(
            "invalid_ratio",
            f"{what} must be an integer or decimal string, got "
            f"{type(value).__name__}",
        )
    else:
        parsed = value
    if not 1 <= parsed <= MAX_RATIO_PART:
        raise GroupedError(
            "invalid_ratio",
            f"{what} must be between 1 and {MAX_RATIO_PART}, got {parsed}",
        )
    return parsed


def parse_groups(body: object, k: int) -> list[dict]:
    """Validate the raw grouped body and return normalised group records.

    Each returned record is ``{"id": str, "members": [{"index": int,
    "ratio": Fraction}, ...]}`` ordered by group id with members ordered by
    index.  Ordering is canonicalisation, not a semantic choice: permuting
    the incoming group/member list cannot change coefficients.
    """
    if not isinstance(body, dict):
        raise GroupedError("invalid_grouped_request", "request body must be an object")
    if "input" not in body or "groups" not in body:
        raise GroupedError(
            "invalid_grouped_request", "body must contain 'input' and 'groups'"
        )
    groups_raw = body["groups"]
    if not isinstance(groups_raw, list) or not groups_raw:
        raise GroupedError(
            "invalid_group", "groups must be a non-empty list of group objects"
        )
    if len(groups_raw) > k:
        raise GroupedError(
            "invalid_group",
            f"cannot have {len(groups_raw)} groups for only {k} curves",
        )

    groups: list[dict] = []
    seen_ids: set[str] = set()
    for gi, group in enumerate(groups_raw):
        if not isinstance(group, dict):
            raise GroupedError("invalid_group", f"group {gi} must be an object")
        if set(group.keys()) != {"id", "members"}:
            raise GroupedError(
                "invalid_group",
                f"group {gi} must contain exactly the keys id and members",
            )
        gid = group["id"]
        if not isinstance(gid, str) or not gid.strip():
            raise GroupedError(
                "invalid_group", f"group {gi} id must be a non-empty string"
            )
        if gid in seen_ids:
            raise GroupedError("invalid_group", f"duplicate group id: {gid!r}")
        seen_ids.add(gid)

        members_raw = group["members"]
        if not isinstance(members_raw, list) or not members_raw:
            raise GroupedError(
                "invalid_member",
                f"group {gid!r} must contain a non-empty members list",
            )
        members: list[dict] = []
        seen_indices: set[int] = set()
        for mi, member in enumerate(members_raw):
            if not isinstance(member, dict):
                raise GroupedError(
                    "invalid_member",
                    f"member {mi} of group {gid!r} must be an object",
                )
            if set(member.keys()) != {"index", "ratio"}:
                raise GroupedError(
                    "invalid_member",
                    f"member {mi} of group {gid!r} must contain exactly "
                    "the keys index and ratio",
                )
            index = member["index"]
            if isinstance(index, bool) or not isinstance(index, int):
                raise GroupedError(
                    "invalid_member",
                    f"member index must be an integer, got {type(index).__name__}",
                )
            if not 0 <= index < k:
                raise GroupedError(
                    "invalid_member",
                    f"member index {index} in group {gid!r} is out of range "
                    f"(0..{k - 1})",
                )
            if index in seen_indices:
                raise GroupedError(
                    "invalid_member",
                    f"curve {index} listed more than once in group {gid!r}",
                )
            seen_indices.add(index)
            members.append({"index": index, "ratio": _parse_ratio(member["ratio"])})
        groups.append({"id": gid, "members": members})

    # Exactly-once partition of the original curves: no duplicates across
    # groups and no omissions.
    all_indices = sorted(
        index for group in groups for index in (m["index"] for m in group["members"])
    )
    if len(all_indices) != len(set(all_indices)):
        dup = {j for j in all_indices if all_indices.count(j) > 1}
        raise GroupedError(
            "invalid_member",
            f"curve index {sorted(dup)} belongs to more than one group",
        )
    missing = sorted(set(range(k)) - set(all_indices))
    if missing:
        raise GroupedError(
            "invalid_member",
            f"every curve must belong to a group; missing indices: {missing}",
        )

    groups.sort(key=lambda g: g["id"])
    for group in groups:
        group["members"].sort(key=lambda m: m["index"])
    return groups


# ---------------------------------------------------------------------------
# Canonical digest
# ---------------------------------------------------------------------------


def _ratio_pair(ratio: Fraction) -> dict:
    # Ratios are reduced in the canonical form, so 2/2 and 1/1 bind to the
    # same request while both remaining within the declared part bounds.
    return {"num": ratio.numerator, "den": ratio.denominator}


def canonical_grouped_payload(
    req: SolveRequest, groups: list[dict]
) -> bytes:
    """Deterministic JSON of the spectra plus the normalised group list."""
    return json.dumps(
        {
            "input": {
                "wavelengths": req.wavelengths,
                "observations": req.observations,
                "references": req.references,
            },
            "groups": [
                {
                    "id": group["id"],
                    "members": [
                        {"index": m["index"], "ratio": _ratio_pair(m["ratio"])}
                        for m in group["members"]
                    ],
                }
                for group in groups
            ],
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


# ---------------------------------------------------------------------------
# Solve and serialise
# ---------------------------------------------------------------------------


def _solve(
    req: SolveRequest, groups: list[dict]
) -> tuple[list[Fraction], list[Fraction], list[Fraction], list[Fraction], Fraction]:
    n = len(req.observations)
    # Group blend columns B_g = sum_{j in g} r_j * A_j, exact fractions.
    columns = [
        [
            sum(
                (
                    Fraction(req.references[m["index"]][i]) * m["ratio"]
                    for m in group["members"]
                ),
                Fraction(0),
            )
            for i in range(n)
        ]
        for group in groups
    ]
    fitted = solve_nonnegative_least_squares(
        req.observations, columns, allow_singular=True
    )

    # Original curve coefficients follow the fixed ratios: x_j = t_g * r_j.
    coefficients = [Fraction(0)] * len(req.references)
    for group, value in zip(groups, fitted.coefficients):
        for member in group["members"]:
            coefficients[member["index"]] = value * member["ratio"]

    reconstructed = [
        sum(
            (
                Fraction(req.references[j][i]) * coefficients[j]
                for j in range(len(coefficients))
            ),
            Fraction(0),
        )
        for i in range(n)
    ]
    residuals = [
        Fraction(y) - value for y, value in zip(req.observations, reconstructed)
    ]
    rss = sum((value * value for value in residuals), Fraction(0))
    return fitted.coefficients, coefficients, reconstructed, residuals, rss


def build_grouped_result(body: object, validate: Callable[[SolveRequest], None]):
    """Validate everything, then solve; returns ``(payload, digest, csv)``.

    Validation of the spectra and of the group list both happen before any
    result is produced, so callers can reject the whole request atomically.
    """
    if not isinstance(body, dict) or "input" not in body:
        raise GroupedError("invalid_grouped_request", "body must contain 'input'")
    # A schema failure here is a whole-request rejection, not a 500.
    try:
        req = SolveRequest.model_validate(body["input"])
    except Exception as exc:  # pydantic.ValidationError
        raise GroupedError(
            "invalid_schema", f"invalid spectrum input: {exc}"
        ) from exc
    validate(req)
    groups = parse_groups(body, len(req.references))

    group_values, coefficients, reconstructed, residuals, rss = _solve(req, groups)
    digest = hashlib.sha256(canonical_grouped_payload(req, groups)).hexdigest()

    payload = {
        "input_digest": digest,
        "groups": [
            {
                "id": group["id"],
                "members": [
                    {"index": m["index"], "ratio": rational(m["ratio"])}
                    for m in group["members"]
                ],
            }
            for group in groups
        ],
        "groupCoefficients": [
            {"id": group["id"], "value": rational(value)}
            for group, value in zip(groups, group_values)
        ],
        "coefficients": [
            {"index": index, "value": rational(value)}
            for index, value in enumerate(coefficients)
        ],
        "points": [
            {
                "wavelength": wave,
                "observed": observed,
                "reconstructed": rational(recon),
                "residual": rational(resid),
            }
            for wave, observed, recon, resid in zip(
                req.wavelengths, req.observations, reconstructed, residuals
            )
        ],
        "rss": rational(rss),
    }
    return payload, digest, build_grouped_csv(payload, digest)


def solve_grouped(body: object, validate: Callable[[SolveRequest], None]) -> dict:
    payload, _digest, _csv = build_grouped_result(body, validate)
    return payload


def grouped_csv(body: object, validate: Callable[[SolveRequest], None]):
    _payload, digest, csv_text = build_grouped_result(body, validate)
    return digest, csv_text


def build_grouped_csv(result: dict, digest: str) -> str:
    """Exact CSV of the same result object the chart is rendered from."""
    buf = io.StringIO()
    buf.write(f"# input_digest,{digest}\n")
    buf.write(
        "# group_coefficients,"
        + ";".join(
            f"{g['id']}={g['value']['fraction']}" for g in result["groupCoefficients"]
        )
        + "\n"
    )
    buf.write(
        "# coefficients,"
        + ";".join(
            f"{c['index']}={c['value']['fraction']}" for c in result["coefficients"]
        )
        + "\n"
    )
    buf.write(f"# rss,{result['rss']['fraction']}\n")
    buf.write(
        "wavelength,observed,reconstructed_num,reconstructed_den,"
        "reconstructed_fraction,residual_num,residual_den,"
        "residual_fraction\n"
    )
    for p in result["points"]:
        buf.write(
            f"{p['wavelength']},{p['observed']},"
            f"{p['reconstructed']['numerator']},{p['reconstructed']['denominator']},"
            f"{p['reconstructed']['fraction']},"
            f"{p['residual']['numerator']},{p['residual']['denominator']},"
            f"{p['residual']['fraction']}\n"
        )
    return buf.getvalue()
