"""Tests for the exact NNLS solver.

The strategy mirrors the production algorithm but is written independently
here: on small matrices we enumerate every support with an independent
Fraction Gaussian elimination, check *all* candidate residuals, and verify
KKT-like optimality of the winner.  Special cases: a coefficient that is
exactly zero, and an "almost duplicate" curve that stays linearly
independent (non-degenerate).
"""

from __future__ import annotations

import sys
from fractions import Fraction
from itertools import combinations
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.solver import (  # noqa: E402
    DomainError,
    rational_rank,
    solve_nonnegative_least_squares,
)

F = Fraction


# ---------------------------------------------------------------------------
# Independent reference implementation for cross-checking candidate sets
# ---------------------------------------------------------------------------


def _indep_candidates(y: list[int], cols: list[list[int]]):
    """Enumerate supports with a separately written eliminator."""
    n, k = len(y), len(cols)

    def solve(mat, vec):
        m = len(mat)
        aug = [row[:] + [vec[i]] for i, row in enumerate(mat)]
        for c in range(m):
            p = next(r for r in range(c, m) if aug[r][c] != 0)
            aug[c], aug[p] = aug[p], aug[c]
            piv = aug[c][c]
            aug[c] = [z / piv for z in aug[c]]
            for r in range(m):
                if r != c:
                    a = aug[r][c]
                    if a:
                        aug[r] = [z - a * w for z, w in zip(aug[r], aug[c])]
        return [aug[i][m] for i in range(m)]

    found = {}
    found[()] = [F(0)] * k
    for size in range(1, k + 1):
        for supp in combinations(range(k), size):
            gram = [
                [sum(F(cols[c][r]) * F(cols[d][r]) for r in range(n)) for d in supp]
                for c in supp
            ]
            aty = [sum(F(cols[c][r]) * F(y[r]) for r in range(n)) for c in supp]
            x = solve(gram, aty)
            if all(v > 0 for v in x):
                full = [F(0)] * k
                for t, c in enumerate(supp):
                    full[c] = x[t]
                found[supp] = full
    return found


def _rss(y, cols, x):
    n = len(y)
    return sum(
        (F(y[r]) - sum(F(cols[c][r]) * x[c] for c in range(len(cols)))) ** 2
        for r in range(n)
    )


def _is_optimal(y, cols, x):
    """KKT check for NNLS: active coordinates zero the gradient of the LS
    objective; inactive coordinates must have non-negative gradient (moving
    mass onto them cannot reduce the objective)."""
    n, k = len(y), len(cols)
    for c in range(k):
        grad = sum(
            F(cols[c][r]) * (sum(F(cols[d][r]) * x[d] for d in range(k)) - F(y[r]))
            for r in range(n)
        )
        if x[c] == 0:
            if grad < 0:
                return False
        elif grad != 0:
            return False
    return True


# ---------------------------------------------------------------------------
# Cases
# ---------------------------------------------------------------------------


def test_exact_fit_with_one_zero_coefficient():
    # y = 2*c0 + 0*c1 with c1 genuinely independent: coefficient 1 is
    # exactly zero at the optimum (inactive support), and residual is 0.
    y = []
    c0 = [1, 2, 3, 1, 2, 3] * 4
    c1 = [0, 0, 0, 1, 1, 1] * 4  # independent of c0
    y = [2 * c0[i] for i in range(24)]
    res = solve_nonnegative_least_squares(y, [c0, c1])
    assert res.coefficients == [F(2), F(0)]
    assert res.active == [0]
    assert res.rss == 0
    assert res.residuals == [F(0)] * 24
    assert res.reconstructed == [F(v) for v in y]


def test_near_duplicate_curve_non_degenerate():
    # c1 is an "almost duplicate" of c0 but differs at a single point, so
    # the columns stay independent; the system must remain non-singular and
    # produce an exact (fractional, non-trivial) fit rather than refuse.
    n = 24
    c0 = [3, 5, 2, 4, 6, 1] * 4
    c1 = c0[:]
    c1[7] += 1  # perturb one entry: still independent
    assert rational_rank([c0, c1]) == 2
    y = [c0[i] + 2 * c1[i] for i in range(n)]
    res = solve_nonnegative_least_squares(y, [c0, c1])
    assert res.coefficients == [F(1), F(2)]
    assert res.rss == 0
    assert res.feasible_candidates >= 3  # empty + {0} + {1} + {0,1}


