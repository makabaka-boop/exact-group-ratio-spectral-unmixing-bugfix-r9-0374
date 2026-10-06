/** Freshness rule that stops an old response from being presented as the
 *  conclusion for a newly edited input.
 *
 *  A result is usable for *the current editor content* only when a response
 *  exists AND the canonical signature of the request that produced it equals
 *  the signature of the request currently in the editor.  Any edit (even a
 *  single observation) changes the signature, immediately staling the
 *  result; a fresh solve is then required before the chart can back a
 *  download or a conclusion.
 */
export function isResultStale(args: {
  hasResponse: boolean;
  solvedSignature: string | null;
  currentSignature: string | null;
}): boolean {
  if (!args.hasResponse) return false;
  if (args.solvedSignature === null) return true;
  return args.solvedSignature !== args.currentSignature;
}

/** Whether the response may be trusted as the result for the current input. */
export function canUseResult(args: {
  hasResponse: boolean;
  solvedSignature: string | null;
  currentSignature: string | null;
}): boolean {
  return (
    args.hasResponse &&
    !isResultStale(args) &&
    args.solvedSignature !== null &&
    args.solvedSignature === args.currentSignature
  );
}
