import { describe, expect, it } from "vitest";
import { canUseResult, isResultStale } from "./freshness";

describe("isResultStale", () => {
  it("is neutral when there is no response yet", () => {
    expect(
      isResultStale({
        hasResponse: false,
        solvedSignature: null,
        currentSignature: "a",
      }),
    ).toBe(false);
  });

  it("is fresh right after a successful solve whose signature matches", () => {
    expect(
      isResultStale({
        hasResponse: true,
        solvedSignature: "sig-1",
        currentSignature: "sig-1",
      }),
    ).toBe(false);
  });

  it("becomes stale as soon as the editor content changes", () => {
    expect(
      isResultStale({
        hasResponse: true,
        solvedSignature: "sig-1",
        currentSignature: "sig-2",
      }),
    ).toBe(true);
  });

  it("is stale when the current editor content is invalid (no signature)", () => {
    expect(
      isResultStale({
        hasResponse: true,
        solvedSignature: "sig-1",
        currentSignature: null,
      }),
    ).toBe(true);
  });

  it("is stale if somehow a response exists without a recorded signature", () => {
    expect(
      isResultStale({
        hasResponse: true,
        solvedSignature: null,
        currentSignature: "sig-1",
      }),
    ).toBe(true);
  });
});

describe("canUseResult", () => {
  it("allows use only for a matching fresh response", () => {
    expect(
      canUseResult({
        hasResponse: true,
        solvedSignature: "sig-1",
        currentSignature: "sig-1",
      }),
    ).toBe(true);
    expect(
      canUseResult({
        hasResponse: true,
        solvedSignature: "sig-1",
        currentSignature: "sig-2",
      }),
    ).toBe(false);
    expect(
      canUseResult({
        hasResponse: false,
        solvedSignature: null,
        currentSignature: "sig-1",
      }),
    ).toBe(false);
  });

  it("models the requirement: editing then re-saving renews usability", () => {
    const args = {
      hasResponse: true,
      solvedSignature: "sig-1",
      currentSignature: "sig-2",
    };
    expect(canUseResult(args)).toBe(false);
    // user solves again for the edited input:
    expect(canUseResult({ ...args, solvedSignature: "sig-2" })).toBe(true);
  });
});
