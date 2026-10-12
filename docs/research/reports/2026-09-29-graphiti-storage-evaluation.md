# Graphiti / Neo4j / Postgres：本地评估结果

日期：2026-09-29。状态：隔离技术试验完成；未实现或切换生产。所有测试数据为虚构数据。

## 1. 决策：修正此前“优先 Graphiti + Neo4j”的建议

**现阶段优先实现带索引、可增量更新的关系型知识存储；不把 Graphiti 0.30.2 或 Neo4j 作为首轮真实数据上线的必需依赖。** Postgres 是本轮实测支持的候选。Graphiti 保留为可替换的实验适配器，等证据撤回、审核过滤、身份映射和回放契约通过后再考虑接管核心。

这不是认定图数据库普遍比关系数据库慢。我们测的是当前产品需要的有界查询，在本机配置与模拟拓扑下，Postgres 已有足够快的存储层结果；增加图数据库没有显示出抵消部署与同步成本的必要收益。框架能否正确处理我们的知识更新政策，比名称是否叫 knowledge graph 更重要。

**产品图谱与存储引擎是两个选择。** 四层关系、Obsidian 风格可视化、能力/商业画像、项目视图、介绍路径和战略组网仍然保留。它们不要求存储必须是 Neo4j。四层关系是证据分类，不能换算成一至四跳。

## 2. 实际做了哪些实验

| 项目 | 范围 |
|---|---|
| 存储对比 | PostgreSQL 16.15 与 Neo4j 5.26.31；两个新建 Docker 容器，均限制 2 CPU、1.5 GiB，端口仅绑定 127.0.0.1 |
| 数据 | 固定随机种子 7410；1,000 人 / 1,120 实体 / 6,130 关系；10,000 人 / 11,200 实体 / 61,425 关系 |
| 拓扑 | 人际关系、项目、组织；约三分之一人员共享同一组织，含 pending、旧职位、晚到修正和未来获知记录 |
| 正确性 | 两库每一次计时结果均与独立 Python 邻接遍历 oracle 比较，按 ID 排序最多返回 50 个相同候选 |
| 模型试验 | Graphiti 0.30.2 + 与现有应用相同的 Anthropic SDK 0.125.0；固定 Claude Haiku 4.5 dated model；三条虚构消息 |
| 更新契约 | SDK 实际写入多来源事实，再实际删除第一/第二条来源；测试摘要、残留引用、审核过滤、日期过滤、新 episode ID |
| demo 搜索 | 复用现有 `NetworkRetrieval`，对 10,000 人生成证据/画像，测缓存后扫描及每问重建；另测物化技能字段的索引候选查询 |

Neo4j heap 上限 512 MiB、page cache 256 MiB；Postgres 使用容器默认配置加工作负载所需索引。数据库有相同资源上限，但没有穷尽调参或压满相同内存。Neo4j 使用通用 `E` 关系类型加 kind 属性，接近通用事实边方案；未对专用关系类型、APOC、专用图算法库做调优。数据不是 Mark 的真实图，未测并发、冷启动、远端网络、故障恢复或整套 API/UI/LLM 延迟。

## 3. 有界关系查询的实测

最终确认轮在其他本次评估任务结束后运行，10,000 人；每种查询预热 30 次，再交替执行两库各 60 次。下表是客户端完整取回候选 ID 的耗时，单位 ms；不是仅数据库内部执行时间。

| 查询 | Postgres P50 / P95 | Neo4j P50 / P95 |
|---|---:|---:|
| 明确人际联系 | 2.27 / 3.96 | 6.48 / 8.80 |
| 共享项目 | 2.34 / 3.02 | 8.83 / 10.34 |
| 共享组织，含大组织 | 2.66 / 29.47 | 9.81 / 52.50 |
| 三跳内经明确联系找到 cybersecurity 候选 | 3.85 / 5.33 | 8.06 / 9.69 |
| 较早获知时间的共享组织视图 | 2.45 / 20.43 | 8.35 / 36.22 |

最终轮共 **600 次结果集合核对，全部一致**。初轮两个规模另有 600 次一致核对。中间确认轮与很小的 Graphiti 试验有时间重叠，因此不以其中延迟作为主结论；已单独保留该轮文件。初轮 Neo4j 首个查询有显著预热效应，不能拿它的 73 ms P50 当稳定性能。

两库的自定义 upsert 均通过“同一批 100 条更新重复两次，关系数量不增长”。这仅验证 probe 的 UPSERT/MERGE，不证明 Graphiti `add_episode` 幂等，也不证明正式增量 worker 的恢复正确。最终轮 Postgres 两批各约 23–24 ms，Neo4j 约 101/20 ms，样本不足以形成写入吞吐结论。

大组织的尾延迟值得关注：应先筛组织/时间/关系类型，限制结果和扩展预算，按需展开；不要把同公司的人两两物化成“认识”边。两边均需要这些产品约束。

原始记录含完整 SQL EXPLAIN、Cypher PROFILE、版本、计数与结果检查：

