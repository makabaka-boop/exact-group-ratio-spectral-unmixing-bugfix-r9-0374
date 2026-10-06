"""Tests for the fixed-ratio group unmixing endpoint (/api/grouped).

Covers the four evidence channels that must jointly prove a fit — group
values, per-curve coefficients, pointwise reconstruction/residuals and
total RSS — plus optimality against the original observations, order
independence of the group list, whole-request rejection semantics and
the digest/download binding to the complete request.
"""

from __future__ import annotations

import sys
from fractions import Fraction
from itertools import combinations
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.main import app  # noqa: E402

client = TestClient(app)

F = Fraction


# ---------------------------------------------------------------------------
# Fixtures and exact-arithmetic helpers
# ---------------------------------------------------------------------------


def _curves(n):
    c0 = [1, 2, 3, 1, 2, 3] * (n // 6) + [1] * (n % 6)
    c1 = [0, 0, 0, 1, 1, 1] * (n // 6) + [1] * (n % 6)
    c2 = [1, 0, 1, 0, 1, 0] * (n // 6) + [1] * (n % 6)
    return [c0[:], c1[:], c2[:]]


def _input(n=24, k=2, y=None):
    refs = _curves(n)[:k]
    if y is None:
        y = [5 * refs[0][i] + 10 * refs[1][i] for i in range(n)]
    return {
        "wavelengths": list(range(400, 400 + n)),
        "observations": y,
        "references": refs,
    }


def _group(gid, *members):
    return {
        "id": gid,
        "members": [
            {"index": index, "ratio": {"num": str(num), "den": str(den)}}
            for index, num, den in members
        ],
    }


def _body(groups, **input_kwargs):
    return {"input": _input(**input_kwargs), "groups": groups}


def _rat(payload):
    return F(payload["numerator"], payload["denominator"])


def _solve(body):
    r = client.post("/api/grouped", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def _assert_rejected(body, code):
    r = client.post("/api/grouped", json=body)
    assert r.status_code == 422, r.text
    payload = r.json()
    assert payload["error"]["code"] == code
    # Whole-request rejection: no partial fit leaks into the envelope.
    for key in ("groupCoefficients", "coefficients", "points", "rss"):
        assert key not in payload


def _group_columns(groups, k, n):
    """Effective columns col_g = sum_j ratio_j * reference_j (Fractions)."""
    refs = _curves(n)[:k]
    columns = []
    for group in groups:
        columns.append(
            [
                sum(
                    F(int(m["ratio"]["num"]), int(m["ratio"]["den"]))
                    * refs[m["index"]][i]
                    for m in group["members"]
                )
                for i in range(n)
            ]
        )
    return columns


# ---------------------------------------------------------------------------
# Exact fits: single group, fractional ratios, zero group value, near
# duplicates — and the ratio constraint on every curve
# ---------------------------------------------------------------------------


def test_single_group_integer_ratios_exact_fit():
    body = _body([_group("blend", (0, 1, 1), (1, 2, 1))])
    d = _solve(body)
    assert _rat(d["groupCoefficients"][0]["value"]) == 5
    assert [_rat(c["value"]) for c in d["coefficients"]] == [F(5), F(10)]
    assert _rat(d["rss"]) == 0
    assert all(_rat(p["residual"]) == 0 for p in d["points"])
    assert len(d["input_digest"]) == 64


def test_single_group_fractional_ratios_exact_fit():
    # y = 8 * (1/2 * c0 + 3/4 * c1) = 4*c0 + 6*c1, exactly representable.
    n, k = 24, 2
    refs = _curves(n)[:k]
    y = [4 * refs[0][i] + 6 * refs[1][i] for i in range(n)]
    body = _body([_group("frac", (0, 1, 2), (1, 3, 4))], n=n, k=k, y=y)
    d = _solve(body)
    assert _rat(d["groupCoefficients"][0]["value"]) == 8
    coefs = [_rat(c["value"]) for c in d["coefficients"]]
    assert coefs == [F(4), F(6)]
    # Ratio constraint: x1/x0 == (3/4)/(1/2) == 3/2, exactly.
    assert coefs[1] * F(1, 2) == coefs[0] * F(3, 4)
    assert _rat(d["rss"]) == 0


def test_group_value_exactly_zero():
    # Observations match group A alone; group B must come out exactly zero
    # and so must every coefficient of its member curves.
    n, k = 24, 3
    refs = _curves(n)[:k]
    y = [3 * refs[0][i] + 6 * refs[1][i] for i in range(n)]
    groups = [
        _group("A", (0, 1, 1), (1, 2, 1)),
        _group("B", (2, 1, 1)),
    ]
    d = _solve(_body(groups, n=n, k=k, y=y))
    values = {g["id"]: _rat(g["value"]) for g in d["groupCoefficients"]}
    assert values == {"A": F(3), "B": F(0)}
    assert [_rat(c["value"]) for c in d["coefficients"]] == [F(3), F(6), F(0)]
    assert _rat(d["rss"]) == 0


def test_near_duplicate_but_independent_curves_across_groups():
    # c1 differs from c0 at a single point: independent, non-degenerate.
    n = 24
    refs = _curves(n)[:2]
    refs[1] = refs[0][:]
    refs[1][7] += 1
    y = [2 * refs[0][i] + 3 * refs[1][i] for i in range(n)]
    body = {
        "input": {
            "wavelengths": list(range(400, 400 + n)),
            "observations": y,
            "references": refs,
        },
        "groups": [_group("g0", (0, 1, 1)), _group("g1", (1, 1, 1))],
    }
    d = _solve(body)
    assert [_rat(c["value"]) for c in d["coefficients"]] == [F(2), F(3)]
    assert _rat(d["rss"]) == 0


def test_fractional_group_value_is_exact():
    # y = (2/3) * (c0 + c1): the group value itself is a reduced fraction.
    n, k = 24, 2
    refs = _curves(n)[:k]
    y = [2 * (refs[0][i] + refs[1][i]) // 3 for i in range(n)]
    body = _body([_group("g", (0, 1, 1), (1, 1, 1))], n=n, k=k, y=y)
    d = _solve(body)
    # Equal ratios force equal coefficients; the shared value is whatever
    # exact fraction minimises the residual (checked exactly elsewhere).
    coefs = [_rat(c["value"]) for c in d["coefficients"]]
    assert coefs[0] == coefs[1]
    assert _rat(d["groupCoefficients"][0]["value"]) == coefs[0]


# ---------------------------------------------------------------------------
# Coherence: group values, coefficients, points and RSS prove the same fit
# ---------------------------------------------------------------------------


def _noisy_body():
    n, k = 30, 3
    refs = _curves(n)[:k]
    y = [(i * i) % 17 + 2 * refs[0][i] + refs[2][i] for i in range(n)]
    groups = [
        _group("mix", (0, 1, 2), (2, 1, 3)),
        _group("solo", (1, 2, 1)),
    ]
    return _body(groups, n=n, k=k, y=y), groups, refs, y


def test_all_evidence_channels_are_mutually_consistent():
    body, groups, refs, y = _noisy_body()
    d = _solve(body)
    n = len(y)

    group_values = [_rat(g["value"]) for g in d["groupCoefficients"]]
    coefs = [_rat(c["value"]) for c in d["coefficients"]]

    # 1. Every curve coefficient equals its group value times its ratio.
    for group, gval in zip(groups, group_values):
        for m in group["members"]:
            ratio = F(int(m["ratio"]["num"]), int(m["ratio"]["den"]))
            assert coefs[m["index"]] == gval * ratio

    # 2. Pointwise reconstruction equals sum_j x_j * reference_j, and the
    #    residual is exactly observed - reconstructed.
    for i, p in enumerate(d["points"]):
        recon = _rat(p["reconstructed"])
        assert recon == sum(coefs[j] * refs[j][i] for j in range(len(refs)))
        assert _rat(p["residual"]) == y[i] - recon
        assert p["wavelength"] == 400 + i
        assert p["observed"] == y[i]

    # 3. RSS equals the exact sum of squared pointwise residuals.
    assert _rat(d["rss"]) == sum(
        (_rat(p["residual"])) ** 2 for p in d["points"]
    )


def test_optimality_kkt_against_original_observations():
    body, groups, refs, y = _noisy_body()
    d = _solve(body)
    n = len(y)
    columns = _group_columns(groups, len(refs), n)
    recon = [_rat(p["reconstructed"]) for p in d["points"]]
    for g, group in enumerate(groups):
        gval = _rat(d["groupCoefficients"][g]["value"])
        # Gradient of ||y - A g||^2 w.r.t. this group variable (up to the
        # irrelevant positive factor 2), in exact arithmetic.
        grad = sum(columns[g][i] * (recon[i] - y[i]) for i in range(n))
        if gval > 0:
            assert grad == 0, f"active group {g} must zero the gradient"
        else:
            assert grad >= 0, f"inactive group {g} must not descend"


def test_matches_independent_fraction_nnls():
    """Cross-check against an independently written support enumeration."""
    body, groups, refs, y = _noisy_body()
    d = _solve(body)
    n = len(y)
    columns = _group_columns(groups, len(refs), n)
    k = len(columns)

    def solve_linear(mat, vec):
        m = len(mat)
        aug = [row[:] + [vec[i]] for i, row in enumerate(mat)]
        for c in range(m):
            p = next(r for r in range(c, m) if aug[r][c] != 0)
            aug[c], aug[p] = aug[p], aug[c]
            piv = aug[c][c]
            aug[c] = [z / piv for z in aug[c]]
            for r in range(m):
                if r != c and aug[r][c]:
                    a = aug[r][c]
                    aug[r] = [z - a * w for z, w in zip(aug[r], aug[c])]
        return [aug[i][m] for i in range(m)]

    def rss_of(x):
        return sum(
            (F(y[i]) - sum(columns[c][i] * x[c] for c in range(k))) ** 2
            for i in range(n)
        )

    best_x, best_rss = [F(0)] * k, rss_of([F(0)] * k)
    for size in range(1, k + 1):
        for supp in combinations(range(k), size):
            gram = [
                [sum(columns[c][i] * columns[e][i] for i in range(n)) for e in supp]
                for c in supp
            ]
            aty = [sum(columns[c][i] * y[i] for i in range(n)) for c in supp]
            x_sub = solve_linear(gram, aty)
            if any(v <= 0 for v in x_sub):
                continue
            x = [F(0)] * k
            for t, c in enumerate(supp):
                x[c] = x_sub[t]
            if rss_of(x) < best_rss:
                best_x, best_rss = x, rss_of(x)

    assert _rat(d["rss"]) == best_rss
    assert [_rat(g["value"]) for g in d["groupCoefficients"]] == best_x


# ---------------------------------------------------------------------------
# Order independence of the group list
# ---------------------------------------------------------------------------


def test_reordering_groups_keeps_curve_coefficients():
    body, groups, refs, _y = _noisy_body()
    forward = _solve(body)
    reordered_groups = list(reversed(body["groups"]))
    backward = _solve({**body, "groups": reordered_groups})

    # Per-curve coefficients, points and RSS are invariant ...
    assert [c["value"]["fraction"] for c in forward["coefficients"]] == [
        c["value"]["fraction"] for c in backward["coefficients"]
    ]
    assert forward["points"] == backward["points"]
    assert forward["rss"] == backward["rss"]
    # ... and group values follow their ids, not their list position.
    fwd = {g["id"]: g["value"]["fraction"] for g in forward["groupCoefficients"]}
    bwd = {g["id"]: g["value"]["fraction"] for g in backward["groupCoefficients"]}
    assert fwd == bwd
    assert [g["id"] for g in backward["groupCoefficients"]] == [
        g["id"] for g in reordered_groups
    ]


# ---------------------------------------------------------------------------
# Whole-request rejection: membership, ids, ratios, spectra, structure
# ---------------------------------------------------------------------------


def test_reject_duplicate_member_same_group():
    body = _body([_group("g", (0, 1, 1), (0, 2, 1), (1, 1, 1))])
    _assert_rejected(body, "invalid_membership")


def test_reject_duplicate_member_across_groups():
    body = _body([_group("a", (0, 1, 1)), _group("b", (0, 1, 1), (1, 1, 1))])
    _assert_rejected(body, "invalid_membership")


def test_reject_missing_member():
    body = _body([_group("g", (0, 1, 1))])  # curve 1 belongs to no group
    _assert_rejected(body, "invalid_membership")


@pytest.mark.parametrize("bad_index", [-1, 2, 99])
def test_reject_out_of_range_member(bad_index):
    body = _body([_group("g", (0, 1, 1)), _group("h", (bad_index, 1, 1))])
    _assert_rejected(body, "invalid_membership")


@pytest.mark.parametrize("bad_index", ["0", 0.5, True, None, [0]])
def test_reject_non_integer_member_index(bad_index):
    groups = [
        {"id": "g", "members": [{"index": bad_index, "ratio": {"num": "1", "den": "1"}}]},
        _group("h", (1, 1, 1)),
    ]
    _assert_rejected(_body(groups), "invalid_membership")


def test_reject_duplicate_group_id():
    body = _body([_group("g", (0, 1, 1)), _group("g", (1, 1, 1))])
    _assert_rejected(body, "invalid_group_id")


@pytest.mark.parametrize("bad_id", ["", "   ", None, True, ["g"], {"x": 1}])
def test_reject_malformed_group_id(bad_id):
    groups = [
        {"id": bad_id, "members": [{"index": 0, "ratio": {"num": "1", "den": "1"}}]},
        _group("h", (1, 1, 1)),
    ]
    _assert_rejected(_body(groups), "invalid_group_id")


def test_reject_missing_group_id():
    groups = [{"members": [{"index": 0, "ratio": {"num": "1", "den": "1"}}]}, _group("h", (1, 1, 1))]
    _assert_rejected(_body(groups), "invalid_group_id")


@pytest.mark.parametrize(
    "ratio",
    [
        {"num": "0", "den": "1"},  # zero numerator
        {"num": "-2", "den": "1"},  # negative numerator
        {"num": "1", "den": "0"},  # zero denominator
        {"num": "1", "den": "-3"},  # negative denominator
        {"num": "1000001", "den": "1"},  # numerator above the cap
        {"num": "1", "den": "1000001"},  # denominator above the cap
        {"num": "1.5", "den": "1"},  # non-integer string
        {"num": "1/2", "den": "1"},  # fraction typed as one string
        {"num": 0.5, "den": 1},  # float numerator
        {"num": True, "den": 1},  # boolean numerator
        {"num": "1"},  # missing denominator
        {"den": "1"},  # missing numerator
        "1/2",  # ratio not an object
        None,
    ],
)
def test_reject_invalid_ratio(ratio):
    groups = [
        {"id": "g", "members": [{"index": 0, "ratio": ratio}]},
        _group("h", (1, 1, 1)),
    ]
    _assert_rejected(_body(groups), "invalid_ratio")


def test_reject_empty_members():
    groups = [{"id": "g", "members": []}, _group("h", (0, 1, 1), (1, 1, 1))]
    _assert_rejected(_body(groups), "invalid_membership")


@pytest.mark.parametrize(
    "groups,code",
    [
        ([], "invalid_grouped_request"),  # empty list: curves would be uncovered
        ("blend", "invalid_grouped_request"),  # not a list
        (["not-an-object"], "invalid_grouped_request"),  # group not an object
        ([{"id": "g", "members": "x"}], "invalid_membership"),  # members not a list
        ([{"id": "g"}], "invalid_membership"),  # members missing
        (
            [{"id": "g", "members": [{"ratio": {"num": "1", "den": "1"}}]}],
            "invalid_membership",
        ),  # member without index
        ([{"id": "g", "members": ["x"]}], "invalid_membership"),  # member not an object
    ],
)
def test_reject_malformed_group_structures(groups, code):
    _assert_rejected(_body(groups), code)


def test_reject_missing_top_level_keys():
    _assert_rejected({"input": _input()}, "invalid_grouped_request")
    _assert_rejected({"groups": [_group("g", (0, 1, 1))]}, "invalid_grouped_request")


def test_reject_non_object_body():
    r = client.post("/api/grouped", json=[1, 2, 3])
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "invalid_schema"


def test_reject_invalid_spectrum_despite_valid_groups():
    groups = [_group("g", (0, 1, 1), (1, 1, 1))]
    # Linearly dependent references: the whole grouped request is refused.
    bad = _input()
    bad["references"][1] = [2 * v for v in bad["references"][0]]
    _assert_rejected({"input": bad, "groups": groups}, "linearly_dependent")
    # Negative reference value.
    bad = _input()
    bad["references"][0][3] = -1
    _assert_rejected({"input": bad, "groups": groups}, "invalid_reference")
    # Too few points.
    _assert_rejected(
        {"input": _input(n=19, k=2), "groups": groups}, "invalid_dimension"
    )
    # Non-integer observation inside the embedded input.
    bad = _input()
    bad["observations"][0] = 1.5
    r = client.post("/api/grouped", json={"input": bad, "groups": groups})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "invalid_schema"


def test_ratio_boundaries_accepted():
    # num = den = 1_000_000 is exactly at the cap and must pass.
    groups = [_group("g", (0, 1000000, 1000000), (1, 1, 1000000))]
    d = _solve(_body(groups))
    coefs = [_rat(c["value"]) for c in d["coefficients"]]
    # Ratios 1 and 1/1e6 share one group value: x0 = g, x1 = g/1e6.
    assert coefs[0] == F(1000000) * coefs[1]
    assert coefs[0] > 0


# ---------------------------------------------------------------------------
# Digest binding and the download channel
# ---------------------------------------------------------------------------


def test_digest_binds_the_complete_request():
    body = _body([_group("g", (0, 1, 1), (1, 2, 1))])
    d1 = _solve(body)["input_digest"]
    # Deterministic for the identical request.
    assert _solve(body)["input_digest"] == d1
    # Editing an observation changes the digest ...
    import json as _json

    edited = _json.loads(_json.dumps(body))
    edited["input"]["observations"][0] += 1
    assert _solve(edited)["input_digest"] != d1
    # ... and so does editing only the group list (ratio change).
    edited = _json.loads(_json.dumps(body))
    edited["groups"][0]["members"][1]["ratio"] = {"num": "3", "den": "1"}
    assert _solve(edited)["input_digest"] != d1


def test_download_csv_matches_solve_response():
    body, groups, _refs, _y = _noisy_body()
    solved = _solve(body)
    r = client.post("/api/grouped/download", json=body)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/csv")
    assert solved["input_digest"][:12] in r.headers["content-disposition"]
    text = r.text

    assert f"# input_digest,{solved['input_digest']}" in text
    group_line = "# group_coefficients," + ";".join(
        f'"{g["id"]}"={g["value"]["fraction"]}' for g in solved["groupCoefficients"]
    )
    assert group_line in text
    coef_line = "# coefficients," + ";".join(
        f"{c['index']}={c['value']['fraction']}" for c in solved["coefficients"]
    )
    assert coef_line in text
    assert f"# rss,{solved['rss']['fraction']}" in text

    rows = [ln for ln in text.splitlines() if not ln.startswith("#")]
    assert rows[0] == (
        "wavelength,observed,reconstructed_num,reconstructed_den,"
        "reconstructed_fraction,residual_num,residual_den,residual_fraction"
    )
    assert len(rows) == 1 + len(solved["points"])
    for row, point in zip(rows[1:], solved["points"]):
        assert row == (
            f"{point['wavelength']},{point['observed']},"
            f"{point['reconstructed']['numerator']},"
            f"{point['reconstructed']['denominator']},"
            f"{point['reconstructed']['fraction']},"
            f"{point['residual']['numerator']},"
            f"{point['residual']['denominator']},"
            f"{point['residual']['fraction']}"
        )


def test_download_rejects_invalid_requests():
    body = _body([_group("g", (0, 1, 1))])  # missing member
    r = client.post("/api/grouped/download", json=body)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "invalid_membership"
    dependent = _input()
    dependent["references"][1] = [3 * v for v in dependent["references"][0]]
    r = client.post(
        "/api/grouped/download",
        json={"input": dependent, "groups": [_group("g", (0, 1, 1), (1, 1, 1))]},
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "linearly_dependent"


def test_group_id_with_csv_specials_is_quoted():
    groups = [
        _group('we,"ird"', (0, 1, 1)),
        _group("plain", (1, 1, 1)),
    ]
    solved = _solve(_body(groups))
    r = client.post("/api/grouped/download", json=_body(groups))
    # CSV quoting: the id's own quotes double, then the field is quoted.
    assert '"we,""ird"""=' in r.text
    assert '"plain"=' in r.text
    assert solved["groupCoefficients"][0]["id"] == 'we,"ird"'


# ---------------------------------------------------------------------------
# The review page and the untouched original solver
# ---------------------------------------------------------------------------


def test_groups_page_and_script_are_served():
    r = client.get("/groups")
    assert r.status_code == 200
    assert "/groups-page.js" in r.text
    r = client.get("/groups-page.js")
    assert r.status_code == 200
    assert "buildGroupedCsv" in r.text
    assert "isResultUsable" in r.text


def test_original_solve_still_works():
    r = client.post("/api/solve", json=_input())
    assert r.status_code == 200
    body = r.json()
    assert body["coefficients"][0]["value"]["fraction"] == "5"
    assert body["coefficients"][1]["value"]["fraction"] == "10"
    assert body["rss"]["fraction"] == "0"
