# 数据登记表

## 已落盘并用于受控机制实验

| 字段 | 值 |
|---|---|
| 数据 ID | `controlled_catalog_v1` |
| 类型 | 项目自建的受控测试夹具，不是真实商品/用户日志 |
| 路径 | `data/processed/catalog.json` |
| 版本日期 | 2026-08-24 |
| 规模 | 32 个商品；headphones、shoes、backpacks、coffee_makers 各 8 个 |
| 文件大小 | 14,385 bytes |
| SHA-256 | `7E127D494568D9CC9251390D6050CB2D60712CDAF99E9DBC3CA0199959A442D3` |
| 来源 | 本项目为机制评测编写的确定性 fixture；未抓取外部站点 |
| 许可说明 | 不包含第三方数据，不据此主张任何外部数据许可或真实分布 |
| 处理 | 无下载；`load_catalog()` 做 schema 解析，任务生成器按冻结模板构造任务 |
| 实验标记 | catalog、Task、manifest 和每条 trajectory 均标记 controlled/source |
| 已用于 | smoke、pilot、controlled full |

受控 full 的真实/非受控记录数为 0。报告只能解释 controlled 机制行为，不能声称生产推荐质量或真实用户 uplift。

## 已落盘并用于独立真实日志实验

| 字段 | 值 |
|---|---|
| 数据 ID | `agentrecbench_short_term_amazon_100` |
| 类型 | AgentRecBench 的 Amazon short-term 真实日志候选排序子集；`controlled=false`、`data_type=real_log` |
| 上游代码 | `data/external/AgentRecBench`，commit `599a9f73edf76fc324f2336053e4c58d03720a4e` |
| 数据版本 | Hugging Face `SGJQovo/AgentRecBench` revision `288f7f09ca0387e5169a61b219047aea397e4b06` |
| 许可证 | MIT（上游仓库与数据卡声明） |
| 原始落盘 | task/groundtruth 200 个 JSON，共 69,000 bytes；short reviews 21,862,581 bytes；商品范围 23 个连续块，共 380,000,001 bytes |
| 处理后路径 | `data/processed/agentrecbench_short_term_amazon_100.json` |
| 处理后大小 | 9,716,755 bytes |
| 处理后 SHA-256 | `BFDC3FA3056B452D9A3AC1700231E9BC80D482FE234C5B156C73F239F1D169B1` |
| 评论原始 SHA-256 | `7D488A7DA555EE7BE4D1EC9399A726DF5C026C1CDD7112F1087BF40C7474634D` |
| 处理规则 | 只取 `short_term/amazon` 前 100 个任务；严格解析所有候选和历史商品；按官方 baseline 从任务可见历史中排除全部候选商品评论 |
| 处理后规模 | 100 tasks；1,969 个候选商品；781/781 个历史商品解析成功；2,632 个任务候选实例；1,016 条选中用户评论，其中 917 条任务可见 |
| 泄漏审计 | 共排除 99 条候选商品历史评论；处理后 target/candidate 与可见历史重叠为 0 |
| 有效 smoke | `agentrecbench_real_smoke-7851b3340ba0d081-20260825T092106-2c8bf6`，80 条轨迹、0 错误 |
| 有效 pilot | `agentrecbench_real_pilot-5e06aafcc42bea27-20260825T092126-4630a1`，400 条轨迹、0 错误 |
| 无效但保留 | `agentrecbench_real_smoke-7851b3340ba0d081-20260825T091944-b96996`；未排除候选评论，存在标签泄漏，不进入结论 |

该数据只支持静态候选排序的 exact target@1、HR@3/5 与 NDCG@5。它没有本项目受控任务所需的主动澄清、硬约束、对象污染或反馈恢复标签，因此不计算或混入对应主指标。独立结果见 `reports/real_data_report.md`。

## 其他尚未下载、未用于本轮结果

| 优先级 | 数据 | 预期用途 | 地址 | 当前状态与接入要求 |
|---|---|---|---|---|
| P1 | Amazon Reviews 2023 独立原始集 | 商品元数据、评论和交互扩展 | https://amazon-reviews-2023.github.io/ | 未单独下载；当前真实日志实验只使用上表冻结的 AgentRecBench Amazon 子集 |
| P2 | KuaiRec | 可选短视频扩展 | https://github.com/chongminggao/KuaiRec | 未下载；不得与购物主实验混合汇总 |

接入任何外部数据后必须补充：版本/日期、许可证、下载地址、文件 SHA-256、原始大小、筛选脚本、处理后样本数、source 字段、新 config hash、新 run ID 和独立报告。controlled 与 real-log 必须分表报告。