- [最终确认轮](../network-demo/graph-storage-warm-final.json)
- [初轮两个规模](../network-demo/graph-storage-benchmark.json)
- [中间轮，非主性能依据](../network-demo/graph-storage-warm-confirmation.json)
- [可复现脚本](../../../scripts/research/graph_storage_eval.py)

## 4. 现在 demo 的慢点：重复构建和全文扫描

现有 `NetworkAgent.answer` 每次问答构建一次 `NetworkRetrieval`；同一次问答内会复用它。该结构会构造全量记录、证据文本与邻接，再在 `people()` 中扫描人员相关文本并反复分词。它不是 Postgres 检索，也不是已建立的 BM25/向量索引。

在 10,000 人的合成证据集合中，精确单词 `cybersecurity` 查询，8 次测量的中位数：

| 路径 | P50 |
|---|---:|
| demo 已构建对象后扫描 | 763 ms |
| demo 构建对象加扫描 | 2,517 ms |
| Postgres 已物化技能字段的 GIN 全文候选查询 | 2.01 ms |
| Neo4j 已物化技能字段的全文候选查询 | 16.48 ms |

**这些管线承担的工作不同，不能宣称换数据库就端到端快了 1,000 倍。** demo 处理完整证据记录并先找所有匹配；索引实验提前物化技能，仅取 50 个候选 ID。它说明“入库时建立可增量维护的索引、问答时只查候选”的方向值得实施。正式索引必须由相同审核/时间/来源政策生成，命中后再批量获取所需证据；这里没有测试完整证据回填、策略回答、中文分词、同义词或多条件排序。

