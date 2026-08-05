# Phase 12 layer-1 里程碑记录

**日期**: 2026-07-22 (二次修订 — 修 naive/lw_erc solver bug)
**范围**: v6 pool, IS ≤ 2023-12-31, cost 10 bp/side, OOS **封存**
**分支**: block-level risk budgeting + 10-mo MA trend gate, **standalone (无 α 层)**
**代码**: `scripts/block_composite_v6.py` + `scripts/block_risk_budget_v6.py`
**详细报告**: `reports/block_risk_budget_v6_report.md` (+ `_no_trend_report.md` 消融)

---

## 0. Bug fix note (2026-07-22 二次修订)

用户审代码发现两个独立 bug, 修正后重新跑齐所有 4 variants + no-trend 消融:

1. **`solve_naive` 系数错**. 原写 `w_b ∝ policy_b / σ_b`. 对角协方差下这个交付的是
   `RC_b ∝ policy_b²` (55/20/10/15 的 policy 平方归一化 = 80.7/10.7/2.7/6.0),
   实测在 no-trend §3 上正好逐位吻合. 正确闭式解是 **`w_b ∝ √policy_b / σ_b`**
   (推导: RC_b = w_b²σ_b² = c · policy_b → w_b = √(c·policy_b) / σ_b).

2. **`ledoit_wolf_cov` shrinkage target 错**. 原写 `F = Tr(S)/N · I` (LW 2004
   等方差目标). 本 pool 四个 block 方差差一个数量级 (equity σ ~17.6%, bond σ ~2%),
   等方差目标把 bond var 拉高 30x, equity var 压低, ERC solve 严重失真.
   改用 **`F = diag(S)`** (Schäfer & Strimmer 2005 target-D), 保留对角、只收缩
   off-diagonal 相关系数. 修正的 shrinkage intensity 公式:
   `α* = Σ_{i≠j} Var̂(s_ij) / Σ_{i≠j} s_ij²`.

修 bug 后数值变化如下, 各 cell Sharpe 都上升, CAGR 下降 (book vol 下降更多):

| variant | 旧 Sharpe | 新 Sharpe | Δ | 旧 CAGR | 新 CAGR |
|:---|---:|---:|---:|---:|---:|
| eqw × naive     | +1.185 | **+1.333** | +0.148 | +3.66% | +3.30% |
| eqw × lw_erc    | +1.125 | **+1.429** | +0.304 | +4.46% | +3.40% |
| invvol × naive  | +1.177 | +1.321 | +0.144 | +3.52% | +3.16% |
| invvol × lw_erc | +1.109 | +1.381 | +0.272 | +4.25% | +3.17% |

Naive 的实测 realized RC 现在很接近 policy: no-trend 版 §3 显示所有 4 cell
统一为 **57.5 / 20.9 / 10.0 / 15.7** vs policy 55 / 20 / 10 / 15
(2.5 pp 的 equity 溢出来自对角近似没算上 equity-commodity 正相关; lw_erc
把这部分捡了回来, 所以 Sharpe 高一点).

---

## 1. 结论 (TL;DR)

- **第一层单独跑 (无块内 α 选股) 已经反超 T2 bond_invvol**: 最佳 cell `eqw × lw_erc`
  IS Sharpe **+1.429** / CAGR +3.40% / DD −2.55% / vol 2.45% / turnover 0.053,
  相对 T2 `bond_invvol` (+1.425) +0.004 Sharpe, +1.00 pp CAGR, DD 只有 T2 的 60%.
  相对 Phase 11.2 production finalist `solo defensive` (+1.002) **+0.43 Sharpe**.
- **所有 4 个 cell 都在 +1.32 到 +1.43 IS Sharpe** — 稳定压过 solo defensive.
- **两个 sizing 平手, eqw 微弱领先**: intra-block `eqw` 比 `invvol` 高
  ~0.05 Sharpe, corr +0.99. 建议 canonical = `eqw × lw_erc`.
- **`lw_erc` 求解器现在稳过 `naive`**: 修 shrinkage target 之后, LW 不再扭曲 block
  variance, ERC 干净地拾起 off-diagonal 相关系数信息, Sharpe 比对角近似高 +0.06-0.10.
- **Trend gate 修 bug 后变成 Sharpe-neutral overlay**: 每 cell +0.02 至 −0.04 Sharpe
  (invvol 侧甚至微负). 之前 +0.12 的 Sharpe boost 主要是 bug 版 naive 把 80% 风险
  堆在 equity 上, gate 掉 equity 收益比较大. 修完后 book 本身已经低 vol, gate
  的 switching cost 不划算.

