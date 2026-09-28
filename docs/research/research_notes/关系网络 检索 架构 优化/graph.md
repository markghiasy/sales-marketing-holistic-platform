# 图遍历、上下文与可解释引荐路径研究

## 1. 现有实现到底是什么算法，有哪些语义和截断问题？

### Takeaway
当前实现是带时间、审核状态过滤的无权邻域扩展，加上以 owner 沟通活跃度排序的展示投影；并不是专门的最短引荐路径或语义 GraphRAG。适合小型关系图浏览，但展示截断与问答检索复用，可能丢掉解释路径所需的桥接节点。

### Cited Findings
- `eligible_claims` 按 rejected/pending、observed_at、valid_from/valid_to 过滤，并避免未来更正泄漏到历史快照。`build_snapshot` 先做身份归一化，然后构建合格边池。[本地 projection.py](../../../../adapters/network/projection.py#L38)
- compact 固定一跳；expand 深度 1–3。遍历对 source/target 对称处理，每轮从全部 reached 节点重扫边池；虽不是队列实现，但结果相当于有约束的无权无向可达扩展，并记录首次到达 hop。focus 不是 owner 时，owner 不作中转。[projection.py](../../../../adapters/network/projection.py#L180)；[深度与默认值 model.py](../../../../adapters/network/model.py#L15)
- `min_activity` 用的是联系人对 owner 的近期/历史直接会话衰减分数，过滤发生在扩展之前；并非 focus 到候选人的边权、关系可信度或图距离。会话按 contact/channel 分组，间隔超过 30 分钟才另起一段；半衰期 30/180 天。[projection.py](../../../../adapters/network/projection.py#L11)
- 展示最多 50 节点/100 边，compact 为 8/12；节点优先顺序是 focus、owner、按 owner 活跃度排序的人、剩余 ID；边按池中原顺序截断，并不排序路径或保留连通性。[projection.py](../../../../adapters/network/projection.py#L203)
- entity_context 取当前有效的直接 claims、成员、共享 organization/project、work records、follow-ups；共享上下文是显式两边路径，代码明确不推断友谊。它重新构造默认 GraphQuery，只继承 focus/as_of，因此不继承 history/include_pending 等查询设置。[context.py](../../../../adapters/network/context.py#L8)
- agent 的 neighborhood 直接复用上述 display snapshot，context 返回实体包，people 是名字及有来源 tags 的字面 OR 匹配、最多 12 人。agent 拒绝以 owner 查询 context/neighborhood，最多 4 个 lookup、两次模型调用；最终证据按 ID 排序取前 40 条。`compact_claim` 仅保留 source/target/relation/evidence_ids，会丢掉边的时间字段。[agent.py](../../../../adapters/network/agent.py#L142)

### Inferences
- 这里能说“A 与 B 共享组织 O”，不能仅凭 `A—O—B` 说“A 认识 B、愿意引荐 B”。现有 prompt 已承认这一点，应升级为路径类型约束及返回结构，而不是只依赖模型措辞。
- 现有 cap 可能保留高活跃人而裁掉组织/项目桥梁，导致 distances 说可达但返回子图缺少完整连接。此为代码逻辑推断，尚未构造反例运行验证。
- 对非 owner focus 使用 owner 活跃度硬门槛，可能删掉与 focus 高相关但 owner 很少联系的人；应只用于“我最近联系的联系人”模式或软排序，不作通用扩展硬门槛。
- 逐轮扫描边池的扩展成本约 O(depth × E)，且为每个人重扫 claims/messages，规模扩大时优先建立 person→claims/messages 及 typed adjacency 索引；无需先换图数据库。

### Gaps
- 本研究只读代码，没有跑现有 demo、真实数据、API 或性能测试；上述容量风险不是已经复现的线上故障。
- 当前数据是否存在足够非 owner↔person 的直接交往/引荐证据，需要另查数据分布；算法无法补造缺失社交边。

## 2. Graphiti、HippoRAG、Microsoft GraphRAG 哪些值得借鉴？

### Takeaway
最直接可迁移的是 Graphiti 的“多路召回→图扩展→重排”和 Microsoft 的实体局部上下文思想。HippoRAG 的 Personalized PageRank 可作为复杂多实体问题的候选召回实验，但不能直接当作人际信任、熟悉程度或引荐成功率。

### Cited Findings
- Graphiti 默认 search 将 BM25 与向量相似度结果用 RRF 融合；可按 focal node 距离重排。其可配置搜索区分 nodes、edges、communities，并支持 MMR 与 cross-encoder；距离优先只是相关性启发，不是关系证实。[Graphiti 官方 Searching the Graph](https://help.getzep.com/graphiti/working-with-data/searching)
- 当前主分支源码显示，普通 RRF recipes 使用 BM25+cosine；cross-encoder recipes 的 nodes/edges 还加入 BFS。不能笼统写成“Graphiti 所有默认搜索都执行 BFS”。代码还含 episode 配置，说明概览文档与实现粒度并不完全相同，应固定版本评估。[Graphiti 官方 recipes 源码](https://github.com/getzep/graphiti/blob/main/graphiti_core/search/search_config_recipes.py)
- Microsoft GraphRAG local search 将实体相关结构化图数据与原始非结构化文本结合，面向具体实体问题。[Microsoft Local Search](https://microsoft.github.io/graphrag/query/local_search/)
- Global search 面向整体数据主题：对预生成 community reports 执行 map-reduce，社区层级影响资源用量及回答粒度。[Microsoft Global Search](https://microsoft.github.io/graphrag/query/global_search/)
- HippoRAG 用 query entities 初始化 Personalized PageRank，并加入 node specificity：实体来源 passages 数量的倒数调节 seed 权重。研究评测是 MuSiQue、2WikiMultiHopQA、HotpotQA 各抽取 1,000 验证问题，测文档检索/问答；并未测私人社交引荐。论文错误分析亦指出，PPR 可能因混淆信号及无法直接利用完整查询上下文而选错子图。[HippoRAG 论文 v3，方法、实验、Appendix F](https://arxiv.org/html/2405.14831v3)
- Yen 算法可按正边成本列出 k 条最短路径；k=1 等同 Dijkstra。算法本身只优化定义的成本，并不理解“认识”或“愿意引荐”。[Neo4j 官方 Yen 文档](https://neo4j.com/docs/graph-data-science/current/algorithms/yens/)

### Inferences
- 先以名字/别名、关键词、语义召回实体及原始证据，再对候选实体作 typed bounded expansion；仅扩展有问题相关性的邻居，避免一命中大组织就取全员。
- PPR 借鉴的是由查询 seed 向邻域扩散的相关性。若采用，应在经过时间/审核/类型过滤的局部子图上跑、加入组织枢纽惩罚，并保留原文语义重排；PPR 分数不可显示为“关系强度”。
- Microsoft global search 可留给“我的网络覆盖哪些主题、长期缺什么资源”等明确整体问题；人物详情、项目跟进、找可询问联系人优先局部检索。
- 不建议为此 demo 立即迁移完整 Graphiti/HippoRAG/GraphRAG；先实现其可验证的小模块，避免把索引、抽取、图数据库和检索策略一起更换而无法归因。

### Gaps
- 所引官方文档证明机制，不证明它们在此合成网络优于当前实现。HippoRAG 的公开多跳 QA 结果不能换算为私人通信检索提升或引荐成功率。
- 未找到直接适用于此数据、已校准的组织 degree 惩罚系数、关系衰减半衰期或引荐权重；这些应作为本产品假设并经样例验证。

## 3. 如何优化 expand、人物/组织/项目视图和“谁能介绍谁”？

### Takeaway
建立两种不同图语义：保留“上下文关联图”供探索；从有明确证据的 person↔person 联系构建“可询问的引荐候选图”。先保证每条结果的路径与证据完整，再谈更复杂的排名模型。

### Cited Findings
- 当前 shared contexts、activity coverage 与 agent 提示已区分沟通、共享组织、实际能力和工作交付，适合保留为稳定语义边界。[context.py](../../../../adapters/network/context.py#L40)；[agent.py](../../../../adapters/network/agent.py#L284)
- Graphiti 展示了图距离重排与语义/关键词召回可以组合；Yen 提供可审计的多路径成本排序，但两者均未声称能从共组织关系证明引荐。[Graphiti 官方文档](https://help.getzep.com/graphiti/working-with-data/searching)；[Neo4j Yen](https://neo4j.com/docs/graph-data-science/current/algorithms/yens/)

### Inferences
以下均为针对现有 repo 的设计建议，不是来源论文已经验证的社交模型。

1. **分离 UI snapshot 与 RetrievalResult。** UI 保留 50/100 cap；检索单独设置 candidate/edge/evidence/token 预算。每个结果返回命中原因、完整 ordered path、每条边 relation/status/validity/evidence_ids、截断原因及 coverage。返回前做 path closure：保留结果就保留其必要桥梁与证据，否则不将它包装成完整路径。
2. **索引后再扩展。** 建 typed adjacency、entity→claims、claim→evidence、person/project→work；按 as_of/version/cache key 复用计算。真正 queue/frontier BFS 用于 UI；query-aware beam expansion 用于问答，保留 1–3 跳上限，每个 organization/project 的邻居按问题相关性给额度，大组织默认折叠和分页。
3. **软排序分开度量。** 检索分数可组合 query relevance、evidence quality、time relevance、focus distance、diversity；owner communication activity 独立展示，只在联系优先级中小幅加权。组织 hub 惩罚可用 log(1+degree) 一类启发，但不能因 degree 小就断言关系更真。
4. **按视图定义允许边。** 人物详情：个人事实、直接交往、工作记录、按类型分组的项目/组织；组织详情：成员与任期、项目、成员的有来源工作事实；项目详情：职责、交付、待办、时间线。明确是否需 history 模式，并将查询设置显式传给 entity_context，避免静默重置。
5. **分三类路径。** (a) topology shortest path：最少跳，只作位置解释；(b) evidence-supported person path：各 person-person 边有可见证据，可列为“可询问的联系链”；(c) co-membership path：仅“共同背景”，必须单列，不能混入“已证实认识的人”。person-project-person 也不自动证明合作，要看是否有共同工作/直接交流证据。
6. **引荐检索规则先于权重。** 起点允许 owner，内部禁止回穿 owner；只允许任务规定的 person-person 关系，禁止把 org/project 当人际跳板；待审核、不在目标时间有效的边先排除。直接联系、明确提及认识/合作、实际引荐等需有各自类型及证据，不将提及名字当认识。
7. **路径打分可从简单规则开始。** 若边支持强度 s∈(0,1] 只是内部排序特征，可设成本 `ε - log(s)`，加 hop/过时惩罚；用 Dijkstra/Yen 返回 top 3 候选，再按共同中间人的重复度去重。未经校准，s 和路径乘积不能称为成功概率；强度本身也不能仅由消息量定义。小图深度≤3时，受约束枚举+排序更易调试。
8. **完整路径证据打包。** 不再将全部证据按 ID 取前 40。优先按问题相关性选完整的 claim+support bundle，给每条候选路径保底全部边证据，再去重和压缩；超预算返回部分检索标志。答案可说“记录支持 A 与 B 有合作，可先询问 A 是否愿意引荐”，不能说“一定能引荐”。
9. **递进验证。** 第一阶段只改 typed adjacency、完整路径保全、时间字段和 context 参数传播；第二阶段加入 BM25/语义候选+有界扩展+重排；第三阶段以离线消融比较 PPR。测试集含大组织假捷径、真实桥梁被截断、同名人、过期任职、时间旅行、稀疏联系、多语言别名和无答案。分别量 path validity、all-edge evidence coverage、错误 acquaintance 率、相关证据 recall@budget、截断后连通性、P95 延时；无需以生成答案的流畅程度代替检索质量。

### Gaps
- 数据只有 owner↔contact 沟通时，不足以推出 contact↔contact 社交关系。此时应返回“可询问联系人及缺失证据”，而不是通过组织边补齐看似完整的引荐链。
- 引荐意愿、介绍渠道、当前可联系性无法由历史交流次数可靠推出，需独立字段或实际确认；本次没有执行联系行为。
