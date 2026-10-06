import { useMemo, useState } from "react";
import SpectrumChart from "./components/SpectrumChart";
import { SAMPLES } from "./sampleData";
import { parseIntList, requestSignature, toText } from "./parse";
import { buildCsv } from "./csv";
import { canUseResult, isResultStale } from "./freshness";
import type { ApiError, SolveRequest, SolveResponse } from "./types";

const MIN_PTS = 20;
const MAX_PTS = 6;

interface Parsed {
  request: SolveRequest;
  errors: string[];
}

export default function App() {
  const initial = SAMPLES[0].request;
  const [wlText, setWlText] = useState(toText(initial.wavelengths));
  const [obsText, setObsText] = useState(toText(initial.observations));
  const [refTexts, setRefTexts] = useState<string[]>(
    initial.references.map((r) => toText(r)),
  );
  const [response, setResponse] = useState<SolveResponse | null>(null);
  const [solvedSignature, setSolvedSignature] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [apiError, setApiError] = useState<ApiError["error"] | null>(null);

  const parsed: Parsed = useMemo(() => {
    const errors: string[] = [];
    const wl = parseIntList(wlText);
    const obs = parseIntList(obsText);
    if (wl === null) errors.push("波长须全部为整数。");
    if (obs === null) errors.push("观测值须全部为整数。");
    const refs: number[][] = [];
    refTexts.forEach((t, i) => {
      const r = parseIntList(t, { nonNegative: true });
      if (r === null) errors.push(`参考曲线 ${i + 1} 须为非负整数。`);
      else refs.push(r);
    });
    if (errors.length)
      return {
        request: { wavelengths: [], observations: [], references: refs },
        errors,
      };

    const request: SolveRequest = {
      wavelengths: wl as number[],
      observations: obs as number[],
      references: refs,
    };

    const n = request.observations.length;
    if (n < 20 || n > 80) errors.push(`观测点数须在 20～80 之间，当前 ${n}。`);
    if (request.wavelengths.length !== n)
      errors.push(
        `波长数量（${request.wavelengths.length}）须与观测点数（${n}）一致。`,
      );
    else {
      for (let i = 1; i < n; i++) {
        if (request.wavelengths[i] <= request.wavelengths[i - 1]) {
          errors.push("波长位置须严格递增且不重复。");
          break;
        }
      }
    }
    if (request.references.length < 2 || request.references.length > MAX_PTS)
      errors.push(
        `参考曲线须为 2～6 条，当前 ${request.references.length} 条。`,
      );
    request.references.forEach((r, i) => {
      if (r.length !== n)
        errors.push(
          `参考曲线 ${i + 1} 长度 ${r.length} 与观测点数 ${n} 不一致。`,
        );
    });
    return { request, errors };
  }, [wlText, obsText, refTexts]);

  const currentSignature = useMemo(
    () =>
      parsed.errors.length === 0 ? requestSignature(parsed.request) : null,
    [parsed],
  );

  const isStale = isResultStale({
    hasResponse: response !== null,
    solvedSignature,
    currentSignature,
  });
  const resultUsable = canUseResult({
    hasResponse: response !== null,
    solvedSignature,
    currentSignature,
  });

  const canSubmit = parsed.errors.length === 0 && !loading;

  async function handleSolve() {
    if (parsed.errors.length) return;
    setLoading(true);
    setApiError(null);
    try {
      const r = await fetch("/api/solve", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(parsed.request),
      });
      const body = await r.json();
      if (!r.ok) {
        setApiError(body.error ?? { code: "unknown", message: "请求失败" });
        return;
      }
      const resp = body as SolveResponse;
      setResponse(resp);
      setSolvedSignature(requestSignature(parsed.request));
    } catch (e) {
      setApiError({
        code: "network",
        message: `网络错误：${(e as Error).message}`,
      });
    } finally {
      setLoading(false);
    }
  }

  function handleDownload() {
    // The download is generated from the SAME response object the chart is
    // rendered from, and only when the editor still matches that response.
    if (!response || !resultUsable) return;
    const csv = buildCsv(response);
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `spectrum-${response.input_digest.slice(0, 12)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }

  function loadSample(idx: number) {
    const s = SAMPLES[idx].request;
    setWlText(toText(s.wavelengths));
    setObsText(toText(s.observations));
    setRefTexts(s.references.map((r) => toText(r)));
    setResponse(null);
    setSolvedSignature(null);
    setApiError(null);
  }

  function addReference() {
    if (refTexts.length >= 6) return;
    const n = parsed.request.observations.length || 20;
    setRefTexts([...refTexts, Array.from({ length: n }, () => 0).join(", ")]);
  }

  function updateReference(i: number, v: string) {
    setRefTexts(refTexts.map((t, j) => (j === i ? v : t)));
  }

  function removeReference(i: number) {
    if (refTexts.length <= 2) return;
    setRefTexts(refTexts.filter((_, j) => j !== i));
  }

  return (
    <div className="page">
      <header>
        <h1>光谱 NNLS 精确求解复核台</h1>
        <p className="sub">
          非负有理系数 · 支撑集全枚举 · 有理数正规方程 ·
          精确残差比较（全程无浮点优化器）
        </p>
      </header>

      <div className="layout">
        <section className="editor panel">
          <h2>输入</h2>
          <div className="samples">
            {SAMPLES.map((s, i) => (
              <button
                key={i}
                className="btn-link"
                onClick={() => loadSample(i)}
              >
                {s.name}
              </button>
            ))}
          </div>

          <label>波长位置（严格递增，整数）</label>
          <textarea
            rows={2}
            value={wlText}
            onChange={(e) => setWlText(e.target.value)}
          />

          <label>观测值（{MIN_PTS}～80 个整数）</label>
          <textarea
            rows={3}
            value={obsText}
            onChange={(e) => setObsText(e.target.value)}
          />

          <div className="refs-head">
            <label>参考曲线（2～6 条非负整数）</label>
            <button
              className="btn-mini"
              onClick={addReference}
              disabled={refTexts.length >= 6}
            >
              + 增加曲线
            </button>
          </div>
          {refTexts.map((t, i) => (
            <div key={i} className="ref-row">
              <span className="ref-idx">R{i + 1}</span>
              <textarea
                rows={2}
                value={t}
                onChange={(e) => updateReference(i, e.target.value)}
              />
              <button
                className="btn-mini danger"
                onClick={() => removeReference(i)}
                disabled={refTexts.length <= 2}
                title="删除该曲线"
              >
                ×
              </button>
            </div>
          ))}

          {parsed.errors.length > 0 && (
            <div className="error-box">
              {parsed.errors.map((e, i) => (
                <div key={i}>• {e}</div>
              ))}
            </div>
          )}

          <button
            className="btn-primary"
            disabled={!canSubmit}
            onClick={handleSolve}
          >
            {loading ? "求解中…" : "求解"}
          </button>

          {apiError && (
            <div className="error-box server">
              <strong>整份请求被拒绝（{apiError.code}）</strong>
              <div>{apiError.message}</div>
            </div>
          )}
        </section>

        <section className="result panel">
          <h2>结果复核</h2>
          {!response && (
            <p className="empty">提交有效输入后在此显示精确结果。</p>
          )}

          {response && (
            <>
              {isStale && (
                <div className="stale-banner">
                  ⚠ 输入已被修改：以下图表与数据属于<strong>旧响应</strong>，
                  不能作为当前输入的结论；请重新「求解」。下载已锁定。
                </div>
              )}
              <div className={isStale ? "stale-content" : ""}>
                <div className="meta-grid">
                  <div>
                    <span className="meta-label">总平方残差 RSS</span>
                    <span className="mono big">{response.rss.fraction}</span>
                    <span className="meta-hint">≈ {response.rss.decimal}</span>
                  </div>
                  <div>
                    <span className="meta-label">枚举支撑集</span>
                    <span className="mono">{response.subsets_scanned}</span>
                    <span className="meta-hint">
                      可行 {response.feasible_candidates}
                    </span>
                  </div>
                  <div>
                    <span className="meta-label">输入指纹</span>
                    <span className="mono small">
                      {response.input_digest.slice(0, 16)}…
                    </span>
                  </div>
                </div>

                <table className="coef-table">
                  <thead>
                    <tr>
                      <th>参考曲线</th>
                      <th>约分系数</th>
                      <th>近似值</th>
                      <th>状态</th>
                    </tr>
                  </thead>
                  <tbody>
                    {response.coefficients.map((c) => {
                      const active = response.active_set.includes(c.index);
                      return (
                        <tr key={c.index} className={active ? "" : "zero-row"}>
                          <td>R{c.index + 1}</td>
                          <td className="mono">{c.value.fraction}</td>
                          <td className="mono muted">{c.value.decimal}</td>
                          <td>{active ? "非零" : "恰为零"}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>

                <SpectrumChart points={response.points} />

                <div className="actions">
                  <button
                    className="btn-secondary"
                    onClick={handleDownload}
                    disabled={isStale}
                    title={
                      isStale
                        ? "输入已修改，旧响应数据不可下载为新输入结论"
                        : "下载当前响应对应的精确 CSV"
                    }
                  >
                    下载 CSV（与图表同一响应）
                  </button>
                </div>

                <details>
                  <summary>逐点数据表（{response.points.length} 行）</summary>
                  <div className="table-wrap">
                    <table className="points-table">
                      <thead>
                        <tr>
                          <th>波长</th>
                          <th>观测</th>
                          <th>重建（分数）</th>
                          <th>残差（分数）</th>
                        </tr>
                      </thead>
                      <tbody>
                        {response.points.map((p, i) => (
                          <tr key={i}>
                            <td>{p.wavelength}</td>
                            <td>{p.observed}</td>
                            <td className="mono">{p.reconstructed.fraction}</td>
                            <td className="mono">{p.residual.fraction}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </details>
              </div>
            </>
          )}
        </section>
      </div>
      <footer>
        全部算术基于有理数精确完成；响应含输入指纹（SHA-256），图表与下载共用同一响应对象。
      </footer>
    </div>
  );
}
