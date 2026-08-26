# AgentRec：具备分层记忆与反馈重规划能力的自主购物 Agent

AgentRec 已实现为一个可离线运行、可审计、可复现的自主购物 Agent 工程。推荐召回与排序只是环境工具；核心闭环是规划、主动澄清、工具选择、分层记忆、用户反馈、反思与重规划。

## 当前状态

- Bear Code 实际运行路径已做 offline smoke test；只修复了一个由回归测试复现的多工具调用重复执行问题。
- 本地商品目录、八类受控任务、用户模拟器、工具层、三种记忆策略、Agent loop、指标、bootstrap 和 JSONL 轨迹均已实现。
- 当前代码通过 46 项全量回归测试；受控阶段也通过 20-task smoke 和 100-task pilot 门禁。
- full 运行包含 5 个主基线和 4 个单因素消融，共保存 8,100 条未筛选 episode，运行错误为 0。
- AgentRecBench Amazon short-term 子集已按固定 revision 下载并完成泄漏审计；独立 100-task real-log pilot 保存 400 条轨迹，运行错误为 0。
- 付费 `agentrec_gateway / gpt-5.5` 已完成 20-task smoke 和 100-task pilot；pilot 保存 100 条未筛选轨迹、运行错误为 0。全部历史 401/403 和 gateway 兼容性失败轨迹仍保留。
- 基线提交为 `09facfe`；当前冻结 controlled full 的 dirty-tree 代码指纹为 `74aa0137a3ef25c5`。
- [最终实验报告](reports/final_report.md)、[真实日志报告](reports/real_data_report.md) 和各阶段固定位置汇总已生成。

## Agent 闭环

```text
用户请求
  -> 观察与计划
  -> 检索分层记忆
  -> 必要时主动澄清
  -> 搜索 / 约束过滤 / 排序 / 对比 / 评论摘要
  -> 推荐并接收用户反馈
  -> 反思失败原因、更新记忆、重规划
  -> 完成或到达预算
```

每个动作都记录 observation、action arguments、tool result、memory reads/writes、constraint check、延迟、token/cost 和错误。受控 evaluator 的隐藏 target/acceptance 只由用户模拟器读取，不暴露给 catalog/ranker 或 Agent。

## 数据与结论边界

受控主实验使用项目自带的 `controlled_catalog_v1`：32 个手工受控商品、4 个品类和 8 类确定性场景。`controlled=true` 写入每条任务和轨迹。受控结果验证机制和工程闭环，不代表线上推荐效果、真实用户 uplift 或外部数据泛化；离线策略的 token 与成本均为 0，也不等价于验证真实 LLM 的工具遵循能力。

另有一组完全分开的 AgentRecBench `short_term/amazon` 真实日志实验：100 个任务、1,969 个候选商品，`controlled=false`。它只评估静态候选排序的 exact target@1、HR 和 NDCG；不具备主动澄清、硬约束、对象污染或反馈恢复标签。下载版本、原始大小、SHA-256、筛选和泄漏审计均记录在 [数据登记表](docs/DATA_REGISTRY.md)，结果不与 controlled 汇总混合。

## 最终 controlled full 结果

每个系统 `n=900`（300 tasks × 3 seeds），表中为点估计；95% bootstrap 区间和配对差值见最终报告。

| 系统 | Task success | Hard constraints | Profile contamination | Recovery success | Stale-memory misuse |
|---|---:|---:|---:|---:|---:|
| fixed pipeline | 0.498 | 0.750 | 0.000 | 0.000 | 0.000 |
| Agent / no memory | 0.498 | 0.750 | 0.000 | 0.000 | 0.000 |
| flat memory | 0.750 | 0.750 | 0.126 | 0.000 | 0.000 |
| hierarchical memory | 0.750 | 0.750 | 0.000 | 0.000 | 0.000 |
| full Agent | 1.000 | 1.000 | 0.000 | 1.000 | 0.000 |
| no clarification | 0.937 | 0.937 | 0.000 | 0.747 | 0.000 |
| no replanning | 0.877 | 0.877 | 0.000 | 0.000 | 0.000 |
| no recipient isolation | 1.000 | 1.000 | 0.126 | 1.000 | 0.000 |
| no temporal decay | 1.000 | 1.000 | 0.000 | 1.000 | 0.127 |

诚实解读：在冻结的受控任务上，full Agent 完成率为 1.000；去掉 recipient isolation 或 temporal decay 没有降低主任务成功率，但分别产生 0.126 的画像污染和 0.127 的陈旧记忆误用。这两个零主指标结果没有被包装成性能提升。fixed pipeline 与 Agent/no memory 完全相同，说明仅增加“规划”外壳而缺少记忆、澄清和重规划，在这套任务上没有收益。

所有失败仍在 JSONL 中。早期 smoke/pilot 暴露的会话约束泄漏和跨样本共享 memory store 问题也保留原始运行，并记录在 [协议变更记录](docs/PROTOCOL_AMENDMENTS.md) 中。

