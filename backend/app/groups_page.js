/** Logic for the fixed-ratio group review page (/groups).
 *
 *  The pure functions (freshness rule, CSV builder, chart series) are
 *  exported so they can be unit-tested; boot() wires them to the DOM and
 *  is only invoked by the page itself.
 *
 *  Freshness contract: ``generation`` increments on *every* edit of the
 *  request text, and a solve records the generation it was started at.
 *  The displayed response is usable (chart trustworthy, download
 *  unlocked) only while the editor generation still equals the solved
 *  generation — any edit, including reverting, immediately stales it.
 */

/** A request the backend accepts: one group, ratios 1 and 2. */
export const SAMPLE_REQUEST = {
  input: {
    wavelengths: Array.from({ length: 20 }, (_, i) => i),
    observations: [7, 8, ...Array(18).fill(0)],
    references: [
      [1, 0, ...Array(18).fill(0)],
      [0, 1, ...Array(18).fill(0)],
    ],
  },
  groups: [
    {
      id: "blend",
      members: [
        { index: 0, ratio: { num: "1", den: "1" } },
        { index: 1, ratio: { num: "2", den: "1" } },
      ],
    },
  ],
};

/** True only while the shown response belongs to the current editor text. */
export function isResultUsable(state) {
  return state.result !== null && state.solvedGeneration === state.generation;
}

/** True when a response is on screen but the input has moved on. */
export function isResultStale(state) {
  return state.result !== null && state.solvedGeneration !== state.generation;
}

/** Display-only numeric series for the SVG chart.
 *
 *  Exact rationals stay in the response object; the float conversion here
 *  is used for pixel positions only, never for any reported number.
 */
export function chartSeries(points) {
  const toNumber = (v) =>
    typeof v === "number" ? v : Number(v.numerator) / Number(v.denominator);
  const series = { observed: [], reconstructed: [], residual: [] };
  let maximum = 1;
  for (const point of points) {
    for (const key of Object.keys(series)) {
      const value = toNumber(point[key]);
      series[key].push(value);
      const magnitude = Math.abs(value);
      if (magnitude > maximum) maximum = magnitude;
    }
  }
  return { series, maximum };
}

function csvQuote(id) {
  return '"' + String(id).replaceAll('"', '""') + '"';
}

/** CSV built from the *same response object* the chart renders, so the
 *  download can never diverge from what is on screen.  The format matches
 *  the server's /api/grouped/download output column for column. */
export function buildGroupedCsv(result) {
  const lines = [];
  lines.push(`# input_digest,${result.input_digest}`);
  lines.push(
    "# group_coefficients," +
      result.groupCoefficients
        .map((g) => `${csvQuote(g.id)}=${g.value.fraction}`)
        .join(";"),
  );
  lines.push(
    "# coefficients," +
      result.coefficients.map((c) => `${c.index}=${c.value.fraction}`).join(";"),
  );
  lines.push(`# rss,${result.rss.fraction}`);
  lines.push(
    "wavelength,observed,reconstructed_num,reconstructed_den," +
      "reconstructed_fraction,residual_num,residual_den,residual_fraction",
  );
  for (const p of result.points) {
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

const CHART_COLORS = { observed: "#1565c0", reconstructed: "#2e7d32", residual: "#c62828" };

function renderChart(svg, points) {
  svg.replaceChildren();
  const { series, maximum } = chartSeries(points);
  const width = 640;
  const height = 240;
  const midY = height / 2;
  const first = points[0].wavelength;
  const span = points[points.length - 1].wavelength - first || 1;
  const xOf = (i) => ((points[i].wavelength - first) * (width - 20)) / span + 10;
  const yOf = (v) => midY - (v / maximum) * (midY - 12);
  const axis = document.createElementNS("http://www.w3.org/2000/svg", "line");
  axis.setAttribute("x1", "0");
  axis.setAttribute("x2", String(width));
  axis.setAttribute("y1", String(midY));
  axis.setAttribute("y2", String(midY));
  axis.setAttribute("stroke", "#999");
  axis.setAttribute("stroke-dasharray", "4 3");
  svg.append(axis);
  for (const [name, values] of Object.entries(series)) {
    const path = document.createElementNS("http://www.w3.org/2000/svg", "polyline");
    path.setAttribute(
      "points",
      values.map((v, i) => `${xOf(i)},${yOf(v)}`).join(" "),
    );
    path.setAttribute("fill", "none");
    path.setAttribute("stroke", CHART_COLORS[name]);
    path.setAttribute("stroke-width", name === "residual" ? "1.2" : "1.8");
    path.dataset.series = name;
    svg.append(path);
  }
}

function rationalText(value) {
  return `${value.fraction} (≈ ${value.decimal})`;
}

export function boot(sample) {
  const $ = (id) => document.getElementById(id);
  const state = { result: null, generation: 0, solvedGeneration: -1 };

  $("request").value = JSON.stringify(sample, null, 2);

  function render() {
    const usable = isResultUsable(state);
    const stale = isResultStale(state);
    $("stale").hidden = !stale;
    $("download").disabled = !usable;
    $("content").classList.toggle("stale-content", stale);
    if (!state.result) {
      $("summary").replaceChildren();
      $("result").textContent = "";
      $("chart").replaceChildren();
      return;
    }
    const r = state.result;
    $("summary").replaceChildren(
      ...[
        `输入指纹 ${r.input_digest.slice(0, 16)}…`,
        `总平方残差 RSS ${r.rss.fraction} (≈ ${r.rss.decimal})`,
        "组变量 " +
          r.groupCoefficients
            .map((g) => `${JSON.stringify(g.id)}=${rationalText(g.value)}`)
            .join("，"),
        "曲线系数 " +
          r.coefficients.map((c) => `R${c.index + 1}=${c.value.fraction}`).join("，"),
      ].map((text) => {
        const div = document.createElement("div");
        div.textContent = text;
        return div;
      }),
    );
    $("result").textContent = JSON.stringify(r, null, 2);
    renderChart($("chart"), r.points);
  }

  $("request").addEventListener("input", () => {
    state.generation += 1; // any edit immediately stales the shown result
    $("status").textContent = "输入已变化，旧结果已失效";
    render();
  });

  $("run").addEventListener("click", async () => {
    const generationAtSolve = state.generation;
    const body = $("request").value;
    $("status").textContent = "求解中…";
    try {
      const response = await fetch("/api/grouped", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body,
      });
      const payload = await response.json();
      if (generationAtSolve !== state.generation) return; // edited mid-flight
      if (!response.ok) {
        throw new Error(
          (payload && payload.error && payload.error.message) || "请求失败",
        );
      }
      state.result = payload;
      state.solvedGeneration = generationAtSolve;
      $("status").textContent = "精确复核完成";
    } catch (error) {
      if (generationAtSolve === state.generation) {
        state.result = null;
        $("status").textContent = "";
        $("status").append(`整次拒绝：${error.message}`);
      }
    }
    render();
  });

  $("download").addEventListener("click", () => {
    if (!isResultUsable(state)) return; // stale results never download
    const csv = buildGroupedCsv(state.result);
    const url = URL.createObjectURL(
      new Blob([csv], { type: "text/csv;charset=utf-8" }),
    );
    const a = document.createElement("a");
    a.href = url;
    a.download = `grouped-${state.result.input_digest.slice(0, 12)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  });

  render();
}
