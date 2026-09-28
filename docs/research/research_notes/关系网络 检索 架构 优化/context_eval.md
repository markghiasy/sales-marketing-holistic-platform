# 上下文组装、Agent 记忆与评估

## 现有算法的上下文瓶颈是什么？

### Takeaway
现在是“两次模型调用之间执行一次本地检索”的有界工作流；最值得先改的是按目标挑选证据与显式报告覆盖范围，而不是直接增加上下文长度。人数、来源条数、输出 token 上限都不等于输入 token 预算。

### Cited Findings
- 第一调用产生最多 4 个 lookup；people 在名字及有来源标签上做字面子串 OR，按现有 activity 排序后最多取 12 人；第二调用合成答案。每次模型输出上限 3,000 token，但没有输入 token 预算器。[agent.py](C:/Users/Eva%20Ng/Desktop/ironman/network-demo-worktree/adapters/network/agent.py:38)
- evidence 按 ID 排序后截 40 条，缺少目标相关性与覆盖排序；`retrieved` 仍包含原始引用及重复对象。引用 ID 的白名单确保引用来自实际供给的证据，但不能保证“合成建议被证据支持”。事实栏采用来源原文，建议栏仍由模型生成。[agent.py](C:/Users/Eva%20Ng/Desktop/ironman/network-demo-worktree/adapters/network/agent.py:258)
- `compact_claim` 仅保留 source/target/relation/evidence_ids，省略 observed_at/valid_from/valid_to。底层先做时态过滤，因此不是自动泄露未来；但合成模型难以区分“何时发生、何时才得知、适用到何时”。[agent.py](C:/Users/Eva%20Ng/Desktop/ironman/network-demo-worktree/adapters/network/agent.py:199)、[projection.py](C:/Users/Eva%20Ng/Desktop/ironman/network-demo-worktree/adapters/network/projection.py:38)
- entity_context 将工作记录与通信活动分开：工作有 observed_at 和证据可见性检查；deliveries 是 delivered 更新条数，成员展示顺序仍是 owner 通信 activity。不能解释为贡献、质量、完成任务数或员工绩效。[context.py](C:/Users/Eva%20Ng/Desktop/ironman/network-demo-worktree/adapters/network/context.py:19)
- 文档报告一次压缩使输入由 27,928 降到 10,451 token，明确为单次运行、非控制实验；四轮历史留在浏览器内存，当前没有长期 agent memory。[demo 说明](C:/Users/Eva%20Ng/Desktop/ironman/network-demo-worktree/docs/demos/network-intelligence.md)
- Anthropic 主张保留最小而足够的高信息量上下文，使用轻量索引按需加载，并指出探索式检索存在延迟成本；长期记忆可以用结构化笔记保存决策、未解决事项。[Anthropic context engineering，2025](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)
- Lost in the Middle 在其测试模型与任务中发现相关内容的位置会显著影响表现，中部常弱于开头/末尾；这是应测试位置敏感性的依据，不能直接推定当前 Haiku 有同等幅度退化。[论文，2023](https://arxiv.org/abs/2307.03172)

### Inferences
- 把 lookup 输出统一为精简 `EvidenceUnit`：事实/关系、实体、来源 ID、原文短摘、observed_at、valid_from/to、适用需求 ID、来源类型。一个来源正文只出现一次，其他位置引用 ID；依赖的关系链及修正证据须成组保留。
- 当前 OR 结果是“候选池”，不是“满足全部能力需求的名单”。例如 Research 可以命中项目 Research bridge，不意味着命中的人具备 Research 职能；必须保留标签种类与命中原因，交给显式需求验证。
- 将 `retrieved_count / eligible_count / selected_count / omitted_by_budget / uncovered_requirements` 交给合成与 UI；否则“没检到”与“已搜过而无证据”混在一起。

### Gaps
- 未进行 live API 实验，没有现有策略质量、端到端成本或上下文截断错误率的统计。只检查代码、文档并运行纯本地 retrieve 示例；无凭证读取、无服务调用。

## 怎样用小规模改动提高目标推理与证据完整性？

### Takeaway
先做需求分解、覆盖驱动的证据包及一次条件补查；继续沿用现有时态投影和来源校验。长期记忆只保存可追溯事实及用户确认的目标，生成的策略不能自动升级为人物能力事实。

### Cited Findings
- MMR 将查询相关性与相对于已选文档的新信息组合，减少重复来源挤占结果；原文也指出非常需要高召回时，纯相关性排序有适用场景。[Goldstein & Carbonell，1998](https://aclanthology.org/X98-1025.pdf)
- Hindsight 区分世界事实、agent 经历、主观意见和实体摘要；Recall 联合语义、词法、图与时间渠道，再融合、重排并按 token 预算输出。其设计可借鉴，但论文记忆 benchmark 的成绩不能转作本项目策略任务的预期收益。[Hindsight，2025，§3–4](https://arxiv.org/html/2512.12818v1)
- Self-RAG 使用训练得到的 reflection tokens 决定检索并检查相关性、支持程度和实用性；论文训练了 critic 与 generator。仅在 Haiku 提示词里增加“自我检查”，不能声称实现了论文算法。[Self-RAG，ICLR 2024，§3](https://arxiv.org/html/2310.11511v1)

### Inferences
建议的最小管线（工程提案，尚未验证）：

1. **GoalSpec**：从问题抽出 decision、capability_requirements、must/prefer、entity_scope、as_of、期望交付。Cybertest 若具体含义不明，先给可修改的假设；例如“AI 对抗/安全测试”只作为待确认需求，再拆成评测方法、工程实现、领域/安全知识、试点资源，不能从名称臆造商业计划。
2. **候选召回**：按每项需求查名字/类型化标签/项目工作原文，随后查相关实体关系；可先做本地词法检索与受控同义词，向量渠道作为后续消融实验。现有工程/研究标签只产生相邻候选，不直接满足专业安全能力。
3. **硬资格过滤**：先应用 as_of、状态、有效期、来源可见性，再相关性排序。保留底层“生效时间”和“获知时间”区分；不要让衰减分数替代资格过滤。项目记录未来扩展需稳定 task_id 与版本/替代关系，避免把同一任务多次 delivered 更新当多个成果。
4. **去重与覆盖打包**：先 evidence_id 去重，再对转发/近重复内容合并，保留来源别名。先保证关键需求、反证/冲突和每条推荐路径的完整边证据，再用 MMR 风格边际分数填满预算：`相关性 + 新覆盖需求 - 与已选内容重复`；可除以 token 成本作为启发式。MMR 不能删掉看似重复但完成另一条路径的必要证据。起步比较 4k/8k/12k 证据 token 档位；这些数值是实验参数，不是论文结论。
5. **一次补查**：coverage 表出现关键未知、路径缺边或来源被截断时，执行一个有明确目标的补查；无新增有效证据就停止。第一阶段可让原 planner 同时输出 fallback queries，由本地规则触发，维持两次模型调用；需要动态重规划时才实验增加一次调用并单独计价。
6. **输出证据状态**：每个候选×需求显示 `supported / contradicted / unknown`；unknown 再区分未搜索、预算截断、已搜索但未发现支持。共同公司/项目是 shared context；只有明确的人际边才能称已证实连接，而且连接仍不等于愿意引荐。项目催办围绕责任人、截止时间、阻塞、最新状态；activity 只作联系时机的辅助信号。
7. **短期记忆**：跨轮只保留用户确认的目标/约束、选中实体、as_of、已查需求、未解决问题、证据 ID。缓存键至少含数据 version、as_of、scope；日期变化必须重检来源。策略建议另存为 hypothesis，不能反馈成 confirmed contact tag。

### Gaps
- MMR 权重、token 档位、一次补查收益及向量召回是否值得，需要本地任务集验证。未推荐整体迁移到 Hindsight，也未证明其时间检索等价于本仓库的双时间语义。

## 怎样诚实评估 Cybertest、能力缺口、引荐路径和项目跟进？

### Takeaway
同时测“找对证据、证据足够、回答不越界、建议有用”，不能只测 JSON 合法、来源 ID 存在或一次漂亮示例。先建立固定快照的小任务集，再做同模型、同问题、同预算的成对比较。

### Cited Findings
- Anthropic 建议从 20–50 个来自真实失败的小任务起步，分别使用代码、模型和人工 grader；模型评分需人工校准，同任务多次 trial 才能观察随机波动。研究型任务可分 groundedness、coverage 与来源质量评分。[Anthropic evals，2026](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)
- 当前 demo 文档已经明确“引用约束修复机械错误，不保证策略质量”；现有 token 对比不能支持优化已有效的结论。[demo 说明](C:/Users/Eva%20Ng/Desktop/ironman/network-demo-worktree/docs/demos/network-intelligence.md)

### Inferences
- 建议 32 题、四类各 8 题，留开发/保留测试两部分，固定 fixture version/as_of；每题标记所需事实集合、可接受答案、不可推出的能力/关系。每版多次运行（例如 3 次，次数是成本可控的起点），记录差异而非只挑最好一次。

| 题型 | 正确行为 | 关键反例 |
|---|---|---|
| Cybertest 策略 | 分解需求；列已支持的相邻能力、待验证专长与下一步 | 工程师不自动是红队专家；业务名变化仍有效，不能靠 system prompt 中 Cybertest 专门提示获胜 |
| 联系人能力缺口 | 明确哪些需求缺证据与搜索覆盖范围 | 移除某人的唯一能力证据后，应变 unknown；不能说这个人“不会” |
| 引荐路径 | 每条边可追溯且符合日期；标注 shared context vs 明确连接 | owner hub 造成的伪二度、同公司≠认识、同名异人、过期关系 |
| 项目跟进 | 依据责任、due、blocker、最新状态提出跟进 | 高频聊天但无交付；低频聊天有交付；重复状态更新；晚获知的修正 |

- **检索层**：按任务标注的 eligible gold sources 计算 recall@token-budget；额外算 requirement coverage、完整路径召回、来源包引用闭合率、重复 token 比例、未来证据泄露数、截断告知率。多来源可替代时以事实/关系支持集合计分，别强制唯一 evidence ID。
- **回答层**：原子事实是否被来源支持、关键事实是否漏掉、未知能力误判率、关系过度推断率、建议的条件性与可执行性。代码查 ID/时间/路径；人工盲评建议是否切合目标；若用 LLM judge，需遮蔽系统版本并以人工样本校准。
- **效率层**：分别记录 planner/synthesizer 输入输出 token、查询次数、时延 P50/P95、失败/澄清率；不要把更多拒答造成的低幻觉率当全面改善。用质量—成本曲线选配置。
- **消融**：A 当前版本；B token 打包+去重；C B+需求覆盖与完整路径约束；D C+一次补查；E 再加向量召回。一次只加一种机制，定位真正收益。
- **抗扰动**：同义改写、中英切换、证据位置前/中/后移动、ID 重命名、灌入重复来源、缺失来源、冲突及未来修正；ID 重命名不应改变证据选择质量。添加活跃但无专长的人不应把合格低频候选挤掉。

### Gaps
- 合成集可验证机制，不能证明真实关系网络中提高商业决策或引荐成功率；需要未来用户授权的脱敏实例和人工评判。现阶段不应给“提升 X%”或“最佳架构”的定量承诺。
