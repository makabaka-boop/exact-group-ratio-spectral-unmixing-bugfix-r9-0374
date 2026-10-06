import type { SolveResponse } from "./types";

/** Build the downloadable CSV *from the exact response object the chart is
 *  rendered from*.  It embeds the response's ``input_digest`` so the file is
 *  cryptographically bound to one particular input/response pair. */
export function buildCsv(resp: SolveResponse): string {
  const lines: string[] = [];
  lines.push(`# input_digest,${resp.input_digest}`);
  lines.push(
    "# coefficients," +
      resp.coefficients.map((c) => `${c.index}=${c.value.fraction}`).join(";"),
  );
  lines.push(`# rss,${resp.rss.fraction}`);
  lines.push(
    "wavelength,observed,reconstructed_num,reconstructed_den,reconstructed_fraction,residual_num,residual_den,residual_fraction",
  );
  for (const p of resp.points) {
    lines.push(
      [
        p.wavelength,
        p.observed,
        p.reconstructed.numerator,
        p.reconstructed.denominator,
        p.reconstructed.fraction,
        p.residual.numerator,
        p.residual.denominator,
        p.residual.fraction,
      ].join(","),
    );
  }
  return lines.join("\n") + "\n";
}
