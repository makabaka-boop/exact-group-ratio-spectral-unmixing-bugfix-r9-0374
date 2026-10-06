import { describe, expect, it } from "vitest";
import { buildCsv } from "./csv";
import type { SolveResponse } from "./types";

function rat(n: number, d = 1) {
  return {
    numerator: n,
    denominator: d,
    fraction: d === 1 ? String(n) : `${n}/${d}`,
    decimal: String(n / d),
  };
}

function fakeResponse(): SolveResponse {
  return {
    coefficients: [
      { index: 0, value: rat(2) },
      { index: 1, value: rat(0) },
      { index: 2, value: rat(1, 3) },
    ],
    points: [
      {
        wavelength: 400,
        observed: 10,
        reconstructed: rat(20, 3),
        residual: rat(10, 3),
      },
      {
        wavelength: 405,
        observed: 7,
        reconstructed: rat(7),
        residual: rat(0),
      },
    ],
    rss: rat(100, 9),
    active_set: [0, 2],
    subsets_scanned: 8,
    feasible_candidates: 5,
    input_digest:
      "abc123def4567890abc123def4567890abc123def4567890abc123def4567890",
  };
}

describe("buildCsv", () => {
  it("embeds the response input digest binding the file to one input", () => {
    const csv = buildCsv(fakeResponse());
    expect(csv).toContain("# input_digest,abc123def4567890");
  });

  it("includes reduced coefficients and the exact rss fraction", () => {
    const csv = buildCsv(fakeResponse());
    expect(csv).toContain("# coefficients,0=2;1=0;2=1/3");
    expect(csv).toContain("# rss,100/9");
  });

  it("emits one data row per point carrying exact fraction columns", () => {
    const csv = buildCsv(fakeResponse());
    const lines = csv.split("\n").filter((l) => l.length > 0);
    // 3 comment lines + 1 header + 2 points
    expect(lines.length).toBe(6);
    expect(lines[4]).toContain("400,10,20,3,20/3,10,3,10/3");
    expect(lines[5]).toContain("405,7,7,1,7,0,1,0");
  });

  it(
    "comes from the same response object identity (no mutation between " +
      "chart and download): changing the response changes the CSV equally",
    () => {
      const a = fakeResponse();
      const b = fakeResponse();
      b.rss = rat(1);
      expect(buildCsv(a)).not.toBe(buildCsv(b));
      expect(buildCsv(b)).toContain("# rss,1");
    },
  );
});
