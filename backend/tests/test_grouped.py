"""Tests for fixed-ratio group unmixing (/api/grouped).

Covers: ratio-forced coefficients, optimality against the *original*
observations by an independent KKT check on the group blend columns,
permutation invariance of the group list, exact rational consistency of
the point evidence, the single-group and zero-variable cases, whole
request rejection for every illegal membership/ratio/spectrum case,
digest binding, and the chart/download sharing one complete request.
"""

from __future__ import annotations

import copy
import json as jsonlib
import sys
from fractions import Fraction
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.main import app  # noqa: E402

client = TestClient(app)
F = Fraction


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _data(n=24, k=2):
    wl = list(range(400, 400 + n))
    c0 = [1, 2, 3] * (n // 3) + [1] * (n % 3)
    c1 = [0, 0, 0, 1, 1, 1] * (n // 6) + [1] * (n % 6)
    refs = [c0[:n], c1[:n]]
    if k >= 3:
        refs.append([(i % 5) for i in range(n)])
    if k >= 4:
        refs.append([1 + (i % 2) for i in range(n)])
    return wl, refs


def _ratio(num, den):
    return {"num": str(num), "den": str(den)}


def _body(*, n=24, observations=None, groups=None, refs=None):
    wl, default_refs = _data(n=n)
    refs = refs if refs is not None else default_refs[:2]
    return {
        "input": {
            "wavelengths": wl,
            "observations": observations if observations is not None else [0] * n,
            "references": refs,
        },
        "groups": groups if groups is not None else [
            {"id": "g", "members": [
                {"index": 0, "ratio": _ratio(1, 1)},
                {"index": 1, "ratio": _ratio(1, 1)},
            ]}
        ],
    }


def _group_columns(refs, groups):
    """Independently recompute B_ig = sum r_j A_ij."""
    n = len(refs[0])
    cols = []
    for g in groups:
        col = [F(0) for _ in range(n)]
        for m in g["members"]:
            r = F(int(m["ratio"]["num"]), int(m["ratio"]["den"]))
            for i in range(n):
                col[i] += F(refs[m["index"]][i]) * r
        cols.append(col)
    return cols


def _group_kkt_optimal(y, cols, t):
    """KKT for NNLS over group blend columns."""
    n, g = len(y), len(cols)
    for a in range(g):
        grad = sum(
            F(cols[a][i])
            * (sum(F(cols[b][i]) * t[b] for b in range(g)) - F(y[i]))
            for i in range(n)
        )
        if t[a] == 0:
            if grad < 0:
                return False
        elif grad != 0:
            return False
    return True


def _as_frac(payload):
    return F(payload["numerator"], payload["denominator"])


# ---------------------------------------------------------------------------
# Correctness
# ---------------------------------------------------------------------------


def test_forced_ratios_exact_fit_and_per_curve_coefficients():
    n = 24
    wl, refs = _data(n=n, k=3)
    c0, c1, c2 = refs
    # t_A = 2 on ratios (1/2, 1); t_B = 3 on ratio (1/3)
    # y = 2*(c0/2 + c1) + 3*(c2/3) = c0 + 2 c1 + c2
    y = [c0[i] + 2 * c1[i] + c2[i] for i in range(n)]
    groups = [
        {"id": "A", "members": [
            {"index": 0, "ratio": _ratio(1, 2)},
            {"index": 1, "ratio": _ratio(1, 1)},
        ]},
        {"id": "B", "members": [
            {"index": 2, "ratio": _ratio(1, 3)},
        ]},
    ]
    r = client.post("/api/grouped", json=_body(n=n, observations=y, groups=groups, refs=refs))
    assert r.status_code == 200, r.text
    b = r.json()

    assert [(g["id"], g["value"]["fraction"]) for g in b["groupCoefficients"]] == [
        ("A", "2"),
        ("B", "3"),
    ]
    # Original curve coefficients are t * ratio.
    assert [c["value"]["fraction"] for c in b["coefficients"]] == ["1", "2", "1"]
    assert b["rss"]["fraction"] == "0"
    assert len(b["input_digest"]) == 64

    # Point-level identities, exact cross multiplication.
    for p in b["points"]:
        rn, rd = p["residual"]["numerator"], p["residual"]["denominator"]
        en, ed = p["reconstructed"]["numerator"], p["reconstructed"]["denominator"]
        assert rn * ed == p["observed"] * rd * ed - en * rd
        assert p["residual"]["fraction"] == "0"


def test_group_variables_are_nonnegative_and_optimal_with_noise():
    n = 30
    wl, refs = _data(n=n, k=3)
    y = [
        3 * refs[0][i] + refs[1][i] + 2 * refs[2][i] + (i % 3 - 1)
        for i in range(n)
    ]
    groups = [
        {"id": "one", "members": [
            {"index": 0, "ratio": _ratio(2, 1)},
            {"index": 1, "ratio": _ratio(1, 4)},
        ]},
        {"id": "two", "members": [
            {"index": 2, "ratio": _ratio(3, 5)},
        ]},
    ]
    r = client.post("/api/grouped", json=_body(n=n, observations=y, groups=groups, refs=refs))
    assert r.status_code == 200, r.text
    b = r.json()
    t = [_as_frac(g["value"]) for g in b["groupCoefficients"]]
    assert all(v >= 0 for v in t)

    cols = _group_columns(refs, groups)
    assert _group_kkt_optimal(y, cols, t)

    # RSS of the response equals independently summed squared residuals and
    # uses the original observations/curves.
    rss = sum(_as_frac(p["residual"]) ** 2 for p in b["points"])
    assert rss == _as_frac(b["rss"])
    coefs = [_as_frac(c["value"]) for c in b["coefficients"]]
    assert all(
        _as_frac(p["reconstructed"])
        == sum(F(refs[j][p_idx]) * coefs[j] for j in range(len(refs)))
        for p_idx, p in enumerate(b["points"])
    )


def test_reordered_group_list_cannot_change_curve_coefficients():
    n = 24
    wl, refs = _data(n=n, k=3)
    y = [refs[0][i] + 2 * refs[1][i] + refs[2][i] for i in range(n)]
    groups = [
        {"id": "A", "members": [
            {"index": 1, "ratio": _ratio(1, 1)},
            {"index": 0, "ratio": _ratio(1, 2)},
        ]},
        {"id": "B", "members": [{"index": 2, "ratio": _ratio(1, 3)}]},
    ]
    b1 = client.post(
        "/api/grouped", json=_body(n=n, observations=y, groups=groups, refs=refs)
    ).json()
    swapped = copy.deepcopy(groups)
    swapped.reverse()
    b2 = client.post(
        "/api/grouped", json=_body(n=n, observations=y, groups=swapped, refs=refs)
    ).json()
    # Same digest (canonical form sorts groups/members) and identical
    # per-original-curve coefficients regardless of list order.
    assert b1["input_digest"] == b2["input_digest"]
    c1 = [(c["index"], c["value"]["fraction"]) for c in b1["coefficients"]]
    c2 = [(c["index"], c["value"]["fraction"]) for c in b2["coefficients"]]
    assert c1 == c2 == [(0, "1"), (1, "2"), (2, "1")]
    # Group variables are reported keyed by their id, hence comparable.
    g1 = {g["id"]: g["value"]["fraction"] for g in b1["groupCoefficients"]}
    g2 = {g["id"]: g["value"]["fraction"] for g in b2["groupCoefficients"]}
    assert g1 == g2 == {"A": "2", "B": "3"}
    # Response order is canonical (sorted by id).
    assert [g["id"] for g in b2["groupCoefficients"]] == ["A", "B"]


def test_single_group_with_fractional_ratios():
    n = 24
    wl, refs = _data(n=n)
    # one group; ratios 1/3 and 2/3; choose t = 9 -> x = (3, 6)
    y = [3 * refs[0][i] + 6 * refs[1][i] for i in range(n)]
    groups = [
        {"id": "only", "members": [
            {"index": 0, "ratio": _ratio(1, 3)},
            {"index": 1, "ratio": _ratio(2, 3)},
        ]}
    ]
    b = client.post(
        "/api/grouped", json=_body(n=n, observations=y, groups=groups, refs=refs)
    ).json()
    assert b["groupCoefficients"][0]["value"]["fraction"] == "9"
    assert [c["value"]["fraction"] for c in b["coefficients"]] == ["3", "6"]
    assert b["rss"]["fraction"] == "0"


def test_zero_group_variable_is_exact_zero():
    n = 24
    wl, refs = _data(n=n, k=3)
    groups = [
        {"id": "a", "members": [
            {"index": 0, "ratio": _ratio(1, 1)},
            {"index": 1, "ratio": _ratio(1, 1)},
        ]},
        {"id": "b", "members": [{"index": 2, "ratio": _ratio(1, 1)}]},
    ]
    # Observations lie only on curve 2, so group a must be exactly zero even
    # though the unconstrained face could use its members.
    y = [5 * refs[2][i] for i in range(n)]
    b = client.post(
        "/api/grouped", json=_body(n=n, observations=y, groups=groups, refs=refs)
    ).json()
    values = {g["id"]: g["value"]["fraction"] for g in b["groupCoefficients"]}
    assert values == {"a": "0", "b": "5"}
    coefs = [c["value"]["fraction"] for c in b["coefficients"]]
    assert coefs == ["0", "0", "5"]
    assert b["rss"]["fraction"] == "0"
    t = [_as_frac(g["value"]) for g in b["groupCoefficients"]]
    assert _group_kkt_optimal(y, _group_columns(refs, groups), t)


def test_zero_observations_zero_everything():
    n = 20
    body = _body(n=n)
    b = client.post("/api/grouped", json=body).json()
    assert all(g["value"]["numerator"] == 0 for g in b["groupCoefficients"])
    assert all(c["value"]["numerator"] == 0 for c in b["coefficients"])
    assert b["rss"]["fraction"] == "0"
    assert all(p["reconstructed"]["fraction"] == "0" for p in b["points"])


def test_near_duplicate_but_independent_curves_stay_exact():
    # The grouped path inherits exact arithmetic: an "almost duplicate"
    # member curve must not degenerate or round.
    n = 24
    wl, _ = _data(n=n)
    c0 = [3, 5, 2, 4, 6, 1] * 4
    c1 = c0[:]
    c1[7] += 1
    refs = [c0, c1]
    # ratio c0:c1 = 1:1, y = c0 + 2 c1 -> t = ? use two groups to fit freely
    groups = [
        {"id": "p", "members": [{"index": 0, "ratio": _ratio(1, 1)}]},
        {"id": "q", "members": [{"index": 1, "ratio": _ratio(1, 1)}]},
    ]
    y = [c0[i] + 2 * c1[i] for i in range(n)]
    b = client.post(
        "/api/grouped", json=_body(n=n, observations=y, groups=groups, refs=refs)
    ).json()
    assert [g["value"]["fraction"] for g in b["groupCoefficients"]] == ["1", "2"]
    assert b["rss"]["fraction"] == "0"


def test_digest_changes_when_groups_or_spectra_change():
    body = _body(n=24)
    d1 = client.post("/api/grouped", json=body).json()["input_digest"]
    b2 = copy.deepcopy(body)
    b2["input"]["observations"][0] += 1
    d2 = client.post("/api/grouped", json=b2).json()["input_digest"]
    assert d1 != d2
    b3 = copy.deepcopy(body)
    b3["groups"][0]["members"][0]["ratio"] = _ratio(3, 1)
    d3 = client.post("/api/grouped", json=b3).json()["input_digest"]
    assert d3 != d1
    # 1/1 expressed with different (in-range) parts normalises to the same.
    b4 = copy.deepcopy(body)
    b4["groups"][0]["members"][0]["ratio"] = {"num": "2", "den": "2"}
    d4 = client.post("/api/grouped", json=b4).json()["input_digest"]
    assert d4 == d1
    # Deterministic.
    assert client.post("/api/grouped", json=body).json()["input_digest"] == d1


# ---------------------------------------------------------------------------
# Whole-request rejection
# ---------------------------------------------------------------------------


REJECT_CASES = [
    ("duplicate_member_in_group", lambda b: b["groups"][0]["members"][1].update(index=0),
     "invalid_member"),
    ("omitted_member", lambda b: b["groups"][0]["members"].pop(), "invalid_member"),
    ("index_out_of_range", lambda b: b["groups"][0]["members"][1].update(index=9),
     "invalid_member"),
    ("negative_index", lambda b: b["groups"][0]["members"][1].update(index=-1),
     "invalid_member"),
    ("float_index", lambda b: b["groups"][0]["members"][1].update(index=1.0),
     "invalid_member"),
    ("bool_index", lambda b: b["groups"][0]["members"][1].update(index=True),
     "invalid_member"),
    ("index_in_two_groups",
     lambda b: (
         b["groups"][0]["members"].pop(),
         b["groups"].append({"id": "h", "members": [
             {"index": 0, "ratio": _ratio(1, 1)},
             {"index": 1, "ratio": _ratio(1, 1)},
         ]}),
     ), "invalid_member"),
    ("duplicate_group_id",
     lambda b: b["groups"].append(
         {"id": "g", "members": [{"index": 1, "ratio": _ratio(1, 1)}]}),
     "invalid_group"),
    ("empty_group_id", lambda b: b["groups"][0].update(id="  "), "invalid_group"),
    ("empty_groups_list", lambda b: b.update(groups=[]), "invalid_group"),
    ("groups_wrong_type", lambda b: b.update(groups={}), "invalid_group"),
    ("extra_group_key", lambda b: b["groups"][0].update(extra=1), "invalid_group"),
    ("extra_member_key", lambda b: b["groups"][0]["members"][0].update(who=1),
     "invalid_member"),
    ("ratio_zero_num", lambda b: b["groups"][0]["members"][0]["ratio"].update(num="0"),
     "invalid_ratio"),
    ("ratio_zero_den", lambda b: b["groups"][0]["members"][0]["ratio"].update(den="0"),
     "invalid_ratio"),
    ("ratio_negative", lambda b: b["groups"][0]["members"][0]["ratio"].update(den=-2),
     "invalid_ratio"),
    ("ratio_float", lambda b: b["groups"][0]["members"][0]["ratio"].update(num=0.5),
     "invalid_ratio"),
    ("ratio_bool", lambda b: b["groups"][0]["members"][0]["ratio"].update(num=True),
     "invalid_ratio"),
    ("ratio_too_large",
     lambda b: b["groups"][0]["members"][0]["ratio"].update(num=1_000_001),
     "invalid_ratio"),
    ("ratio_malformed_string",
     lambda b: b["groups"][0]["members"][0]["ratio"].update(num="1/2"),
     "invalid_ratio"),
    ("ratio_missing_key",
     lambda b: b["groups"][0]["members"][0]["ratio"].pop("den"), "invalid_ratio"),
    ("missing_groups", lambda b: b.pop("groups"), "invalid_grouped_request"),
    ("missing_input", lambda b: b.pop("input"), "invalid_grouped_request"),
    ("dependent_spectra",
     lambda b: b["input"]["references"].__setitem__(
         1, [2 * v for v in b["input"]["references"][0]]),
     "linearly_dependent"),
    ("negative_reference", lambda b: b["input"]["references"][0].__setitem__(3, -1),
     "invalid_reference"),
    ("too_few_points",
     lambda b: (
         b["input"]["wavelengths"].__delitem__(slice(19, None)),
         b["input"]["observations"].__delitem__(slice(19, None)),
         b["input"]["references"][0].__delitem__(slice(19, None)),
         b["input"]["references"][1].__delitem__(slice(19, None)),
     ), "invalid_dimension"),
]


@pytest.mark.parametrize("name,mutate,code", REJECT_CASES)
def test_illegal_requests_rejected_entirely(name, mutate, code):
    body = _body(n=24)
    mutate(body)
    r = client.post("/api/grouped", json=body)
    assert r.status_code == 422, (name, r.status_code, r.text)
    err = r.json()["error"]
    assert err["code"] == code, (name, err)
    # No partial result ever.
    assert "coefficients" not in r.json()
    assert "points" not in r.json()


def test_body_must_be_an_object():
    r = client.post("/api/grouped", json=["not", "an", "object"])
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "invalid_schema"


def test_schema_level_spectrum_error_is_unified_envelope():
    body = _body(n=24)
    body["input"]["observations"][0] = 1.5
    r = client.post("/api/grouped", json=body)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "invalid_schema"


def test_malformed_json_body_rejected():
    r = client.post(
        "/api/grouped",
        content=b"{not json",
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "invalid_schema"


# ---------------------------------------------------------------------------
# Download binding
# ---------------------------------------------------------------------------


def test_grouped_download_csv_matches_rendered_response():
    body = _body(n=24)
    solved = client.post("/api/grouped", json=body).json()
    r = client.post("/api/grouped/download", json=body)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    text = r.text
    assert ("# input_digest," + solved["input_digest"]) in text
    assert solved["rss"]["fraction"] in text
    for g in solved["groupCoefficients"]:
        assert f"{g['id']}={g['value']['fraction']}" in text
    for c in solved["coefficients"]:
        assert f"{c['index']}={c['value']['fraction']}" in text
    rows = [ln for ln in text.splitlines() if not ln.startswith("#")]
    assert len(rows) == 25  # header + 24 points
    first = solved["points"][0]
    assert first["reconstructed"]["fraction"] in text
    assert "grouped-spectrum-" in r.headers["content-disposition"]


def test_grouped_download_recomputes_for_the_same_complete_request():
    body = _body(n=24)
    solved = client.post("/api/grouped", json=body).json()
    changed = copy.deepcopy(body)
    changed["groups"][0]["members"][0]["ratio"] = _ratio(7, 1)
    r = client.post("/api/grouped/download", json=changed)
    assert r.status_code == 200
    # The download of a different request must not carry the old digest.
    assert solved["input_digest"] not in r.text


@pytest.mark.parametrize("name,mutate,code", REJECT_CASES)
def test_download_rejects_illegal_requests(name, mutate, code):
    body = _body(n=24)
    mutate(body)
    r = client.post("/api/grouped/download", json=body)
    assert r.status_code == 422, (name, r.status_code, r.text)
    assert r.headers.get("content-type", "").startswith("application/json")
    assert r.json()["error"]["code"] == code


def test_download_rejects_non_object_body():
    r = client.post("/api/grouped/download", json="nope")
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "invalid_schema"


def test_original_ungrouped_solver_still_served():
    n = 24
    wl, refs = _data(n=n)
    y = [2 * refs[0][i] + refs[1][i] for i in range(n)]
    r = client.post(
        "/api/solve",
        json={"wavelengths": wl, "observations": y, "references": refs},
    )
    assert r.status_code == 200
    b = r.json()
    assert [c["value"]["fraction"] for c in b["coefficients"]] == ["2", "1"]
    assert b["rss"]["fraction"] == "0"


def test_groups_page_served():
    r = client.get("/groups")
    assert r.status_code == 200
    assert "固定组比例" in r.text
    assert "/api/grouped/download" in r.text
