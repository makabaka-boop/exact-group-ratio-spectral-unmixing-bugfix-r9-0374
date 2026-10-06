import { describe, expect, it } from "vitest";
import { parseIntList, requestSignature, toText } from "./parse";

describe("parseIntList", () => {
  it("parses comma/space/semicolon separated integers", () => {
    expect(parseIntList("1, 2 3;4")).toEqual([1, 2, 3, 4]);
  });

  it("parses an empty string to an empty list", () => {
    expect(parseIntList("")).toEqual([]);
    expect(parseIntList("   ")).toEqual([]);
  });

  it("rejects floats", () => {
    expect(parseIntList("1.5")).toBeNull();
    expect(parseIntList("1.0")).toBeNull();
  });

  it("rejects booleans and words", () => {
    expect(parseIntList("true")).toBeNull();
    expect(parseIntList("abc")).toBeNull();
  });

  it("accepts negatives by default but rejects them when nonNegative", () => {
    expect(parseIntList("-1, 2")).toEqual([-1, 2]);
    expect(parseIntList("-1, 2", { nonNegative: true })).toBeNull();
    expect(parseIntList("0, 2", { nonNegative: true })).toEqual([0, 2]);
  });

  it("rejects unsafe integers", () => {
    expect(parseIntList("9007199254740993")).toBeNull();
    expect(parseIntList("9007199254740991")).toEqual([Number.MAX_SAFE_INTEGER]);
  });
});

describe("toText", () => {
  it("round-trips through the parser", () => {
    const vals = [10, 20, -3, 0];
    expect(parseIntList(toText(vals))).toEqual(vals);
  });
});

describe("requestSignature", () => {
  it("is identical for equal content regardless of key insertion order", () => {
    const a = {
      wavelengths: [1, 2],
      observations: [3, 4],
      references: [[5, 6]],
    };
    const b = {
      references: [[5, 6]],
      observations: [3, 4],
      wavelengths: [1, 2],
    };
    expect(requestSignature(a)).toBe(requestSignature(b));
  });

  it("changes on any edit so a stale response can be detected", () => {
    const base = {
      wavelengths: [1, 2, 3],
      observations: [10, 20, 30],
      references: [[1, 1, 1]],
    };
    const edited = { ...base, observations: [10, 21, 30] };
    expect(requestSignature(edited)).not.toBe(requestSignature(base));
    const editedRef = {
      ...base,
      references: [[1, 1, 2]],
    };
    expect(requestSignature(editedRef)).not.toBe(requestSignature(base));
  });
});
