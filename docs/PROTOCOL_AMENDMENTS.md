# 实验协议变更记录

本文件只记录在 pilot/full 结果产生前冻结的执行层变更。原始研究问题、主要指标、基线与单因素消融保持不变。

## 2026-08-24：离线受控 full

- **数据源**：`full.yaml` 从占位值 `agentrecbench_amazon_or_frozen_subset` 改为 `controlled_catalog`。
- **原因**：当前工作区没有 AgentRecBench/Amazon 数据；为避免网络、磁盘和许可证流程阻塞可运行工程，先完成无需下载的完整机制实验。
- **解释边界**：full 结果只能说明冻结受控任务上的闭环、机制差异和可复现性，不能声称真实用户效果、线上推荐提升或外部数据泛化。
- **后续扩展**：接入外部数据时必须产生新的 config hash、run ID 和独立报告，不与本次受控结果混合汇总。

## 2026-08-24：场景名称规范化

配置统一使用实现层的八个场景名：

1. `clear_single_turn`
2. `needs_clarification`
3. `preference_alignment`
4. `preference_conflict`
5. `recipient_shift`
6. `hard_constraints`
7. `rejection_recovery`
8. `cold_start`

这只是标签映射，不删除协议要求的任何场景。

## 2026-08-24：样本与 bootstrap 预算

- full 固定为每组每 seed 300 个任务，使用 `[42, 123, 2026]` 三个 seed。
- pilot 固定最多 100 个任务、一个 seed。
- percentile bootstrap 置信水平保持 95%。重采样次数冻结为 pilot 1000、full 2000；原占位配置中的 10000 次被下调以控制九组完整矩阵的本地运行时间。
- 报告必须同时给出样本量、失败数和逐任务轨迹，不能只依赖置信区间。

## 2026-08-24：离线策略模型

- 本轮受控实验使用 `offline-deterministic-policy`，不调用外部 LLM、没有 token 成本，也不需要 API key。
- 规划、澄清选择、工具调用、反馈反思和重规划仍作为显式 Agent 动作写入轨迹；确定性策略使机制测试可复现。
- 这不等价于验证真实 LLM 的工具遵循能力。未来 LLM 运行必须作为新实验组并保持同一任务、候选池、工具预算和评测器。

## 2026-08-25：pilot 实现缺陷修复

- 首次 pilot 虽然通过机械决策门，但 flat memory 将 `constraint/session/event` 写入扁平 `stable` 槽后，下一任务按存储层错误召回，导致跨品类不可能约束和成功率异常降至 0.04。
- 修复只改变跨任务检索资格：以审计字段 `origin_layer` 为准，只有来源为 `stable/stage/recipient` 的条目可跨任务召回；当前任务的约束仍直接参与过滤并保留记忆审计。
- 这是公平性与会话边界实现修复，不是针对测试集调权重。修复后重新运行全部 pilot 系统；首个 pilot 的原始轨迹继续保留。
- 第二次 pilot 验证上述修复后，又通过分场景表发现独立评测样本仍共享一个 memory store，上一样本的稳定偏好会影响下一样本，破坏 paired bootstrap 的 episode 独立性。
- 最终冻结方式改为每个 `(seed, system, task_id)` 新建 Agent/memory store；每条任务自身的历史通过冻结的 `initial_memories` 注入。这样仍测试长期证据召回、对象隔离和时间衰减，但不会让评测样本互相写入。第二次 pilot 同样保留，随后重新运行全部 pilot 系统。

## 2026-08-25：最终轨迹与 top-1 评测审计

- 最终完整性审计发现逐动作延迟字段使用 `elapsed_ms`，而冻结日志合同使用 `latency_ms`。字段已统一，并把 `step`、`latency_ms` 和其余审计字段加入回归测试；旧运行保留。
- 同一审计发现排序与用户验收虽然始终基于真实 top-1，但结束阶段的解释与硬约束指标会从 top-5 中选择隐藏 acceptance 的 relevant item。这不会改变 task success，却可能高估硬约束满足并让最终解释不对应首位推荐。
- 修复后，`final_answer` 和 `hard_constraint_satisfaction_rate` 只使用实际 `final_product_ids[0]`；隐藏 acceptance 只用于 simulator 验收和 HR/NDCG evaluator。增加回归断言后，重新执行测试、smoke、pilot、full 和报告。
- 当时冻结的 full run 为 `agentrec_full-a6c5235444e80f7b-20260825T002308-75628b`，代码指纹为 `b12d31f3571553db`。此前 full/pilot/smoke 原始轨迹均未删除，避免隐藏修复前的负向证据；后续扩展完成后又执行了当前代码的一键复现，见下方最终验收记录。

