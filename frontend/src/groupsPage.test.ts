import { describe, expect, it } from "vitest";
// The /groups review page is served by the backend as a static ES module;
// these tests exercise that exact file (no duplicated logic).
// @ts-ignore -- plain JS module living next to the backend page
import { SAMPLE_REQUEST, buildGroupedCsv, chartSeries, isResultStale, isResultUsable } from "../../backend/app/groups_page.js";

function rat(n: number, d = 1) {
  return {
    numerator: n,
    denominator: d,
    fraction: d === 1 ? String(n) : `${n}/${d}`,
    decimal: String(n / d),
  };
}

function fakeResult() {
  return {
    groupCoefficients: [
      { id: "blend", value: rat(5) },
      { id: 'we,"ird"', value: rat(0) },
    ],
    coefficients: [
      { index: 0, value: rat(5) },
      { index: 1, value: rat(10) },
      { index: 2, value: rat(0) },
    ],
    points: [
      {
        wavelength: 400,
        observed: 7,
        reconstructed: rat(15, 2),
        residual: rat(-1, 2),
      },
      {
        wavelength: 401,
        observed: 3,
        reconstructed: rat(3),
        residual: rat(0),
      },
    ],
    rss: rat(1, 4),
    input_digest:
      "abc123def4567890abc123def4567890abc123def4567890abc123def4567890",
  };
}

describe("freshness rule (page state model)", () => {
  it("is unusable but not stale before any solve", () => {
    const state = { result: null, generation: 0, solvedGeneration: -1 };
    expect(isResultUsable(state)).toBe(false);
    expect(isResultStale(state)).toBe(false);
  });

  it("is usable right after a solve at the current generation", () => {
    const state = { result: fakeResult(), generation: 3, solvedGeneration: 3 };
    expect(isResultUsable(state)).toBe(true);
    expect(isResultStale(state)).toBe(false);
  });

  it("any edit (generation bump) immediately stales the shown result", () => {
    const state = { result: fakeResult(), generation: 4, solvedGeneration: 3 };
    expect(isResultStale(state)).toBe(true);
    expect(isResultUsable(state)).toBe(false);
  });

  it("editing then editing back does NOT revive the old result", () => {
    // Solve at generation 3, edit away (4), revert the text (5): the text
    // may be identical again, but the generation moved, so the old
    // response stays stale until a fresh solve.
    const state = { result: fakeResult(), generation: 5, solvedGeneration: 3 };
    expect(isResultUsable(state)).toBe(false);
    state.solvedGeneration = 5; // re-solve at the current generation
    expect(isResultUsable(state)).toBe(true);
  });
});

describe("buildGroupedCsv", () => {
  it("embeds the digest binding the file to one complete request", () => {
    const csv = buildGroupedCsv(fakeResult());
    expect(csv.startsWith("# input_digest,abc123def4567890")).toBe(true);
  });

  it("quotes group ids and doubles embedded quotes", () => {
    const csv = buildGroupedCsv(fakeResult());
    expect(csv).toContain('# group_coefficients,"blend"=5;"we,""ird"""=0');
  });

  it("lists per-curve coefficients and the exact rss", () => {
    const csv = buildGroupedCsv(fakeResult());
    expect(csv).toContain("# coefficients,0=5;1=10;2=0");
    expect(csv).toContain("# rss,1/4");
  });

  it("emits one exact-fraction row per point, matching the server format", () => {
    const csv = buildGroupedCsv(fakeResult());
    const lines = csv.split("\n").filter((l: string) => l.length > 0);
    expect(lines.length).toBe(4 + 1 + 2); // 4 comments + header + 2 points
    expect(lines[4]).toBe(
      "wavelength,observed,reconstructed_num,reconstructed_den," +
        "reconstructed_fraction,residual_num,residual_den,residual_fraction",
    );
    expect(lines[5]).toBe("400,7,15,2,15/2,-1,2,-1/2");
    expect(lines[6]).toBe("401,3,3,1,3,0,1,0");
    expect(csv.endsWith("\n")).toBe(true);
  });

  it("changes when the response object changes (same-object binding)", () => {
    const a = fakeResult();
    const b = fakeResult();
    b.rss = rat(9);
    expect(buildGroupedCsv(a)).not.toBe(buildGroupedCsv(b));
    expect(buildGroupedCsv(b)).toContain("# rss,9");
  });
});

describe("chartSeries", () => {
  it("converts exact rationals to display numbers and tracks the max", () => {
    const { series, maximum } = chartSeries(fakeResult().points);
    expect(series.observed).toEqual([7, 3]);
    expect(series.reconstructed).toEqual([7.5, 3]);
    expect(series.residual).toEqual([-0.5, 0]);
    expect(maximum).toBe(7.5);
  });

  it("keeps a minimum scale of 1 so a zero fit does not divide by zero", () => {
    const zero = fakeResult();
    zero.points = zero.points.map((p) => ({
      ...p,
      observed: 0,
      reconstructed: rat(0),
      residual: rat(0),
    }));
    const { maximum } = chartSeries(zero.points);
    expect(maximum).toBe(1);
  });
});

describe("SAMPLE_REQUEST", () => {
  it("is a complete grouped request the backend accepts", () => {
    expect(SAMPLE_REQUEST.input.wavelengths.length).toBe(20);
    expect(SAMPLE_REQUEST.input.observations.length).toBe(20);
    expect(SAMPLE_REQUEST.input.references.length).toBe(2);
    expect(SAMPLE_REQUEST.groups.length).toBe(1);
    const memberIndexes = SAMPLE_REQUEST.groups.flatMap((g: any) =>
      g.members.map((m: any) => m.index),
    );
    expect(memberIndexes.sort()).toEqual([0, 1]);
    for (const g of SAMPLE_REQUEST.groups) {
      for (const m of g.members) {
        expect(Number(m.ratio.num)).toBeGreaterThan(0);
        expect(Number(m.ratio.den)).toBeGreaterThan(0);
      }
    }
  });
});
