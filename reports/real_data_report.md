# AgentRecBench Amazon 真实日志报告

本报告完全从已保存的 processed artifact、manifest、summary 和 JSONL 轨迹重建。
它与 controlled full 分开：这里评估静态候选排序，不具备主动澄清、硬约束、对象污染或反馈恢复的可观测标签。

## 数据边界

- Dataset: `SGJQovo/AgentRecBench`，revision `288f7f09ca0387e5169a61b219047aea397e4b06`，MIT。
- Scenario/domain: `short_term` / `amazon`；`controlled=false`，`data_type=real_log`。
- 任务 100；候选商品 1969；历史商品 781/781 成功解析；可见历史评论 917。
- 按官方 baseline 逻辑，从每个用户的可见历史中排除了全部候选商品评论，共 99 条；审计后 target/candidate 泄漏为 0。
- Processed artifact: `data/processed/agentrecbench_short_term_amazon_100.json`，9716755 bytes，SHA-256 `BFDC3FA3056B452D9A3AC1700231E9BC80D482FE234C5B156C73F239F1D169B1`。
- 商品原始范围为 23 个连续块，共 380,000,001 bytes；20 MB 处为 Yelp、30 MB 为 Amazon、400 MB 为 Goodreads。

## 100-task pilot

Run: `agentrecbench_real_pilot-5e06aafcc42bea27-20260825T092126-4630a1`；每个系统 n=100，共 400 条轨迹，错误数均为 0。括号为逐任务 bootstrap 95% CI。

| 系统 | Exact target@1 | HR@3 | HR@5 | NDCG@5 |
|---|---:|---:|---:|---:|
| candidate_order | 0.020 [0.000, 0.050] | 0.150 [0.080, 0.220] | 0.240 [0.150, 0.330] | 0.132 [0.087, 0.184] |
| popularity | 0.240 [0.160, 0.330] | 0.370 [0.270, 0.460] | 0.460 [0.350, 0.560] | 0.356 [0.276, 0.437] |
| full_history_lexical | 0.470 [0.380, 0.570] | 0.630 [0.530, 0.720] | 0.730 [0.630, 0.810] | 0.605 [0.530, 0.687] |
| short_term_recency | 0.450 [0.360, 0.550] | 0.670 [0.570, 0.760] | 0.790 [0.700, 0.870] | 0.628 [0.559, 0.705] |

诚实结论：历史文本基线明显优于候选原顺序和 popularity；recency 的 HR@5 最高，但其 exact target@1 低于 full-history。
这些结果只说明该固定 short-term Amazon 候选集上的离线命中，不代表真实用户 uplift，也不能替代 controlled Agent 机制指标。

## 泄漏审计与保留的失败运行

第一次 real smoke 没有排除候选商品评论，产生异常完美结果。审计上游官方 baseline 后修复；该运行没有删除，也不进入结论。

| Run | 记录数 | Code hash | 排除候选评论 | 协议有效 |
|---|---:|---|---:|---|
| `agentrecbench_real_smoke-7851b3340ba0d081-20260825T091944-b96996` | 80 | `eadee5d1924f22a5` | 未执行 | 否（泄漏） |
| `agentrecbench_real_smoke-7851b3340ba0d081-20260825T092106-2c8bf6` | 80 | `f929fcd8d0d6ccdf` | 99 | 是 |

## 代表性失败（short_term_recency）

- JSONL line 302，task `short_term_amazon_1`：target `B07ZJPCQBN`，top-5 `B09VS52R4D, B08YJX4R4Z, B07ZJPCQBN, B07CR1V2G9, B0BW8LYFKV`。
- JSONL line 305，task `short_term_amazon_4`：target `B0C4NX51BY`，top-5 `B0B3X8KMWM, B0C4NX51BY, B073TS1Z96, B0BRMYV3QY, B01AUNIQCA`。
- JSONL line 306，task `short_term_amazon_5`：target `B0BPYT9DKR`，top-5 `B000068NUW, B08Q7S3Z47, B08Q7MCFJY, B085H7LS8R, B086M6D78Q`。
- JSONL line 308，task `short_term_amazon_7`：target `B0C4F5WCHZ`，top-5 `B00LHQLWLC, B01B3JLPA0, B0C4F5WCHZ, B09BPPCDX7, B07DQHFTXR`。
- JSONL line 309，task `short_term_amazon_8`：target `B0BNWLWPSR`，top-5 `B07X2PG2YB, B00AM6IFVI, B0BNWLWPSR, B07FTY7VZN, B0BL2DDTW1`。

## 复现

```powershell
Set-Location AgentRec
python scripts\fetch_agentrecbench_subset.py --project-root . --scenario short_term --max-tasks 100 --workers 8
python -m agentrec.real.run --config experiments\configs\real_smoke.yaml
python -m agentrec.real.run --config experiments\configs\real_pilot.yaml
python -m agentrec.reports.real_data --project-root . --output reports\real_data_report.md
```