## 2026-08-25：AgentRecBench 独立真实日志扩展

- 外部扩展固定为 AgentRecBench 上游代码 commit `599a9f73edf76fc324f2336053e4c58d03720a4e`、数据 revision `288f7f09ca0387e5169a61b219047aea397e4b06`，只使用 `short_term/amazon` 前 100 个任务。
- 第一次 real smoke 直接使用用户评论历史，得到异常完美的 20/20 top-1。对照上游官方 baseline 后确认，必须从每个用户的可见历史中排除全部候选商品 ID；初次运行因此判为标签泄漏并保留为无效证据。
- 适配器随后排除 99 条候选商品历史评论，并新增回归断言，保证 target/candidate 与任务可见历史重叠为 0。修复后重新运行 20-task smoke 和 100-task pilot，分别保存 80 和 400 条轨迹，错误数均为 0。
- real-log 只报告 exact target@1、HR@3/5、NDCG@5 和排序失败案例；它不具备主动澄清、硬约束、profile contamination 或 recovery 标签，不与 controlled full 的主指标合表。

## 2026-08-25：`gpt-5.6-terra` API 预检

- LLM 实验固定使用 Responses API、模型 `gpt-5.6-terra`、`reasoning_effort=low`、`verbosity=low`、每次最多 500 output tokens；工具调用、模型轮数、总成本都由配置和持久化预算账本限制。
- 实际 1-task preflight 在首次请求即收到 `401 invalid_api_key`，推理尚未发生，保存 1 条 runtime-error 轨迹并立即停止。报告不得把该记录解释为模型失败或模型质量结果。
- 账本按 fail-closed 原则为无法结算的请求保留 `$0.02`，没有虚构 token 或已结算费用。当前 `$10.00` 上限中可用余额为 `$9.98`。
- API 错误日志在保存前统一脱敏；既有失败运行和账本也已清理并扫描，未发现可识别的 key 模式。在有效密钥到位前不重复发送付费请求。

## 2026-08-25：最终一键复现与模型标签隔离

- 在用户环境设置 `AGENTREC_MODEL=gpt-5.6-terra` 后执行验收时，发现受控 smoke/pilot/full 的占位符会把该值写进 manifest，尽管受控 runner 实际只执行离线确定性策略。该轮 `agentrec_full-9add91e464e0f12a-20260825T094019-272f47` 数值未受影响，但模型标签不准确，因此不作为最终冻结 run；原始轨迹继续保留。
- 受控三个配置现已显式锁定 `offline-deterministic-policy`，LLM 两个配置继续显式锁定 `gpt-5.6-terra`。回归测试在环境变量设为 Terra 时逐一验证受控配置不会被污染。
- 修复后从项目根目录完整执行 `scripts/reproduce.ps1`：38 tests、两个演示、20-record smoke、300-record pilot、8,100-record full 和报告生成全部通过。
- 最终冻结 full run 为 `agentrec_full-a6c5235444e80f7b-20260825T094146-76f830`，代码指纹 `74aa0137a3ef25c5`，manifest 模型为 `offline-deterministic-policy`，运行错误为 0。

## 2026-08-25：付费 API 目标迁移至 `gpt-5.5`