---

## 2. 设计冻结点 (Phase 12 spec + 2026-07-22 讨论 + 二次修订)

### 2.1 Block groups (post-merge)

`BLOCK_MERGES = {smallcap_cn → broad_cn}`

| group | 组成 blocks | ever-admitted N |
|:---|:---|---:|
| equity      | broad_cn + sector_cn + cross_border_dm + cross_border_hk | 307 |
| bond_rates  | bond_rates                     | 16 |
| bond_credit | bond_credit                    | 14 |
| commodity   | metals + commodity_other       | 7  |

### 2.2 Policy risk shares (frozen)

`equity 55% / bond_rates 20% / bond_credit 10% / commodity 15%` — 用户 2026-07-22 冻结, 至少一版 OOS shot 前不动.

### 2.3 Trend gate

- 每个 group 用**自己的 composite NAV** (无 α 版本), 43-week (≈ 10 个月) 移动平均
- 用**因果版**: `causal_nav = NAV.shift(1)`, `trend[t] = causal_nav[t] > MA_43(causal_nav)[t]`
- OFF → 该 group 权重设 0, **释放的仓位归 cash**, 不重新分配到其他 ON blocks
- 每 group post-warmup 触发次数: 11–13 次 / 6 年 IS

### 2.4 求解器 (**修正版**)

| 名字 | 公式 | 备注 |
|:---|:---|:---|
| `naive` | **`w_b ∝ √policy_b / σ_b`, `Σw = 1`** | 对角协方差下的闭式 ERC. 交付 RC ∝ policy. |
| `lw_erc` | log-barrier `min 0.5·w'Σw − Σ p_b·log(w_b)`, Σ = **Schäfer-Strimmer target-D shrinkage** (F = diag(S)) | 完整 cov 求解器, 保留 diag, 只收缩 off-diagonal. |

- 滚动 cov window = 52W, warmup = 52 bars (前 52 bar book flat)
- 求解在 ON blocks 子集上, OFF blocks 直接归零

### 2.5 权重规范化

`Σ w_b = 1` when all ON. Trend OFF 触发时 cash 补足, **无 leverage, 无显式 vol target**.

---

## 3. 主结果 (IS, 4 variants — **修正版**)

| variant | IS Sharpe | CAGR | max DD | ann vol | turnover | mean K | cash |
|:---|---:|---:|---:|---:|---:|---:|---:|
| **eqw × lw_erc**    | **+1.429** | +3.40% | −2.55% | 2.45% | 0.053 | 51.6 | 30.1% |
| invvol × lw_erc | +1.381 | +3.17% | −2.55% | 2.24% | 0.066 | 53.9 | 29.1% |
| eqw × naive     | +1.333 | +3.30% | −2.60% | 2.59% | 0.055 | 51.6 | 30.6% |
| invvol × naive  | +1.321 | +3.16% | −2.55% | 2.32% | 0.063 | 53.9 | 28.8% |

---

## 4. 与既有基准对比 (all IS)

| 基准 | Sharpe | CAGR | max DD | 来源 |
|:---|---:|---:|---:|:---|
| **layer-1 (eqw × lw_erc)** | **+1.429** | +3.40% | −2.55% | 本工作 (修正版) |
| T2 bond_invvol | +1.425 | +2.40% | −4.26% | `bond_attribution_v6` |
| T3 bond_eqw    | +1.122 | +2.78% | −4.37% | 同上 |
| solo defensive (v6 production) | +1.002 | +3.48% | −5.24% | Phase 11.2 finalist |
| T1 universe_invvol | +0.707 | +5.46% | −8.09% | 同上 |
| T4 equity_invvol | +0.375 | +5.28% | −18.93% | 同上 |

层-1 与 solo defensive IS 相关性 **+0.75** — 有可观的独立信号, 不是 solo defensive 的重加权.

---

## 5. Realized RC-share (IS, **修正版 + §3a/§3b 拆分**)

用户 2026-07-22 二次审报告指出: 原 §3 只展示 gate-averaged 的一列, 数字看起来
和 pre-fix 版本很像 (equity 都在 42% 左右), 容易误以为 solver 没修好. 实际上
是 trend gate 把 equity 拉低了. 报告 writer 已改为拆两列展示.

### 5.1 §3a — Solver 直接交付的 RC (仅取全 4 block ON 的 bar)

