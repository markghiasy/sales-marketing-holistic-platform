# 小论文定位与导师沟通边界

2026-09-30 更新：当前导师讨论材料以 [新版英文摘要](abstract-for-supervisor.md) 和 [研究方案](research-protocol.md) 为准。题目统一为 *Evidence-Grounded Multi-Requirement Retrieval in Professional Networks*；以下保留选题历史和贡献边界。

2026-09-29。当前最紧急交付是导师要求的 abstract。长期目标是形成期刊论文，支持后续博士申请；没有指定期刊、截止日期或录用承诺。

## 当前可发送的产物

[英文研究计划摘要及邮件正文](abstract-for-supervisor.md)。只复制标题和摘要即可；末尾状态说明用于明确研究阶段。收到导师意见后再决定目标刊物与完整实验规模。

现有 [temporal relationship memory 讨论稿](../temporal-relationship-memory/paper.md) 可复用问题背景、证据/时间模型和系统图。它含早期 demo 状态及有限的构造案例，不能原样当作新检索方法的结果。新稿暂不覆盖所有产品功能、全量生产迁移或知识抽取算法。

## 一个研究问题

在相同的候选检索、证据资格规则与计算预算下，依据尚未得到证据支持的目标方面动态分配图扩展预算，能否比固定扩展、最终结果多样化和覆盖成本方法，获得更完整的有证据子图？

技术、行业、商业资源是例子，不是仅有的方面。输出是可用于决策的候选子图与依据，不声称真实世界一定具备所推断能力，也不承诺组出的团队会成功。

## 必须处理的既有研究

**2026-09-30 补充：** [框架 v0.1](search-framework.md) 与 [新核查笔记](../../research/research_notes/2026-09-30-adaptive-search-related-work.md) 加入 ARK、ToG-2、GraphSearch 等更接近的方法。它们已经有自适应探索或缺失证据反馈。因此下述候选区别不能仅靠对比固定扩展、xQuAD 和一次性 PPR 来成立，正式评估必须包含强自适应检索对照。

1. xQuAD 已有逐步更新方面覆盖的机制，不能声称“想到未满足方面”本身是创新。[Santos et al., ECIR 2010](https://doi.org/10.1007/978-3-642-12275-0_11)
2. 社交网络团队形成已有技能覆盖与通信成本的联合选择，也包括新增覆盖/成本的贪心方法。[Lappas et al., KDD 2009，作者提供全文](https://cs-people.bu.edu/evimaria/cs591/lappas09finding.pdf)
3. CatRAG 使用查询相关的动态边权；其 v1 在遍历前作一次调整。我们拟研究搜索过程中残余需求如何影响探索预算，但这只是候选区别，尚未完成全面新颖性核实。[CatRAG v1](https://arxiv.org/html/2602.01965v1)

进一步对照细节见 [novelty boundary note](../../research/research_notes/2026-09-29-short-paper-novelty-boundary.md)。摘要没有使用 first、novel、state-of-the-art 或优于现有方法的结果性表述。

## 最小实验边界

- 第一阶段使用人工确认的 query aspects，所有方法共享它们，避免把更好的 LLM query parsing 当作检索算法收益。
- 固定图快照、有效证据与审核过滤。基线也必须获得同样的证据约束，不能人为允许其读取失效信息后宣称新方法更可靠。
- 比较 hybrid candidate retrieval、fixed expansion、aspect-diversified reranking、coverage-cost team selection；动态方法消融为固定权重和仅最终 reranking。
- 固定输出预算并记录实际搜索开销，包含候选取得、看过的关系、证据回填及模型调用。缓存、预计算和桥接路径查找不能隐藏成本。
- 检索质量优先于最终 LLM 文风：方面覆盖、完整支持路径、无依据推荐、未找到时的明确不足、延迟与成本。
- 开发与测试按场景/图/查询模板分组隔离；先固定规则与测试集，再看结果，不能用几道为本方法特制的问题证明优越。
- 合成场景可验证机制和边界，不能代替商业有效性；期刊级评估范围与是否加入真实数据案例由导师反馈后确定。

## 已有证据可以支持什么

已经有可运行的网络 demo、证据模型、存储层计时和 Graphiti 小样本接受测试。它们支持“该研究有工程基础且某些集成契约需要显式处理”。它们不支持“动态多方面检索优于基线”“真实商业价值已验证”或“数据库选型决定了搜索质量”。

先把摘要送到导师手上，确认研究问题、最接近的相关工作和可接受的评估范围；再实现最小检索机制和对照实验。期刊定位及博士申请安排需分别确认，不能将尚未完成的论文当作已经发表的申请成果。