- 用户在 Terra preflight 失败后明确要求把后续 API 实验改为 `gpt-5.5`。这只改变尚未成功运行的付费 LLM 组；受控离线 full、AgentRecBench real-log 结果及历史 Terra 失败轨迹均不改写。
- `llm_smoke.yaml`、`llm_pilot.yaml`、运行器协议检查和安全配置脚本现固定为模型 ID `gpt-5.5`；Responses API、required function calling、`reasoning_effort=low`、`verbosity=low` 和工具/轮数/output-token 上限保持不变。
- 成本闸门按 2026-08-25 OpenAI 官方模型页固定为每百万 token：input `$5.00`、cached input `$0.50`、output `$30.00`；输入超过 272K tokens 时按 2× input、1.5× output 计费。新增回归测试验证模型 ID、请求参数、普通上下文与长上下文费用计算。
- 新模型使用独立 `gpt-5.5_ledger.json`，但运行前会读取所有旧模型账本并扣除其 charged/reserved 金额，防止切换模型重置总预算。Terra 失败请求保留的 `$0.02` 因此计入原 `$10.00` 总上限，当前最多剩余 `$9.98`。
- 迁移完成时尚未发送任何 `gpt-5.5` 请求；只有有效的新 API key 配置并完全重启后，才按 20-task smoke → 最多 100-task pilot 执行。

## 2026-08-25：GPT-5.5 endpoint/key 不匹配

- 用户确认新 key 配置后，进程级与用户级 key 的只读布尔比较显示二者存在且一致；未输出或保存 key 内容。
- 20-task smoke `agentrec_llm_smoke-e2fe5777e4a873b7-20260825T181308-b542ab` 在第一个请求收到 `401 invalid_api_key`，按 `stop_on_error=true` 保存 1 条 runtime-error 轨迹后停止。没有生成 token 使用或模型质量结果。
- 后续只读审计发现当前 Codex 配置为自定义 `sribd` provider（Responses-compatible endpoint，凭证变量 `SRIBD_API_KEY`），而 AgentRec 的 OpenAI SDK 使用官方默认 endpoint；`SRIBD_API_KEY` 存在。因此最可能原因是 provider key 被填入官方 `OPENAI_API_KEY`，并非 GPT-5.5 模型 ID 错误。
- 不在未授权情况下把 AgentRec 数据改发第三方 endpoint，也不套用官方 GPT-5.5 价格声称能约束第三方账单。若继续，必须二选一：提供有效 OpenAI Platform key 保持原协议，或明确授权使用 `sribd` 并确认模型 ID/计费边界。
- 当前两个认证失败均为 `$0` settled；跨模型 fail-closed charged/reserved 合计 `$0.05014375`，总预算剩余 `$9.94985625`。

## 2026-08-25：`sribd / codex.gpt-5.5` 授权与 403

- 用户明确授权把受控合成购物任务发送到 `https://ai.sribd.cn/v1`，并接受该 provider 实际价格无法由 OpenAI 官方价格保证。
- 新 provider 配置固定使用 Responses-compatible endpoint、模型 ID `codex.gpt-5.5` 和凭证变量名 `SRIBD_API_KEY`；manifest 记录 provider/base URL/key 变量名，但绝不保存凭证值。provider 单独使用 `sribd_codex_gpt-5.5_ledger.json`，并继承此前所有账本的保留额。
- 账本中的美元值明确改为按 OpenAI GPT-5.5 公价计算的 reference estimate，`provider_pricing_verified=false`，不得解释为 sribd 实际账单或硬性消费上限。
- 实现和 43 项回归测试通过后，1-task preflight `agentrec_llm_smoke-84d7ce7f5f169925-20260825T181819-2d65ba` 到达第三方 endpoint，但在推理前收到 `403`，错误表明该环境未启用 API key 使用。保存 1 条 runtime-error 轨迹，token usage 与 settled cost 均为 0。
- 三次失败请求的 fail-closed reference reservation 合计 `$0.0802875`，估算余额 `$9.9197125`。该 403 是 provider 权限阻塞，不通过重试或修改 prompt 规避。

## 2026-08-26：独立 AgentRec gateway 与 HTTP 传输闸门