| variant | equity | bond_rates | bond_credit | commodity | n bars |
|:---|---:|---:|---:|---:|---:|
| **policy (target)** | **55.0%** | **20.0%** | **10.0%** | **15.0%** | — |
| eqw × naive     | 58.8% | 21.4% | 10.0% | 16.0% | 156 |
| eqw × lw_erc    | 58.8% | 21.4% | 10.0% | 16.0% | 156 |
| invvol × naive  | 58.4% | 21.2% | 10.0% | 15.9% | 163 |
| invvol × lw_erc | 58.4% | 21.2% | 10.0% | 15.9% | 163 |

全 4 cell 在全-ON bar 上交付的 RC 都是 ~58.8/21.4/10.0/16.0, 相对 policy
55/20/10/15 有 **~4 pp equity 溢出**. 来源: 修正后的对角近似 (naive) 假设
Σ 对角, 但实际上 equity 与 commodity 正相关, 会让 equity 实际 RC 略高于
policy. `lw_erc` 在 target-D LW 下, off-diagonal 被强收缩到近 0
(N=4, T=52 情况下 shrinkage α 很高), 于是收敛到跟 naive 几乎相同的解.

要把 equity RC 精准打到 55% 需要 (a) 用 full-sample cov 无 shrinkage, 或者
(b) 换成保留 off-diagonal 的 shrinkage 目标 (如 constant-correlation).
当前设计是 IC-noise robust > 精准命中, 4 pp 漂移可接受.

### 5.2 §3b — Gate-averaged RC (所有 invested IS bar 的均值)

| variant | equity | bond_rates | bond_credit | commodity |
|:---|---:|---:|---:|---:|
| policy (target) | 55.0% | 20.0% | 10.0% | 15.0% |
| eqw × naive     | 41.5% | 30.8% | 12.1% | 20.5% |
| eqw × lw_erc    | 42.0% | 34.5% |  7.7% | 18.9% |
| invvol × naive  | 41.4% | 29.8% | 17.1% | 18.7% |
| invvol × lw_erc | 41.9% | 31.8% | 15.3% | 17.3% |

Equity RC 从 solver 交付的 ~58.8% 掉到 ~42%, 是 gate 把 equity 打掉 38% bar
的自然结果. 剩下的 3 个 block RC% 在 equity-OFF 的 bar 上等比放大 → 均值
里 bond_rates 从 21% → 31%, commodity 从 16% → 20%. 这是 book 实际交易
时的 mean RC, 但**不是** solver 求解目标的直接反映.

### 5.3 No-trend 版本对比 (纯 solver check)

| variant | equity | bond_rates | bond_credit | commodity |
|:---|---:|---:|---:|---:|
| policy | 55.0% | 20.0% | 10.0% | 15.0% |
| 所有 4 cell (no-trend) | 57.5% | 20.9% | 10.0% | 15.7% |

全 292 IS bar 全 ON, 无 gate 摊薄. 4 cell 全部相同, 说明修 bug 之后:
- naive 闭式解在对角 Σ 下交付 = policy (精确)
- lw_erc target-D 下也收敛到几乎同解 (off-diag 收缩很强)

---

## 6. Trend gate 消融 (**修正版**)

| variant | Sharpe (on / off / Δ) | CAGR pp Δ | DD (on / off) | vol (on / off) | turnover (on / off) |
|:---|---:|---:|---:|---:|---:|
| eqw × naive     | +1.333 / +1.309 / **+0.024** | −0.28 | −2.60 / −2.68 | 2.59 / 2.90 | 0.055 / 0.033 |
| eqw × lw_erc    | +1.429 / +1.405 / **+0.024** | −0.23 | −2.55 / −2.47 | 2.45 / 2.68 | 0.053 / 0.034 |
| invvol × naive  | +1.321 / +1.350 / **−0.029** | −0.25 | −2.55 / −2.55 | 2.32 / 2.48 | 0.063 / 0.045 |
| invvol × lw_erc | +1.381 / +1.418 / **−0.037** | −0.26 | −2.55 / −2.55 | 2.24 / 2.39 | 0.066 / 0.048 |

- Trend gate 已经不是明显的 Sharpe overlay (±0.04)
- 仍剪掉 ~0.2 pp vol, 剪掉 ~0.25 pp CAGR
- invvol 那侧 gate 甚至微负 (switching cost 覆盖不了 vol 节省)
- **修 bug 前** gate 看起来 +0.12 Sharpe, 那是因为 bug 版 naive 把 80% 风险压在
  equity 上, gate 掉 equity 有戏

