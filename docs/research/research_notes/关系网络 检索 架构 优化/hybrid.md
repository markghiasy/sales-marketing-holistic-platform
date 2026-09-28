# 关系网络的混合检索与重排

## 1. 现有召回为什么会漏掉目标相关的人与证据？

### Takeaway
当前是受限规则解析和 LLM 生成检索计划，底层 people 工具仍是标签/姓名字面 OR 匹配。优先修复“搜什么材料、怎样按相关性截断”，再决定是否加入 embedding；增加模型不能补出不存在的专业能力证据。

### Cited Findings
- `search.py:83` 的 quick search 使用 regex 别名和动态实体名；未消费的词导致澄清，require 为硬条件、prefer 影响排序。搜索标签来自时间范围内 confirmed assertions。它没有 BM25、向量或神经重排。[本地 search.py](C:/Users/Eva%20Ng/Desktop/ironman/network-demo-worktree/adapters/network/search.py)
- `agent.py:142` 的 people 分支只搜索姓名和 sourced tags，`any(term in text)` 为字面 OR；沿 `ranked_contacts` 顺序取 `matches[:12]`。后续 evidence 先按 ID 排序，再取 40 条。LLM 会用 catalog 规划最多四次 lookup，但没有根据第一次检索结果继续规划的循环。[本地 agent.py](C:/Users/Eva%20Ng/Desktop/ironman/network-demo-worktree/adapters/network/agent.py)
- Sentence Transformers 的官方说明：词法匹配不识别同义词等语义变化；bi-encoder 可做语义召回；cross-encoder 同时读取 query 与候选文档进行相关性重排。语料很小时，可以省略初步召回，直接对所有段落重排。[Sentence Transformers](https://sbert.net/examples/sentence_transformer/applications/retrieve_rerank/README.html)

### Inferences
- **建议，尚未测量收益**：目前 24 位联系人规模，可对全部合格 person cards 或证据做查询相关性评分，再选择 context。先取消“按活动排序取 12 位”和“按 ID 取 40 条”对相关性造成的偏置；活动仅在同等相关性时作次级排序。
- person card 可由姓名、confirmed tags、实际项目/交付记录和少量原文证据组成；每个字段保留 claim/evidence ID、时间、来源。同时保留 evidence-level 索引，避免只对“Engineering”这种宽标签搜索。
- Cybertest 可拆为“AI agent / 软件安全与对抗测试 / 测试工程 / 产品试点 / 潜在引荐”子问题，分别保留命中证据。Engineering 是相邻职能线索，不能改写为“已证实具有 AI 红队能力”；“可能值得问”属于建议，不能混入事实。
- 必須/排除/时间条件应先用确定性过滤执行；模型的相关性评分不应覆盖这些约束。索引是候选发现层，原始事实仍由现有证据引用与实体绑定机制验证。

### Gaps
- 未运行 live API 或评测，不能断言哪位联系人最合适，也不能报告实际召回提升；24 人规模来自本次任务背景。
- 未测量全文 evidence 的 token 总量、重复度或 CPU 推理耗时，因此“全部送模型”和“本地 cross-encoder”的延迟取舍还需离线基准。

## 2. 扩展到数千人时，什么混合检索结构值得采用？

### Takeaway
推荐候选架构是“硬过滤 → 实体与原文证据双路 BM25/多语言 dense → RRF 合并 → 重排 → 受限图扩展 → 证据包”。现在可先做可插拔检索接口和简单词法基线，不需要为了使用 RRF 部署 Elasticsearch 或更换图数据库。

### Cited Findings
- RRF 使用各路排名而非直接相加原始分数：`sum(1 / (k + rank))`；Elastic 官方文档默认 `k=60`，说明 rank window 会影响结果及性能。这是可自行实现的融合公式，并不意味着必须采用 Elastic 产品。[Elastic RRF](https://www.elastic.co/docs/reference/elasticsearch/rest-apis/reciprocal-rank-fusion)
- Anthropic Contextual Retrieval 在索引前给 chunk 添加约 50–100 token 的上下文，再构建 embedding/BM25；其自有多个文档域实验中，结合重排将 top-20 检索失败率从 5.7% 降至 1.9%，是相对下降 67%，不是准确率增加 67 个百分点，也不是本项目的预期收益。[Anthropic](https://www.anthropic.com/engineering/contextual-retrieval)
- Graphiti 官方 `COMBINED_HYBRID_SEARCH_RRF` 对 nodes、edges、communities 使用 BM25+cosine+RRF，episodes 在该 recipe 中只有 BM25；cross-encoder recipe 的 nodes/edges 还加入 BFS。说明图、词法、语义可以组合，也说明“Graphiti 所有类型都同时向量搜索”不准确。[Graphiti 官方源码](https://raw.githubusercontent.com/getzep/graphiti/main/graphiti_core/search/search_config_recipes.py)

### Inferences
- **工程建议**：建立两种检索单元：实体卡回答“谁/哪个项目”，原文证据回答“凭什么”。先分别召回，再以稳定 ID 去重与合并；从证据映射回实体，避免直接混合不同类型的裸分数。
- dense 适合“对抗测试 ↔ adversarial evaluation”等跨语言/近义表达；BM25 保留姓名、产品名、缩写、精确技术词的检索能力。`Cybertest` 这类新项目名不应要求出现在旧记录里才能找到相邻经验。
- 初始调参可以每路取几十个候选、融合后重排、按 token 预算选择证据；具体 k、窗口和最终数量必须通过本库评测确定，不照搬 Anthropic 的 150→20。
- 对短证据优先使用确定性上下文前缀：人物、组织/项目、时间、事实类型。它能借鉴 contextual retrieval 的“恢复上下文”思想，先不增加 LLM 批量生成成本；禁止在前缀补写未经证实的能力。
- 搜到相关实体后，再扩展 1–2 hop 寻找共同项目和真实关系证据。路径用于解释接近方式；共同组织、共同项目及 owner hub 都不能自动证明认识或可成功引荐。不要把图距离直接当专业匹配分。
- relevance、证据直接性、来源/日期、关系路径应分栏展示。RRF/cross-encoder 分数是检索信号，不是“此人确实具备能力”的概率。

### Gaps
- 这些来源没有证明本项目需要 Graphiti、ANN 或独立搜索集群；当前无需因架构名称而迁移。
- 未在本库比较 BM25-only、dense-only、hybrid、hybrid+rerank；不能承诺复杂管线一定优于全部候选直接评分。

## 3. 多语言、模型提供商与最小落地顺序是什么？

### Takeaway
第一阶段直接改进候选材料、相关性排序和评测；第二阶段按实测加入多语言 embedding。现有 Claude API 不等于已有 embedding 服务，选择云 API 或本地模型要显式处理依赖与缓存。

### Cited Findings
- Claude 官方文档明确 Anthropic 没有自有 embedding 模型，介绍 Voyage 作为一个提供商，并要求按实际场景评估供应商；因此现有 `ANTHROPIC_API_KEY` 不能假定能直接调用 embedding。[Claude embeddings](https://platform.claude.com/docs/en/build-with-claude/embeddings)
- BAAI 官方 BGE-M3 模型卡说明其支持 100 多种语言、dense/sparse/multi-vector，提供本地 FlagEmbedding 使用示例；输出 dense 向量为 1024 维。它是本地多语言实验候选，不是本任务已验证的最佳模型。[BAAI 模型卡](https://huggingface.co/BAAI/bge-m3)

### Inferences
- **阶段 A，最低复杂度**：保持现有数据和 graph/context 语义；建立 evidence-backed cards；24 人全部进入相关性评估；最终 40 条证据按子问题覆盖、相关性和去重选择。可先用已有 LLM 对全部精简 cards 做结构化选择，也可离线对比 cross-encoder。明确这是新的推理开销或更大 prompt，需要测量。
- **阶段 B，规模或实测漏召回需要时**：本地 BM25 加缓存 embedding，RRF 融合。数千个短卡片可以先用矩阵余弦全扫作基线，量出瓶颈再引入 ANN；实际规模应按证据条数/token 计，而非只数人。
- 云端方案需要独立 embedding provider 配置与 SDK；本地 BGE-M3 避免运行时外部 embedding 请求，但增加模型下载、推理库及内存要求。默认模型选型不应仅凭通用榜单；不在此次研究擅自安装模型或使用密钥。
- 中文 query 对英文 tags 应测试原始中文、规范化英文扩展和中英混合三组。词法索引需明确中文分词/字符策略；dense 模型要评估跨语言，不要沿用英文专用 encoder。扩展词只扩大召回，不写回 confirmed tags。
- 最少建立 20–30 条人工标注查询，覆盖 Cybertest 目标任务、姓名、精确标签、中文/英文同义表达、无证据能力、过期/未确认记录和引荐问题。按 person recall@k、evidence recall@k、nDCG、无证据能力断言、引用正确性、延迟/token 开销比较基线。
- 验收重点：能找回“值得进一步问的人”和其实际记录，同时明确专业能力未知；“没搜到证据”不变成“人脉里没有此能力”。保留现有 source ID 校验与引用原文展示。

### Gaps
- 没有供应商价格或本机资源实测，本笔记不指定价格、预计毫秒数、最佳 embedding/reranker 型号。
- 代码/网页核对日期为 2026-09-28；Graphiti 链接是 main 分支，真正实现前应固定版本再核对接口。
