# 实验执行交接单

## 你接手的目标

在本目录内完成一个可运行、可复现、可解释的 AgentRec Demo，并真正运行 pilot 和完整消融实验。最终交付代码、配置、逐样本轨迹、聚合表、失败案例与结论；不能只写设计文档。

项目定位必须始终保持为：**推荐是环境和工具，Agent 的规划、澄清、工具选择、记忆更新与失败恢复是核心。**

## 开始前必读

1. `README.md`
2. `docs/IMPLEMENTATION_PLAN.md`
3. `docs/EXPERIMENT_PROTOCOL.md`
4. `upstream/bearcode/README.md`
5. `upstream/bearcode/wiki/架构设计.md`
6. `upstream/bearcode/agents/agent.py`
7. `upstream/bearcode/agents/tools.py`
8. `upstream/bearcode/agents/memory.py`
9. `upstream/bearcode/agents/session_memory.py`

## 必须完成的交付物

- 一条端到端购物任务可以运行：用户请求 → Agent 决策 → 查询/比较工具 → 推荐 → 用户反馈 → 重规划 → 最终答案。
- 商品目录、用户画像、候选召回/排序、评论摘要至少以本地确定性工具形式存在。
- 分层记忆至少区分稳定偏好、阶段偏好、当前意图、购买对象、硬约束和反馈事件。
- 每条记忆有证据来源、时间、置信度、适用对象和状态；给他人购物不得覆盖本人长期偏好。
- 完成固定流水线、无记忆、扁平记忆、分层记忆四个主基线。
- 完成至少三项 Agent/记忆消融：无主动澄清、无失败重规划、无对象隔离或无时间衰减。
- 输出逐样本 JSONL 轨迹；每个聚合指标都能回溯到样本。
- 输出 bootstrap 95% 置信区间，随机过程固定并记录 seed。
- 形成 `reports/final_report.md`，同时报告正向、零结果和负向结果。
- 补充自动化测试，至少覆盖记忆更新、对象隔离、硬约束和指标计算。

## 推荐执行顺序

1. 对上游 runtime 做最小烟雾测试和关键路径修复。
2. 先构建 20 个纯确定性任务，验证工具、状态、指标和日志。
3. 扩展到不超过 100 个任务的 pilot，只比较固定流水线、扁平记忆、分层记忆。
4. 冻结任务集、Prompt、候选池、模型参数和主指标。
5. 跑完整基线与消融，保存原始轨迹。
6. 失败任务分类，必要时修复实现 bug；算法调整必须记录版本并重新运行全部相关组。
7. 生成报告和一条可演示案例。

## 当前已知的上游风险

下面是静态审计发现，必须先通过测试复现，确认影响当前路径后再最小修复：

- `agents/agent.py` 的 OpenAI 多 `tool_calls` 批处理疑似在循环中重复执行已经收集的工具调用，且拒绝调用可能缺少 tool result。
- Plan 审批路径存在异步调用和权限模式赋值问题；只有实验启用 Plan 模式时才是阻断项。
- `--thinking` 路径引用的方法名可能不存在；只有启用该参数时才修。
- 客户端协议选择依赖 base URL；无自定义 base 的 OpenAI 配置需要单独验证。
- `agents/memory.py` 的关键词预取对无空格中文查询可能失效。
- 上游无可靠单测，旧评测结果不能作为本项目基线。

不要一开始全面重构上游。优先保证本项目真实使用的路径正确，并给每个修复添加回归测试。

## 数据决策

- **第一阶段**：使用本地小型商品目录和基于真实商品字段构造的受控任务，确保可离线、确定性地完成实验闭环。
- **第二阶段主数据**：优先接 AgentRecBench 的 Amazon 场景；若下载或环境成本过高，使用 Amazon Reviews 2023 单品类子集自行构建。
- `upstream/bearcode/data/WebShop/test.json` 只用于 schema 和购物任务烟雾测试，不直接声称为 AgentRec 实验结果。
- 所有合成或注入的偏好变化必须单独标记 `controlled=true`，不得与真实日志混称。
- 大数据放入 `data/external/`，加工产物放入 `data/processed/`，记录下载地址、版本、校验值、筛选规则和许可证。

## 实验红线

- 不伪造、不补写、不挑选性删除实验结果。
- 不把 API Key、`.env`、用户路径或原始隐私数据提交到仓库。
- 不使用未来信息更新当前用户画像。
- 各实验组保持相同模型、候选池、最大轮数、工具预算和评测样本。
- 传统排序指标没有提升并不构成失败；必须检查任务成功、约束满足、画像污染和失败恢复。
- 如果全部指标无差异，先验证 Agent 是否真正读取并使用了记忆，而不是直接调 Prompt 追涨点。

## 完成定义

只有当下列命令或等价入口存在且通过，才算交付完成：

```powershell
python -m pytest
python -m agentrec.cli demo --scenario recipient_shift
python -m agentrec.experiments.run --config experiments/configs/pilot.yaml
python -m agentrec.experiments.run --config experiments/configs/full.yaml
python -m agentrec.reports.build --results results/raw --output reports/final_report.md
```

可以调整模块名，但必须在 README 中提供一键复现命令。