## AgentRecBench 真实日志 pilot

固定数据 revision 为 `288f7f09ca0387e5169a61b219047aea397e4b06`。每个系统 `n=100`，有效 run 为 `agentrecbench_real_pilot-5e06aafcc42bea27-20260825T092126-4630a1`；下表为点估计，bootstrap 95% 区间和失败案例见 [真实日志报告](reports/real_data_report.md)。

| 系统 | Exact target@1 | HR@3 | HR@5 | NDCG@5 |
|---|---:|---:|---:|---:|
| candidate order | 0.020 | 0.150 | 0.240 | 0.132 |
| popularity | 0.240 | 0.370 | 0.460 | 0.356 |
| full-history lexical | 0.470 | 0.630 | 0.730 | 0.605 |
| short-term recency | 0.450 | 0.670 | 0.790 | 0.628 |

第一次 real smoke 因未排除候选商品评论而存在标签泄漏，已标记为协议无效且原始轨迹保留。修复后排除 99 条候选历史评论，审计重叠为 0，再完整重跑 smoke/pilot。真实日志结果显示文本历史基线优于候选原顺序与 popularity，但它不是交互式 Agent 成功率证据。

## `gpt-5.5` API 状态

LLM 控制器通过 Responses API 显式调用规划、记忆检索、主动澄清、目录检查、推荐、反思重规划和结束工具。当前 smoke/pilot 配置固定为独立 `agentrec_gateway`、模型 ID `gpt-5.5`，并设置 output token、工具调用和模型轮数上限。gateway 的实际计费规则尚未获得，因此账本美元数只按 OpenAI GPT-5.5 公价作 reference estimate，不能视为第三方账单或严格消费上限。

历史 `gpt-5.6-terra` 1-task preflight `agentrec_llm_smoke-f28ac116f82114d8-20260825T093039-70e555` 在首个请求收到 `401 invalid_api_key` 后立即停止。该运行保留为 runtime-error 轨迹，不构成模型效果结论。

迁移后的 20-task GPT-5.5 smoke `agentrec_llm_smoke-e2fe5777e4a873b7-20260825T181308-b542ab` 也在第一个请求收到 401 后按协议停止，仅保存 1 条 runtime-error 轨迹。审计确认当前 Codex 使用自定义 `sribd` provider，而 AgentRec 仍请求官方 OpenAI endpoint，key 与 endpoint 不匹配。两个失败请求均无已结算 token 成本；fail-closed 总保留为 `$0.05014375`，剩余总预算 `$9.94985625`。在明确选择官方 OpenAI key 或授权第三方 provider 并确认其计费前不再重试。

获得第三方 endpoint 授权后，1-task preflight `agentrec_llm_smoke-84d7ce7f5f169925-20260825T181819-2d65ba` 已实际请求 `https://ai.sribd.cn/v1`，但在推理前收到 `403`，说明该 provider 环境未启用 API key 使用。该请求同样为 `$0` settled；全部失败保守预留合计 `$0.0802875`，估算剩余 `$9.9197125`。继续付费实验需要 provider 侧启用 API key，或改用有效 OpenAI Platform key。

用户随后提供了专用于本项目的 OpenAI-compatible gateway（公开版本已隐去私有地址）。不带凭证的 `/models` 探测返回 401，证明服务可达；该网关当时未提供 HTTPS。为了防止把 key 经公网明文误发，运行器默认拒绝 HTTP，只有用户通过配置脚本的 `-AllowInsecureHttp` 显式确认后才允许请求。

gateway preflight 实测并最小修复了三个兼容性问题：不支持可选 `metadata`、不能通过 `previous_response_id` 恢复 tool-call 状态、在 `parallel_tool_calls=false` 下仍可能返回多个调用。当前实现改为无 `metadata`、每轮显式回传完整 Responses items，并只执行首个调用、把额外调用记录为冗余而不静默并行。成功 preflight 为 `agentrec_llm_smoke-4f0e87a8fd0712bb-20260826T004727-bf0034`。

20-task smoke `agentrec_llm_smoke-4f0e87a8fd0712bb-20260826T004907-d2f3bc` 完整结束，task success、hard constraints、recovery 分别为 1.000/1.000/1.000，profile contamination 为 0.000，错误为 0。100-task pilot `agentrec_llm_pilot-22e15e5699fbfdf2-20260826T005917-66c9ac` 同样为 1.000/1.000/1.000/0.000，错误为 0；共使用 1,451,090 input、428,160 cached-input、35,919 output tokens，按 OpenAI 公价的 reference estimate 为 `$6.4063`。

这些满分任务结果只适用于冻结的受控环境，不能解释为真实用户效果。负向机制信号没有删除：pilot 的 100 条中有 80 条出现一次额外 provider tool call；35 次实际澄清中 13 次增加了信息、22 次没有增加信息，显示明显的过度澄清倾向。跨 provider fail-closed charged/reserved reference 总额为 `$7.979394`，预算剩余 `$2.020606`；gateway 的真实账单价格仍未知。