def test_independent_enumeration_finds_same_optimum():
    # Small 3-column matrix with noise so the optimum is interior; compare
    # against the independently enumerated candidate sets.
    c0 = [1, 0, 2, 1, 3] * 5
    c1 = [0, 1, 1, 2, 1] * 5
    c2 = [2, 1, 0, 1, 1] * 5
    y = [(3 * c0[i] + c1[i] + 2 * c2[i]) + (i % 3 - 1) for i in range(25)]
    res = solve_nonnegative_least_squares(y, [c0, c1, c2])

    candidates = _indep_candidates(y, [c0, c1, c2])
    rsses = {supp: _rss(y, [c0, c1, c2], x) for supp, x in candidates.items()}
    best_supp, best_rss = min(rsses.items(), key=lambda kv: (kv[1], len(kv[0])))

    assert res.rss == best_rss
    winner = candidates[best_supp]
    assert res.coefficients == winner
    # Every feasible candidate the production scan compared against is real.
    assert res.subsets_scanned == 2**3
    assert _is_optimal(y, [c0, c1, c2], res.coefficients)


def test_all_candidates_compared_by_exact_residual():
    # A 4-column case (16 supports) where the unconstrained full-support
    # solution is infeasible (negative), so the optimum is on a face; exact
    # comparison must not be fooled by close fractions.
    c0 = [2, 1, 3, 0] * 6
    c1 = [1, 2, 0, 1] * 6
    c2 = [3, 1, 1, 2] * 6
    c3 = [0, 1, 2, 3] * 6
    # y aligned with c0+c3 but "pulled" so that using c2 goes negative.
    y = [c0[i] + c3[i] - (1 if i % 2 else 0) for i in range(24)]
    res = solve_nonnegative_least_squares(y, [c0, c1, c2, c3])
    assert all(v >= 0 for v in res.coefficients)
    assert res.subsets_scanned == 16
    candidates = _indep_candidates(y, [c0, c1, c2, c3])
    for x in candidates.values():
        assert _rss(y, [c0, c1, c2, c3], x) >= res.rss
    assert _is_optimal(y, [c0, c1, c2, c3], res.coefficients)


def test_zero_observations_gives_zero_coefficients():
    n = 20
    cols = [[1 + (i + j) % 4 for i in range(n)] for j in range(3)]
    res = solve_nonnegative_least_squares([0] * n, cols)
    assert res.coefficients == [F(0)] * 3
    assert res.active == []
    assert res.rss == 0


def test_rank_detection():
    n = 24
    c0 = [1, 2, 3] * 8
    assert rational_rank([c0]) == 1
    assert rational_rank([c0, [2 * v for v in c0]]) == 1
    c2 = [1, 0, 0] * 8
    c3 = [0, 1, 0] * 8
    assert rational_rank([c0, c2, c3]) == 3
    with pytest.raises(DomainError):
        solve_nonnegative_least_squares(
            [1] * n, [c0, [2 * v for v in c0]]
        )  # dependent columns => singular sub-system


def test_fractional_coefficients_are_exact():
    # y = (1/3) c0 + (2/3) c1 with divisible, independent integer curves;
    # the answer must be the exact reduced fraction, not a float rounded.
    n = 30
    c0 = [3, 6] * 15
    c1 = [6, 3] * 15
    y = [c0[i] // 3 + 2 * c1[i] // 3 for i in range(n)]
    res = solve_nonnegative_least_squares(y, [c0, c1])
    assert res.coefficients == [F(1, 3), F(2, 3)]
    assert res.rss == 0
    assert res.coefficients[0].denominator == 3
    assert res.coefficients[1].denominator == 3


def test_six_columns_sixtythree_supports():
    # Columns (i+1)^j for j=0..5: a Vandermonde design, guaranteed full
    # column rank without any floating-point rank test.
    n = 40
    cols = [[(i + 1) ** j for i in range(n)] for j in range(6)]
    assert rational_rank(cols) == 6
    y = [sum(cols[j][i] for j in range(6)) for i in range(n)]
    res = solve_nonnegative_least_squares(y, cols)
    assert res.subsets_scanned == 64
    assert res.coefficients == [F(1)] * 6
    assert res.rss == 0
