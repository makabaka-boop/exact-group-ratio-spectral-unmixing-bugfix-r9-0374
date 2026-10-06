from fractions import Fraction
from .models import SolveRequest, rational_to_payload
from .solver import solve_nonnegative_least_squares


def rational(value):
    return rational_to_payload(value).model_dump()


def response(req, groups, group_values, coefficients):
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
                "reconstructed": rational(value),
                "residual": rational(residual),
            }
            for wave, observed, value, residual in zip(
                req.wavelengths, req.observations, reconstructed, residuals
            )
        ],
        "rss": rational(sum((value * value for value in residuals), Fraction(0))),
    }


def solve_grouped(body, validate):
    req = SolveRequest.model_validate(body["input"])
    validate(req)
    groups = body["groups"]
    columns = [
        [
            sum(req.references[member["index"]][i] for member in group["members"])
            for i in range(len(req.observations))
        ]
        for group in sorted(groups, key=lambda group: group["id"])
    ]
    fitted = solve_nonnegative_least_squares(req.observations, columns)
    coefficients = [Fraction(0)] * len(req.references)
    for group, value in zip(groups, fitted.coefficients):
        for member in group["members"]:
            coefficients[member["index"]] = value
    return response(req, groups, fitted.coefficients, coefficients)
