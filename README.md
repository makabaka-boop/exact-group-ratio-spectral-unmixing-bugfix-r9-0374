# 模拟光谱数据：FastAPI 精确求解端 + React 复核页

一次输入包含：

- **20～80** 个相同波长位置上的**整数观测值**（波长严格递增）；
- **2～6** 条**非负整数参考曲线**；
- 参考曲线必须**线性独立**，否则整份请求拒绝。

求解目标：求各参考曲线的**非负有理系数**，使重建曲线
`reconstructed = Σ xⱼ·referenceⱼ` 与观测值的**平方残差和最小**。
全程**不使用浮点优化器**——所有运算基于 Python `fractions.Fraction`。

## 精确求解算法（`backend/app/solver.py`）

对 k 条曲线（k ≤ 6），枚举所有非零系数集合（支撑集，共 2^k 个）：

1. 对每个支撑集，用**有理数高斯-若尔当消元**解该支撑上的正规方程
   `(AᵀA)_S x = (Aᵀy)_S`；
2. 解中出现负系数或零系数 → 该支撑不可行，跳过；
3. 可行候选按**精确 Fraction 残差平方和**比较，取最小；
4. 空支撑（全零系数）恒为可行候选。

线性独立性用有理数秩检验（高斯消元）确认；相关则返回
`422 linearly_dependent`，不静默丢弃任何曲线。

## 响应内容（精确）

`POST /api/solve` 返回：

- `coefficients`：每条曲线的**约分系数**（分子/分母/分数字符串 + 仅用于
  展示的十进制串）；
- `points[].reconstructed` / `points[].residual`：逐点重建值与残差
  （观测 − 重建，均为精确分数）；
- `rss`：总平方残差（精确分数）；
- `active_set`、`subsets_scanned`、`feasible_candidates`：枚举诊断；
- `input_digest`：请求规范 JSON 的 SHA-256，把结果与唯一输入绑定。

`POST /api/download` 对同一请求重算并返回精确 CSV（含 digest、系数、RSS、
逐点分数列）。任何维度/类型/独立性错误都返回统一信封
`{"error":{"code","message"}}`，HTTP 422，整份拒绝。

## 复核页（`frontend/`）

- 并列绘制**观测 / 重建**（上图）与**逐点残差**（下图，零轴 + 茎线）；
- **编辑后旧响应不可冒充新输入的结论**：页面保存求解时输入的规范签名，
  任何编辑都使结果立刻标记为“陈旧”（横幅 + 灰化 + 下载锁定），必须重新
  求解；逻辑见 `src/freshness.ts`；
- **图与下载来自同一响应对象**：CSV 直接由渲染图表的那个 `SolveResponse`
  生成（`src/csv.ts`），陈旧时禁止下载。

## 运行

```bash
# 后端（安装依赖后）
pip install -r backend/requirements.txt
cd backend
uvicorn app.main:app --port 8000          # http://127.0.0.1:8000/docs

# 前端开发（/api 代理到 8000）
cd frontend
npm install
npm run dev                               # http://localhost:5173
```

生产单端口：`npm run build` 后，FastAPI 检测到 `frontend/dist` 会自动在
`/` 托管页面（API 路由优先），可用 `SPECTRUM_WEB_DIST` 覆盖目录。

## 测试

```bash
# 后端：34 个（小矩阵独立枚举候选集合交叉验证、KKT 最优性、恰为零系数、
#       近似但不退化曲线、维度/相关性整份拒绝、digest、下载一致性）
cd backend && python -m pytest

# 前端：20 个（整数解析、陈旧判定、CSV 与响应同源）
cd frontend && npm test
```

后端求解器测试用一套**独立书写**的 Fraction 枚举实现交叉核对所有候选
支撑集，并用 NNLS 的 KKT 条件复核最优性；特别覆盖系数**恰为零**与
“几乎重复但仍满秩、不退化”的近似曲线情形。


## 固定组比例解混
打开 `/groups`，沿原整数光谱输入添加组清单；每条原参考曲线必须恰好属于一个组，组内指定严格正的有理比例 `{num:"整数",den:"正整数"}`，分子分母各不超过 1000000。
组变量非负，原曲线系数=所属组变量×该曲线比例；目标仍是原观测与所有原曲线共同重建的精确平方残差最小值。
返回组变量、每条原曲线系数、逐点重建与残差、总残差；全部使用精确有理数，单组及零组变量允许。
组 ID 唯一，成员索引不能重复、越界或遗漏。无效光谱、组或比例整次拒绝，不产生部分结果。
重排组清单不改变原曲线系数；页面图与下载对应同次完整请求，修改组或光谱使旧结果立即失效。原无组求解继续可用。


运行：在 frontend 安装依赖并构建页面，在 backend 启动 uvicorn app.main:app。固定组比例复核页位于 /groups。
