import type { SolveRequest } from "./types";

export interface Sample {
  name: string;
  request: SolveRequest;
}

const n = 40;

function wavelengths(): number[] {
  return Array.from({ length: n }, (_, i) => 400 + i * 5);
}

// Three non-negative, independent reference "shapes".
const gaussian = (center: number, width: number) =>
  wavelengths().map((w) => {
    const d = (w - center) / width;
    return Math.round(100 * Math.exp(-(d * d) / 2));
  });

export const SAMPLES: Sample[] = [
  {
    name: "示例：三曲线混合（含精确零系数）",
    request: (() => {
      const wl = wavelengths();
      const c0 = gaussian(450, 35);
      const c1 = gaussian(520, 30);
      const c2 = gaussian(590, 40);
      // Observation = 3*c0 + 2*c2 + small integer noise; c1 unused.
      const observations = wl.map(
        (_, i) => 3 * c0[i] + 2 * c2[i] + ((i * 7) % 5) - 2,
      );
      return { wavelengths: wl, observations, references: [c0, c1, c2] };
    })(),
  },
  {
    name: "示例：近似但不退化的双峰",
    request: (() => {
      const wl = wavelengths();
      const c0 = gaussian(500, 40);
      const c1 = gaussian(505, 40); // nearly parallel, still independent
      const observations = wl.map((_, i) => 2 * c0[i] + c1[i] + (i % 3) - 1);
      return { wavelengths: wl, observations, references: [c0, c1] };
    })(),
  },
];