原始结果：[lexical benchmark](../network-demo/network-lexical-benchmark.json)。Postgres 这次用的是内置 `tsvector + GIN`，**不是 BM25**。[官方索引文档](https://www.postgresql.org/docs/16/textsearch-indexes.html)

## 5. Graphiti：有价值，但几个核心契约没通过

固定版本源码和测试相互印证，不能把以下问题归咎于 embedding 模型，因为删除与属性过滤的 probe 不依赖模型判断。

| 业务契约 | 实测结果 | 对我们产品的影响 |
|---|---|---|
| E1、E2 同时支持事实 F，删除 E1 后保留 F | **未通过**：E2 仍存在，F 被删除 | 有效标签/关系可能误消失 |
| 删除 E2 后，F 只引用 E1 | **未通过**：F 保留但还引用已删除 E2 | “查看依据”失效，来源回收不完整 |
| 删除 E1 后，摘要移除只有 E1 支持的细节 | **未通过**：存活人物摘要保持旧内容 | 图、标签、summary、strategy context 可能不一致 |
| 设置属性过滤 `review_state=confirmed` 后排除 pending | **未通过**：Neo4j BM25 路径仍返回 pending | 不可直接把默认结果作为正式能力/关系推荐 |
| 显式限定 edge UUID 白名单 | 通过这个小样本 | 可作为适配手段，仍须防止其他检索通道绕过 |
| 显式 `invalid_at IS NULL` | 通过这个小样本 | 默认搜索仍返回已结束事实，需要主动设置时间政策；此条件也不等于完整 as-of 逻辑 |
| 新外部 episode UUID 可直接当幂等插入键 | **不支持这种用法**：返回 NodeNotFoundError | 需要我们自己的 source-version→episode 映射和重放协议 |

删除测试先使用 SDK 正常保存一个多来源事实状态，再调用真实 `remove_episode`；这是确定性的存储契约测试，不是端到端抽取质量测试。属性过滤使用 BM25-only + RRF，同时验证默认能检出全部三条、UUID 白名单能只返回一条，防止把“没搜到”误判成过滤成功。

- [删除和模型试验结果](../network-demo/graphiti-acceptance-probe.json)
- [过滤和 UUID probe](../network-demo/graphiti-policy-probe.json)
- [固定 release 的源码审计](../research_notes/2026-09-29-graphiti-v0302-adoption-audit.md)
- [官方 remove_episode 实现](https://github.com/getzep/graphiti/blob/v0.30.2/graphiti_core/graphiti.py#L1824-L1852)
- [官方 SearchFilters 实现](https://github.com/getzep/graphiti/blob/v0.30.2/graphiti_core/search/search_filters.py)

这里的“未通过”对应我们的产品接受标准，不表示 Graphiti 所有场景不可用。修补/适配是可能的，但原本希望节省的工程量需重新计算。

## 6. 实际接通 Claude 的有限结果

模型为 `claude-haiku-4-5-20251001`，三条虚构消息依次表达：一月在 Cedar Labs 工作；二月离开并加入 Birch Security；最后补录一月的旧消息。Graphiti 在本次运行中保留了已结束的 Cedar 关系和当前 Birch 关系；补录没有把旧工作重新变成当前工作。

三条消息分别耗时约 **7.02、8.13、4.36 秒**；总计 **9 次模型调用、17,608 input tokens、1,007 output tokens**。只记录实际 usage，没有把这三个短句按比例推算全量导入费用或生产吞吐量。

为避免引入未选择的外部 provider，本次明确传入了 token-hash embedding 和禁止调用的 reranker；没有向 OpenAI 发送请求，Graphiti telemetry 关闭。**Hash embedding 是连接和状态试验的替身，不是生产 embedding；本次不能评价语义召回质量。** Anthropic SDK 已在隔离 venv 固定到应用现用 0.125.0，但没有将 Graphiti 安装进生产 venv。

源码还显示：基础 search 默认 RRF，而高级 search 默认可能调用逐条 passage 的模型 reranker；当前 Neo4j cosine 查询路径也不能直接等同 ANN 索引检索。不能假定采用 Graphiti 就自然解决搜索慢。[固定版本审计与源码链接](../research_notes/2026-09-29-graphiti-v0302-adoption-audit.md)

## 7. 建议落地顺序

1. **先建立持久化的知识变更账本**：source/version、canonical identity、assertion、support、review、有效时间与获知时间、发布版本。更正、撤回和身份合并触发有范围的依赖失效；重放不重复付费抽取。
2. **把检索准备工作移到增量 worker**：联系人画像文档、证据倒排索引、关系邻接索引按受影响实体更新。图与正式标签共享同版有效断言，summary/context 后台更新并独立标明覆盖版本。
3. **以索引候选检索起步**：名字/实体匹配、词法召回、有界 SQL 关系扩展，再按业务条件排序并回填证据。语义检索可单独评估 pgvector/HNSW、RRF 和小候选集 reranker；本轮未测试这些，不把它们写成已经达标。[pgvector 官方实现](https://github.com/pgvector/pgvector)
4. **保留可替换接口**：Graphiti 只能通过 extraction/retrieval adapter 接入。通过删除、审核、身份、恢复 gates 后，按实际维护收益决定使用范围；不先 fork 大量内部代码。
5. **真实数据候选验证再上线**：对最小授权样本检查来源和主体、检索召回/排序、中文语义、source lag、撤回残留、图与标签一致性及问答引用。由于本轮已有接受门槛失败，没有继续导入 300–500 条真实消息来制造成本和待修状态。

现有设计/计划原先选择了“只读来源 Postgres → 本地 SQLite 派生存储”。本轮**没有比较 SQLite**，因此不能据此宣称它胜过或不如 Postgres。新的证据支持采用关系型路线，并提供了本地 Postgres 的可行基线；正式实施前需统一计划中的派生存储选择。若使用本地 Postgres，应建立独立候选库，不能把这里的本地延迟直接套到可能位于远端的源库，更不能在未核实运行配置时写生产表。

## 8. 复现与环境

试验代码均在 `scripts/research/`，标为 throwaway；未修改 `adapters/` 或 frontend。现有用户的 network.css 改动保持原样。JSON 只含虚构数据或聚合指标，无真实正文/凭证。

- [Python 依赖快照](../network-demo/graph-eval-requirements.txt)
- PostgreSQL 镜像 ID：`sha256:f1c3376c26f2609ab9f29f71f824103fe2fcd8ee0346485cb6122a4f93df6f94`
- Neo4j 镜像 ID：`sha256:5eb12ad77fa46ab73e23df9ea1f43f5c0f2a79523435577648e046be042b9b93`
- 临时容器：`codex-network-eval-pg-20260929`（55448）、`codex-network-eval-neo4j-20260929`（57688）。结束后停止，保留可复现数据；不碰已有服务。
- 资源单次观测：Postgres 约 53.7 MiB，Neo4j 约 754.4 MiB。这是本次启动配置和工作负载后的快照，非最低资源要求或普适效率结论。

从 worktree 根目录、两个隔离容器运行时：

```powershell
& '.\.tmp\graph-storage-eval-venv\Scripts\python.exe' scripts/research/graph_storage_eval.py --people 1000 10000 --repetitions 30
& '.\.tmp\graph-storage-eval-venv\Scripts\python.exe' scripts/research/graph_storage_eval.py --people 10000 --repetitions 60 --warmups 30 --reuse --output graph-storage-warm-final.json
& '.\.tmp\graph-storage-eval-venv\Scripts\python.exe' scripts/research/network_lexical_eval.py
& '.\.tmp\graph-storage-eval-venv\Scripts\python.exe' scripts/research/graphiti_acceptance_probe.py
& '.\.tmp\graph-storage-eval-venv\Scripts\python.exe' scripts/research/graphiti_policy_probe.py
```

第一次运行 acceptance probe 会建立 Graphiti 索引；policy probe 依赖这些索引。加 `--live` 才会运行有预算限制的三条模拟消息 Claude 试验；默认不调用模型。acceptance JSON 会被重跑覆盖，应保留原始已发布记录或另外保存结果。脚本仅适用于这些隔离端口，不支持传入生产 DSN。

首次 SDK fixture 保存缺少 embedding 被 Neo4j 拒绝，补齐 probe 所需 embedding 后才进行有效契约测试；首次索引创建也出现 equivalent-index 警告。它们不是本报告的业务失败证据。最终结论依据成功构建 fixture 后的实际状态和对照查询。
