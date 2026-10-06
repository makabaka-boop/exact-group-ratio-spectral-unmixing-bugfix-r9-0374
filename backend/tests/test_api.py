"""API-level tests: validation, rejection semantics, response coherence,
digest binding, and the chart/download sharing one response."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.main import app  # noqa: E402

client = TestClient(app)


def _payload(n=24, k=2, *, dep=False, neg=False):
    wl = list(range(400, 400 + n))
    c0 = [1, 2, 3, 1, 2, 3] * (n // 6) + [1] * (n % 6)
    c1 = [0, 0, 0, 1, 1, 1] * (n // 6) + [1] * (n % 6)
    refs = [c0[:], c1[:]]
    if k >= 3:
        refs.append([(i % 5) for i in range(n)])
    if k >= 4:
        refs.append([1 + (i % 2) for i in range(n)])
    if dep:
        refs[1] = [2 * v for v in refs[0]]
    if neg:
        refs[0][3] = -1
    y = [2 * c0[i] + c1[i] for i in range(n)]
    return {
        "wavelengths": wl,
        "observations": y,
        "references": refs,
    }


def test_health():
    assert client.get("/api/health").json() == {"status": "ok"}


def test_solve_basic_response_shapes_and_identities():
    r = client.post("/api/solve", json=_payload())
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["coefficients"]) == 2
    assert len(body["points"]) == 24
    for c in body["coefficients"]:
        rat = c["value"]
        assert isinstance(rat["numerator"], int)
        assert rat["denominator"] >= 1
        assert "/" in rat["fraction"] or rat["denominator"] == 1
    for p in body["points"]:
        # residual == observed - reconstructed, checked with integer cross
        # multiplication against the exact fraction payload.
        rn, rd = p["residual"]["numerator"], p["residual"]["denominator"]
        en, ed = (
            p["reconstructed"]["numerator"],
            p["reconstructed"]["denominator"],
        )
        assert rn * ed == (p["observed"] * rd * ed - en * rd)
    # Coefficients of this constructed input.
    assert body["coefficients"][0]["value"]["fraction"] == "2"
    assert body["coefficients"][1]["value"]["fraction"] == "1"
    assert body["rss"]["fraction"] == "0"
    assert len(body["input_digest"]) == 64


def test_reject_too_few_points():
    p = _payload(n=19)
    r = client.post("/api/solve", json=p)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "invalid_dimension"


def test_reject_too_many_curves():
    p = _payload(k=4)
    p["references"].append([1] * 24)
    p["references"].append([2] * 24)
    p["references"].append([3] * 24)  # 7 curves
    r = client.post("/api/solve", json=p)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "invalid_dimension"


def test_reject_length_mismatch():
    p = _payload()
    p["wavelengths"].append(999)
    r = client.post("/api/solve", json=p)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "invalid_dimension"


def test_reject_non_increasing_wavelengths():
    p = _payload()
    p["wavelengths"][5] = p["wavelengths"][3]
    r = client.post("/api/solve", json=p)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "invalid_wavelengths"


def test_reject_linear_dependence_entire_bundle():
    p = _payload(k=3, dep=True)
    r = client.post("/api/solve", json=p)
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "linearly_dependent"
    # No partial result is returned.
    assert "coefficients" not in r.json()


def test_reject_negative_reference():
    p = _payload(neg=True)
    r = client.post("/api/solve", json=p)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "invalid_reference"


def test_reject_float_and_bool_inputs():
    p = _payload()
    p["observations"][0] = 1.5
    r = client.post("/api/solve", json=p)
    assert r.status_code == 422
    p = _payload()
    p["references"][0][0] = True
    r = client.post("/api/solve", json=p)
    assert r.status_code == 422


def test_digest_changes_when_input_changes():
    import json as _json

    p1 = _payload()
    d1 = client.post("/api/solve", json=p1).json()["input_digest"]
    p2 = _json.loads(_json.dumps(p1))
    p2["observations"][0] += 1
    d2 = client.post("/api/solve", json=p2).json()["input_digest"]
    assert d1 != d2
    # Deterministic for identical content.
    assert client.post("/api/solve", json=p1).json()["input_digest"] == d1


def test_download_csv_is_same_response_binding():
    p = _payload()
    solved = client.post("/api/solve", json=p).json()
    r = client.post("/api/download", json=p)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    text = r.text
    assert solved["input_digest"] in text
    assert ("rss," + solved["rss"]["fraction"]) in text
    # One CSV row per point, exact reconstructed fractions present.
    data_rows = [ln for ln in text.splitlines() if not ln.startswith("#")]
    assert len(data_rows) == 25  # header + 24 points
    first = solved["points"][0]
    assert first["reconstructed"]["fraction"] in text


def test_download_rejects_dependent_input():
    r = client.post("/api/download", json=_payload(dep=True))
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "linearly_dependent"


def test_schema_errors_use_unified_rejection_envelope():
    # missing field
    r = client.post("/api/solve", json={"wavelengths": [1, 2], "observations": [1, 2]})
    assert r.status_code == 422
    body = r.json()
    assert body["error"]["code"] == "invalid_schema"
    assert "details" in body["error"]
    # malformed JSON body
    r = client.post(
        "/api/solve",
        content=b"{not json",
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "invalid_schema"
    # non-integer typed observation
    r = client.post(
        "/api/solve",
        json={
            "wavelengths": list(range(20)),
            "observations": [1.5] * 20,
            "references": [[1] * 20, [2] * 20],
        },
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "invalid_schema"


@pytest.mark.parametrize("n", [20, 80])
def test_dimension_boundaries(n):
    r = client.post("/api/solve", json=_payload(n=n))
    assert r.status_code == 200
    assert len(r.json()["points"]) == n
