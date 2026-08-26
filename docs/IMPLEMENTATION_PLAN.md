# 实现计划与目标架构

## 1. 最终系统

```text
用户/模拟器
  → Agent orchestrator
      → 状态观察与任务分类
      → 规划：追问 / 检索 / 比较 / 推荐 / 重规划
      → 商品工具：search、rank、compare、review_summary
      → 偏好工具：read_profile、write_memory、resolve_conflict
      → 安全与预算：硬约束检查、调用次数和 token 限制
  → 推荐与解释
  → 用户反馈
  → 记忆更新与下一轮行动
```

推荐模型只是 `rank` 工具的一种实现。第一版可以是 BM25/规则/轻量向量打分，以便把实验变量集中在 Agent 行为，而不是模型训练。

## 2. 建议代码结构

```text
agentrec/
  cli.py
  domain/
    models.py              # Product、Constraint、Preference、Task、Event
  tools/
    catalog.py             # 商品查询和过滤
    ranking.py             # 固定候选池上的可替换排序工具
    comparison.py
    profile.py
  memory/
    base.py
    flat.py
    hierarchical.py
    update_policy.py
    retrieval_policy.py
  agent/
    orchestrator.py
    planner.py
    policy.py
    reflection.py
  simulation/
    user_simulator.py
    scenarios.py
  experiments/
    run.py
    tasks.py
    metrics.py
    bootstrap.py
  reports/
    build.py
tests/
```

可以复用 Bear Code，也可以通过适配器调用它，但不要直接把所有实验逻辑堆进 `upstream/bearcode/agents/agent.py`。

## 3. 分层记忆合同

每条记忆建议采用统一结构：

```json
{
  "memory_id": "m_001",
  "layer": "stable|stage|session|recipient|constraint|event",
  "subject": "self|recipient:<id>",
  "attribute": "brand",
  "value": "Android",
  "polarity": "prefer|avoid|required",
  "confidence": 0.9,
  "source": "explicit|repeated_behavior|single_behavior|derived",
  "evidence_event_ids": ["e_001"],
  "created_at": "ISO-8601",
  "valid_from": "ISO-8601",
  "expires_at": null,
  "status": "active|candidate|superseded|expired",
  "supersedes": null
}
```

最小更新策略：

- 用户明确陈述的硬约束优先级最高。
- 单次点击不能直接形成高置信长期偏好。
- 重复行为逐步增加置信度，并保存证据事件。
- 当前会话需求和购买对象偏好不能覆盖本人稳定偏好。
- 冲突信息进入候选或版本替换流程，不静默覆盖。
- 阶段和会话偏好支持过期；过期不等于删除，仍可审计。

## 4. Agent 动作空间

至少支持以下动作并记录原因：

- `ask_clarifying_question`
- `search_products`
- `retrieve_preferences`
- `filter_constraints`
- `rank_candidates`
- `compare_products`
- `recommend`
- `reflect_on_feedback`
- `update_memory`
- `finish`

每轮轨迹记录 observation、selected_action、action_arguments、tool_result、memory_reads、memory_writes、constraint_check、latency、token/cost 和错误。

## 5. 里程碑

### M0：runtime 可测

- 固定依赖版本，确认 Python 版本。
- 建立测试入口和最小 Agent/tool smoke test。
- 只修复实际阻断实验路径的上游问题。

### M1：确定性闭环

- 本地商品目录和 20 个任务。
- 固定规则用户模拟器。
- 不依赖 LLM 也能验证指标与轨迹格式。

### M2：Agent pilot

- 接入一个可配置 LLM。
- 完成主动澄清、工具调用和一次反馈后的重规划。
- 比较固定流水线、扁平记忆、分层记忆。

### M3：完整消融

- 冻结实验协议。
- 扩展任务和多 seed 运行。
- 输出置信区间、失败分类和成本。

### M4：面试交付

- 一键演示案例。
- 最终实验报告。
- 架构图、核心轨迹和诚实的简历表述。

## 6. 范围控制

第一版不做强化学习、不训练大规模推荐模型、不接真实支付、不做线上 A/B。优先保证 Agent 行为可观察、实验可重复、结论可辩护。
