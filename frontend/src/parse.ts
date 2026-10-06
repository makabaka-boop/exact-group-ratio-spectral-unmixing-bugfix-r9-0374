/** Strict integer-list parsing used by the editor.
 *
 * Values must be actual integers (no 1.5, no "true"); references must be
 * non-negative.  Returns null when the text is not parseable so the editor
 * can surface an error instead of silently coercing.
 */
export function parseIntList(
  text: string,
  opts: { nonNegative?: boolean } = {},
): number[] | null {
  const tokens = text.split(/[\s,;]+/).filter((t) => t.length > 0);
  const out: number[] = [];
  for (const tok of tokens) {
    if (!/^[+-]?\d+$/.test(tok)) return null;
    const v = Number(tok);
    if (!Number.isSafeInteger(v)) return null;
    if (opts.nonNegative && v < 0) return null;
    out.push(v);
  }
  return out;
}

export function toText(values: number[]): string {
  return values.join(", ");
}

/** Stable signature of the exact request a result belongs to.
 *
 *  Canonical (sorted-key, compact) JSON, matching the encoding the backend
 *  hashes for ``input_digest``.  The client keeps this signature around to
 *  detect edits: whenever the editor content differs from
 *  ``solvedSignature`` the displayed result is treated as stale and may not
 *  back any new conclusion or download.
 */
export function requestSignature(req: {
  wavelengths: number[];
  observations: number[];
  references: number[][];
}): string {
  return canonicalJson({
    wavelengths: req.wavelengths,
    observations: req.observations,
    references: req.references,
  });
}

/** Deterministic JSON: object keys sorted, no insignificant whitespace. */
function canonicalJson(value: unknown): string {
  if (Array.isArray(value)) {
    return "[" + value.map(canonicalJson).join(",") + "]";
  }
  if (value !== null && typeof value === "object") {
    const keys = Object.keys(value as Record<string, unknown>).sort();
    return (
      "{" +
      keys
        .map(
          (k) =>
            JSON.stringify(k) +
            ":" +
            canonicalJson((value as Record<string, unknown>)[k]),
        )
        .join(",") +
      "}"
    );
  }
  return JSON.stringify(value);
}