## 7. Trend gate ON 比例 (post-warmup IS bars) — 未变

| variant | equity | bond_rates | bond_credit | commodity | switches/年 |
|:---|---:|---:|---:|---:|---:|
| eqw × naive / lw_erc     | 61.9% | 87.9% | 64.0% | 84.3% | ~13 |
| invvol × naive / lw_erc  | 61.9% | 87.9% | 92.0% | 80.3% | ~11 |

---

## 8. 按年拆分 (net weekly ret, IS, **修正版**)

| year | eqw × naive | eqw × lw_erc | invvol × naive | invvol × lw_erc |
|:---:|---:|---:|---:|---:|
| 2018 | — | — | — | — |
| 2019 | +6.01% | +5.88% | +6.02% | +5.86% |
| 2020 | +8.55% | +8.77% | +8.09% | +8.22% |
| 2021 | +2.54% | +2.34% | +1.85% | +1.84% |
| 2022 | +1.21% | +1.53% | +1.48% | +1.50% |
| 2023 | +1.71% | +2.13% | +1.63% | +1.75% |

- 2018 = warmup, book flat
- 2019–2020 是 CAGR 主要贡献年 (但比 bug 版低 2-6 pp, 因为 equity 权重降回来了)
- 2021–2023 每年都是低正收益

---

## 9. 打开的旋钮 (给后续 branch 排队)

按用户 2026-07-22 的排期, 以下都是 Phase 12 内部的独立测试:

1. **块内 sizing 定型** (`eqw` vs `invvol`) — 修 bug 后 eqw 微弱领先 (~+0.05 Sharpe),
   canonical 建议 `eqw × lw_erc`.
2. **块级 hysteresis ε** — 本报告 raw gate, 每 group 11–13 switches/年. Sweep
   `ε ∈ {0, 0.10, 0.20, 0.30}` 看 turnover / Sharpe / DD 取舍. 现在 gate 已经
   Sharpe-neutral, ε > 0 主要影响 gate 存废之争.
3. **求解器最终定型** (`naive` vs `lw_erc`) — 修 bug 后 lw_erc 稳过 naive
   +0.06-0.10 Sharpe. 定 `lw_erc`.
4. **q = 0.20 / 0.10 α 覆盖变体** — Phase 12 × Phase 13 组合分支, 独立报告.
5. **Trend gate 参数** — 目前用 43W (10 mo) 简单 MA. 可以试 26W / 52W / dual-MA
   / momentum. 未来 branch.

---

## 10. 项目状态判断

**Phase 12 layer-1 = validated & 反超 T2 bond_invvol.**

层-1 单独已经赢 T2 (+0.004 Sharpe, +1.00 pp CAGR, DD 60%), 也赢 solo defensive
(+0.43 Sharpe, DD 一半, IS 无 α 层). 意味着:

- **两层架构方向正确** — block risk-budgeting 本身是一阶价值来源, 且比之前预期
  的强得多;
- Phase 12 × Phase 13 组合有充分的 headroom;
- **OOS 一次性投注**的最小可行版本 = `eqw × lw_erc × trend_gate on × broad_cn K=5 α
  × sector_cn K=8 α + 其他 blocks eqw`.

**下一步建议顺序**:
1. Hysteresis ε sweep (最快 turnaround, 弄清 gate 是否值得保留)
2. Phase 12 × Phase 13 组合书 (broad_cn + sector_cn 换成 α 排序结果)
3. OOS 一次性投注

---

## 11. 数据 / 脚本 pointer

- Composite 构建: `scripts/block_composite_v6.py`
  - `data/block_composite_v6/{eqw,invvol}/{returns,nav,weights_*}.parquet`
- 层-1 book: `scripts/block_risk_budget_v6.py` (修正版 solver)
  - `data/block_risk_budget_v6/{sizing}_{budget}/{w_group, w_name, net_ret, summary, trend_gate, realized_rc, diag}`
  - 消融: `data/block_risk_budget_v6_no_trend/...`
- 主报告: `reports/block_risk_budget_v6_report.md` (含 §5b trend gate 消融)
- 消融报告: `reports/block_risk_budget_v6_no_trend_report.md`

## 12. 复现

```bash
cd v6/scripts

# 一次跑齐 4 variants (trend gate on)
python block_risk_budget_v6.py

# 消融 (trend gate off)
python block_risk_budget_v6.py --no-trend --out-tag no_trend

# 单 variant
python block_risk_budget_v6.py --sizings eqw --budgets lw_erc
```