## 一键复现

要求 Python 3.9+。若当前环境尚未安装依赖，先执行：

```powershell
Set-Location AgentRec
python -m pip install -r requirements.txt
```

随后一条命令会依次运行测试、两个演示、smoke、pilot、full 和报告生成：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\reproduce.ps1
```

该流程复现受控实验，不需要 API key 或网络；full 只有在最新 pilot 门禁通过且代码哈希一致时才会启动。外部数据和付费 API 实验使用下面的独立命令，避免把不同证据边界混为一次运行。

## 分阶段命令

```powershell
Set-Location AgentRec

python -m pytest -p no:cacheprovider
python -m agentrec.cli demo --scenario recipient_shift
python -m agentrec.cli demo --scenario rejection_recovery

python -m agentrec.experiments.run --config experiments/configs/smoke.yaml
python -m agentrec.experiments.run --config experiments/configs/pilot.yaml
python -m agentrec.experiments.run --config experiments/configs/full.yaml
python -m agentrec.reports.build --results results/raw --output reports/final_report.md
```

外部真实日志子集与报告：

```powershell
Set-Location AgentRec
python scripts\fetch_agentrecbench_subset.py --project-root . --scenario short_term --max-tasks 100 --workers 8
python -m agentrec.real.run --config experiments\configs\real_smoke.yaml
python -m agentrec.real.run --config experiments\configs\real_pilot.yaml
python -m agentrec.reports.real_data --project-root . --output reports\real_data_report.md
```

付费 LLM 实验使用独立的 `AGENTREC_API_KEY`，不会覆盖 Codex 的 `SRIBD_API_KEY`。当前 gateway 只有公网 HTTP；下面的 `-AllowInsecureHttp` 表示接受 key 和任务内容可能被链路中间方截获。更推荐先为 gateway 配置有效 HTTPS。若接受该风险，使用隐藏输入配置 key，完整重启 Codex 后再按 1-task preflight→20-task smoke→最多 100-task pilot 顺序执行：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\configure_agentrec_api.ps1 -BaseUrl https://gateway.example.com/v1 -Model gpt-5.5 -MaxCostUsd 10

python -m agentrec.llm.run --config experiments\configs\llm_smoke.yaml --max-tasks 1
python -m agentrec.llm.run --config experiments\configs\llm_smoke.yaml
python -m agentrec.llm.run --config experiments\configs\llm_pilot.yaml
```

## 产物

- `results/raw/<stage>/<run_id>/manifest.json`：环境、配置、commit、code hash、seed 和数据边界。
- `results/raw/<stage>/<run_id>/trajectories.jsonl`：逐 episode 完整轨迹，包括失败和异常。
- `results/raw/<stage>/<run_id>/summary.json`：该次运行聚合结果。
- `results/summary/{smoke,pilot,full}_summary.json`：各阶段最新固定位置汇总。
- `results/summary/{real_smoke,real_pilot}_summary.json`：真实日志静态排序的独立汇总。
- `results/api_usage/<model>_ledger.json`：按模型分文件、跨模型合并执行总上限的 API 成本结算/保留账本，不包含密钥。
- `results/summary/pilot_gate.json`：full 的执行门禁证据。
- `reports/final_report.md`：只从保存的 JSONL 重算的最终报告，含置信区间、配对比较、失败计数和源行定位。
- `reports/real_data_report.md`：独立真实日志 pilot、泄漏审计和代表性失败。

最终一键验收的 full 原始运行位于本地 `results/raw/full/agentrec_full-a6c5235444e80f7b-20260825T094146-76f830/`，恰好 8,100 行，manifest 明确记录 `offline-deterministic-policy`。`results/raw/` 因体积不纳入 Git；稳定汇总与报告纳入交付。

## 目录结构

- `agentrec/agent/`：策略特征、规划、反思、轨迹和 orchestration。
- `agentrec/memory/`：no-memory、flat、hierarchical，含版本化、冲突、对象隔离和时间衰减。
- `agentrec/tools/`：本地 catalog 的搜索、约束过滤、排序、比较、评论摘要和 profile read。
- `agentrec/simulation/`：八类任务生成器与只按问题披露信息的用户模拟器。
- `agentrec/experiments/`：配置冻结、代码指纹、运行门禁、指标和 paired bootstrap。
- `agentrec/reports/`：从原始 JSONL 自动生成报告。
- `agentrec/data/`、`agentrec/real/`：AgentRecBench 严格适配器和真实日志静态排序实验。
- `agentrec/llm/`：Responses API Agent、工具协议、预算账本、错误脱敏和付费运行器。
- `upstream/bearcode/`：清理后的 Bear Code 源码快照及最小运行时修复。
- `tests/`：Bear Code 回归测试和 AgentRec 单元/集成测试。

新增外部数据仍必须使用新的 source、config hash、run ID 和独立报告；版本、许可证、校验值、原始大小和处理脚本需补充进 [数据登记表](docs/DATA_REGISTRY.md)，不得与 controlled 汇总合并。