- 用户澄清 `SRIBD_API_KEY` 只供本地 Codex 使用，另行提供项目专用 OpenAI-compatible gateway（公开版本已隐去私有地址），模型 ID 为 `gpt-5.5`。后续配置改用隔离变量 `AGENTREC_API_KEY`，不得复用或覆盖 Codex 凭证。
- 不带认证的 `/v1/models` 连通性检查返回 401；HTTP 未重定向到 HTTPS，同端口的标准 HTTPS 握手失败。该检查没有发送 key、任务或其他项目数据。
- 因公网明文 HTTP 无法保护 bearer key 和任务内容，client 与 runner 均新增 fail-closed 闸门。只有环境变量 `AGENTREC_ALLOW_INSECURE_HTTP` 精确等于 `I_ACCEPT_PLAINTEXT_HTTP` 时才允许该 endpoint；配置脚本仅在用户显式传入 `-AllowInsecureHttp` 时设置该确认值。
- smoke/pilot 冻结为 provider `agentrec_gateway`、model `gpt-5.5`、key env `AGENTREC_API_KEY`。新 provider 使用独立账本，但继续继承历史账本的 charged/reserved 金额；实际第三方价格未知，所有美元数只按 OpenAI GPT-5.5 公价作 reference estimate。
- 完成初始接入后 44 项回归测试通过。用户随后在对话中明确授权明文传输风险并重启进程，才启动付费 preflight；结果见下一节。

## 2026-08-26：gateway 兼容性修复、smoke 与 pilot

- 第一次 gateway preflight `agentrec_llm_smoke-4f0e87a8fd0712bb-20260826T004029-224f6a` 在推理前返回 `Unsupported parameter: metadata`。仅移除该可选远端字段，本地 manifest/JSONL 审计不变；失败轨迹和 `$0.03014375` fail-closed reservation 保留。
- 第二次 preflight `agentrec_llm_smoke-4f0e87a8fd0712bb-20260826T004217-1cf776` 的首轮 function call 成功，但第二轮返回 `No tool call found for function call output`，证明 gateway 不能可靠恢复 `previous_response_id` 状态。实现改为每轮显式回传完整 Responses output items 与 tool outputs，不依赖服务端会话存储；已结算首轮 token/cost 与第二轮 `$0.03636875` 失败预留均保留。
- 第三次 preflight `agentrec_llm_smoke-4f0e87a8fd0712bb-20260826T004559-a1a257` 走通规划和澄清后，在 `parallel_tool_calls=false` 下仍返回两个 function calls。兼容层固定只执行顺序中的第一个，把其余调用作为 `ignored_function_calls` 写入轨迹并计入 redundant-tool-call 指标，避免未经工具结果的隐式并行动作。
- 第四次 1-task preflight `agentrec_llm_smoke-4f0e87a8fd0712bb-20260826T004727-bf0034` 完整成功。随后 20-task smoke `agentrec_llm_smoke-4f0e87a8fd0712bb-20260826T004907-d2f3bc` 保存 20/20 条记录、0 error，task success/hard constraints/profile contamination/recovery 为 1.000/1.000/0.000/1.000。
- 100-task pilot `agentrec_llm_pilot-22e15e5699fbfdf2-20260826T005917-66c9ac` 使用配置哈希 `22e15e5699fbfdf2`、代码指纹 `96b41e0fad6acc13`，保存 100/100 条记录并以 `stop=completed` 结束，0 runtime error。主指标为 task success 1.000、hard constraints 1.000、profile contamination 0.000；12 个 rejection-recovery 样本的 recovery success 为 1.000。
- pilot 总计 1,451,090 input、428,160 cached-input、35,919 output tokens；逐样本 reference estimate 合计 `$6.4063`。当前 gateway ledger settled `$7.832594`，加本 provider 的两笔失败预留及历史 provider 账本后，总 charged/reserved reference 为 `$7.979394`，原 `$10` 上限剩余 `$2.020606`。第三方真实计费未验证，这不是实际账单保证。
- 负向信号完整保留：80/100 个 pilot 样本各出现一次额外 provider tool call（73 次 `inspect_catalog`、7 次 `ask_clarifying_question`），均被记录后抑制；35 次实际澄清中 13 次有用、22 次没有新增信息。任务满分不消除工具协议不服从和过度澄清问题，也不外推为真实用户 uplift。
- 报告生成器现优先读取独立 LLM pilot 汇总与原始轨迹，并自动重算 token、reference cost、额外 tool-call 和澄清负向信号。最终 46 项回归测试通过。
