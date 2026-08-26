# AgentRec 简历项目展示

## AgentRec：可复现的自主购物智能体｜个人项目

**技术栈：** Python、OpenAI Responses API、Function Calling、分层记忆、AgentRecBench、PyTest、JSONL、Bootstrap

- 从零构建自主购物 Agent 闭环，将推荐系统作为工具层，实现任务规划、主动澄清、商品检索与约束过滤、分层记忆、用户反馈、失败反思及动态重规划；支持 recipient isolation、时间衰减和跨会话偏好管理。
- 设计 8 类可复现受控购物任务，对比 fixed pipeline、无记忆 Agent、扁平记忆、分层记忆和完整 Agent，并完成 4 项单因素消融；累计保存 8,100 条未筛选轨迹。完整 Agent 在受控 full benchmark 上取得 1.000 task success、1.000 hard-constraint satisfaction、0.000 profile contamination 和 1.000 recovery success。
- 通过消融验证关键机制：移除 replanning 后任务成功率降至 0.877，移除 clarification 后降至 0.937；移除 recipient isolation 产生 0.126 画像污染，移除 temporal decay 产生 0.127 陈旧记忆误用。
- 接入 GPT-5.5-compatible Responses API，完成 20-task smoke 和 100-task pilot，保存逐步规划、工具调用、token、成本及异常轨迹；受控 pilot 100/100 完成且无运行错误，同时诚实识别出过度澄清和 provider 多工具调用不服从等负向信号。
- 引入 AgentRecBench Amazon 真实日志进行独立评测，完成候选历史泄漏审计与修复；在 100 个真实日志任务上，short-term recency 达到 HR@5 0.790、NDCG@5 0.628，严格与受控 Agent 指标分开报告。
- 建立配置哈希、代码指纹、跨 provider 成本账本、Bootstrap 置信区间及 JSONL 全轨迹审计体系；完成 46 项回归测试和一键复现脚本，并对上游 Bear Code 的多工具重复执行问题实施最小修复与回归验证。

## 30 秒面试介绍

AgentRec 是一个可复现的自主购物 Agent 项目。它不是简单调用推荐模型，而是让 Agent 自己规划任务、判断是否需要澄清、调用本地商品工具、管理分层记忆，并在用户拒绝后反思和重规划。我设计了 5 个基线、4 个消融和 8 类受控任务，保存了全部逐样本轨迹，还加入 Amazon 真实日志和 GPT-5.5 pilot。项目最有价值的地方是通过消融证明了澄清、重规划、对象隔离和时间衰减分别解决什么问题，同时严格区分受控机制验证和真实推荐效果。

## 结果边界

受控任务上的满分结果只验证冻结环境中的机制闭环，不代表真实用户 uplift。真实日志实验是独立静态排序评测；GPT-5.5 pilot 中观察到的额外 provider tool call 和过度澄清均保留在最终报告中。
