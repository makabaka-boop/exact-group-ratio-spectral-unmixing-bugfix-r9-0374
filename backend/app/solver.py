"""Exact non-negative least squares for small integer spectral problems.

No floating point is used anywhere: every operation runs on
:class:`fractions.Fraction`.  For ``k`` non-negative unknowns (2 <= k <= 6)
we enumerate every possible *support* (set of non-zero coefficients) and,
for each one, solve the unrestricted rational normal equations on that
support.  Supports whose solution contains a negative entry are infeasible.
The candidate with the smallest exact squared residual is the answer.

This exhaustive enumeration is exact on purpose: the NNLS optimum is the
unconstrained least-squares solution on its own support, so scanning every
support is a complete search.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from itertools import combinations

ZERO = Fraction(0)


class DomainError(ValueError):
    """A domain-level validation failure (bad dimensions, dependence, ...)."""


@dataclass(frozen=True)
class SolveResult:
    # Coefficients in the order of the incoming reference curves.
    coefficients: list[Fraction]
    # Indices of strictly non-zero coefficients.
    active: list[int]
    reconstructed: list[Fraction]
    residuals: list[Fraction]
    rss: Fraction
    # Diagnostics about the exhaustive search.
    subsets_scanned: int
    feasible_candidates: int


def rational_rank(columns: list[list[int]]) -> int:
    """Rank of an integer matrix given as a list of column vectors.

    Gaussian-Jordan elimination over ``Fraction``, pivoting on rows.
    """
    if not columns or not columns[0]:
        return 0
    n = len(columns[0])
    # Work on rows of the matrix whose columns are the reference curves.
    rows: list[list[Fraction]] = [
        [Fraction(columns[c][r]) for c in range(len(columns))] for r in range(n)
    ]
    pivot_row = 0
    rank = 0
    for col in range(len(columns)):
        pivot = next((r for r in range(pivot_row, n) if rows[r][col] != 0), None)
        if pivot is None:
            continue
        rows[pivot_row], rows[pivot] = rows[pivot], rows[pivot_row]
        piv = rows[pivot_row][col]
        rows[pivot_row] = [v / piv for v in rows[pivot_row]]
        for r in range(n):
            if r != pivot_row and rows[r][col] != 0:
                factor = rows[r][col]
                rows[r] = [v - factor * p for v, p in zip(rows[r], rows[pivot_row])]
        pivot_row += 1
        rank += 1
        if pivot_row == n:
            break
    return rank


def _solve_linear(a: list[list[Fraction]], b: list[Fraction]) -> list[Fraction]:
    """Solve ``a x = b`` by Gauss-Jordan elimination.

    ``a`` is assumed square and non-singular (it is a Gram matrix of
    linearly independent columns restricted to the chosen support).
    """
    m = len(a)
    aug = [row[:] + [b[i]] for i, row in enumerate(a)]
    for col in range(m):
        pivot = next((r for r in range(col, m) if aug[r][col] != 0), None)
        if pivot is None:  # pragma: no cover - callers guarantee full rank
            raise DomainError("singular normal equations")
        aug[col], aug[pivot] = aug[pivot], aug[col]
        piv = aug[col][col]
        aug[col] = [v / piv for v in aug[col]]
        for r in range(m):
            if r != col and aug[r][col] != 0:
                factor = aug[r][col]
                aug[r] = [v - factor * p for v, p in zip(aug[r], aug[col])]
    return [aug[i][m] for i in range(m)]


def solve_nonnegative_least_squares(
    observations: list[int], references: list[list[int]]
) -> SolveResult:
    """Return exact non-negative rational coefficients.

    Minimises ``sum_i (y_i - sum_j A_ij x_j)^2`` subject to ``x_j >= 0``,
    by exhaustive support enumeration.
    """
    n = len(observations)
    k = len(references)

    y = [Fraction(v) for v in observations]
    a = [[Fraction(references[c][r]) for c in range(k)] for r in range(n)]

    # Column norms and cross products: the Gram matrix A^T A.
    gram: list[list[Fraction]] = [[ZERO] * k for _ in range(k)]
    aty: list[Fraction] = [ZERO] * k
    for r in range(n):
        for c in range(k):
            aty[c] += a[r][c] * y[r]
            for d in range(k):
                gram[c][d] += a[r][c] * a[r][d]

    # Seed with the empty support: x = 0, residual y.  This is always a
    # feasible candidate and wins when (for example) every least-squares
    # face solution is non-positive or y is orthogonal to all columns.
    best_x: list[Fraction] = [ZERO] * k
    best_active: list[int] = []
    best_rss: Fraction = sum((v * v for v in y), ZERO)
    subsets_scanned = 1  # the empty support
    feasible = 1

    for size in range(1, k + 1):
        for support in combinations(range(k), size):
            subsets_scanned += 1
            sub_gram = [[gram[c][d] for d in support] for c in support]
            sub_aty = [aty[c] for c in support]
            x_sub = _solve_linear(sub_gram, sub_aty)
            # The support means exactly these coefficients are non-zero.
            if any(v <= 0 for v in x_sub):
                continue
            feasible += 1
            # Reconstruct residual and exact RSS without materialising A x
            # beyond what Fraction handles (n <= 80, k <= 6).
            residual = [
                y[r] - sum(a[r][c] * x_sub[t] for t, c in enumerate(support))
                for r in range(n)
            ]
            rss = sum((e * e for e in residual), ZERO)
            candidate = [ZERO] * k
            for t, c in enumerate(support):
                candidate[c] = x_sub[t]
            if rss < best_rss:
                best_rss, best_x, best_active = rss, candidate, list(support)
            elif rss == best_rss:
                # Deterministic tie break: fewer non-zeros, then lexicographic.
                if (len(support), tuple(candidate)) < (
                    len(best_active),
                    tuple(best_x),
                ):
                    best_x, best_active = candidate, list(support)

    reconstructed = [sum(a[r][c] * best_x[c] for c in range(k)) for r in range(n)]
    residuals = [y[r] - reconstructed[r] for r in range(n)]
    return SolveResult(
        coefficients=best_x,
        active=best_active,
        reconstructed=reconstructed,
        residuals=residuals,
        rss=best_rss,
        subsets_scanned=subsets_scanned,
        feasible_candidates=feasible,
    )
