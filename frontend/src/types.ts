export interface Rational {
  numerator: number;
  denominator: number;
  fraction: string;
  decimal: string;
}

export interface SolveRequest {
  wavelengths: number[];
  observations: number[];
  references: number[][];
}

export interface Point {
  wavelength: number;
  observed: number;
  reconstructed: Rational;
  residual: Rational;
}

export interface Coefficient {
  index: number;
  value: Rational;
}

export interface SolveResponse {
  coefficients: Coefficient[];
  points: Point[];
  rss: Rational;
  active_set: number[];
  subsets_scanned: number;
  feasible_candidates: number;
  input_digest: string;
}

export interface ApiError {
  error: { code: string; message: string; details?: unknown };
}
