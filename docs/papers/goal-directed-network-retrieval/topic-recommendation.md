# Ironman 第一篇论文：选题建议

2026-09-30。选题判断，尚非已验证的贡献或期刊录用预测。以 Eva 希望尽快形成第一篇论文、现有产品资产和可控制的实验范围为依据；导师方向和可用于研究的数据范围仍会影响最终选择。

## 推荐题目

**Evidence-Grounded Multi-Requirement Retrieval in Professional Networks**  
面向商业目标的证据约束多需求人脉检索。

Ironman 的研究主线可以是“如何把分散、变化、不完整的通信记录变成可核查的决策依据”。第一篇只研究其中的检索任务：给定多条件目标和固定知识快照，找出互补的候选人/组织及支持证据，区分已支持、仅线索和预算内未解决的需求。

核心问题：**在同样的数据、证据资格和资源上限下，显式需求状态驱动的检索，能否提高最终有证据支持的需求覆盖，同时控制无依据推荐和检索成本？**

这是应用信息检索/系统实证定位。新搜索策略是待测变量；暂不以“发明新的 HNSW”或“首个战略人脉算法”定位。

## 候选方向比较

| 方向 | 已有资产 | 主要缺口 | 本次判断 |
|---|---|---|---|
| 目标导向、有证据的多需求检索 | synthetic demo、断言/来源、需求拆解、覆盖打包、图展示 | 独立任务集、可靠支持标注、强检索基线、正式实验 | 第一选择：与产品价值直接相连，能冻结输入控制范围 |
| 纠错后的人脉记忆一致性 | 可逆身份 merge、时态断言、Graphiti 小样本契约失败 | 跨标签/摘要/索引的纠错传播未实现；与时态数据库、provenance、agent memory 区分 | 第二选择：问题清楚，但实现和新颖性审计工作仍大 |
| 人工审核下的跨渠道身份消歧 | 真实产品实现、Mark 曾盲评候选、质量门槛与审计 | 新方法与强对照、独立 holdout、召回/漏合并评估、多账户适用性 | 工业证据最具体之一；当前修复尚不足以形成方法论文 |
| 项目活动和跟进决策支持 | 项目视图、职责与交付记录模型 | 长期可靠标注、真实任务使用、绩效含义澄清 | 可作后续用户/组织研究，当前准备度较低 |
| 通用新图搜索算法 | 搜索框架设计与理论动机 | 算法新颖性、广泛基准、复杂度/性能分析 | 暂不作为第一篇的承诺 |
| 全平台架构介绍、图视觉设计、连接器或数据库跑分 | 工程产物较多 | 单独研究问题与可推广证据不足 | 作为背景或基础设施，避免一篇涵盖全部功能 |

这个排序是有条件的判断。如果能取得多账户身份标注、导师专长是 entity resolution，第三项可能更合适；如果导师专长是数据库和 provenance，第二项可能更合适。可接触客户数据不自动等于可公开或用于人体研究。

## 为什么已有框架不阻止这个选题

[Expert finding](https://krisztianbalog.com/files/sigir2006-expertsearch.pdf)、[team formation](https://cs-people.bu.edu/evimaria/cs591/lappas09finding.pdf)、[ARK](https://arxiv.org/abs/2601.13969) 已有很强相关工作。论文不能靠“把 KG 用到人脉”建立新颖性。我们需要测量多需求覆盖、来源支持和缺口表达在明确条件下的效果，并与强方法比较。研究也可能得出简单方案已经足够的结论。

纠错路线也不是无人做：[Zep](https://arxiv.org/abs/2501.13956) 已有时态图记忆；[RECON 预印本](https://arxiv.org/abs/2607.16716) 涉及级联失效与独立支持；[Forgetting Without Restarting 预印本](https://arxiv.org/abs/2609.04875) 涉及跨派生产物的 provenance/replay。修复特定版本的 Graphiti 行为不自动构成普遍研究贡献。

## 最小论文边界

1. 用固定图快照和人工确认的查询需求隔离检索问题；身份解析、抽取、实时更新暂作上游，不同时宣称改进。
2. 设置人员/组织的多条件检索任务，保留“同一人满足多个条件”与“不同人分别覆盖”的差别。暂不评价团队成功、签约或收入。
3. 比较 hybrid retrieval、固定展开、多样化结果选择，以及至少一个自适应 agent；所有主方法共享来源、时间和资格规则。
4. 用相同上下文输出上限及可比读取/模型预算，评估有支持的覆盖、推荐断言精确率、未知误判、端到端耗时和成本。拒答增多不能单独算成功。
5. 在可控制的证据缺失/噪声条件下分析失败；人工屏蔽只是压力测试，不代表现实缺失分布，需真实任务补充。
6. 先做机制诊断，再做按场景隔离的独立评测。若开展用户研究，单个 Mark 的满意度不能支持普遍效率或商业收益结论。

可能的贡献是任务/评测设计、可解释的检索策略和适用边界；三者均须与前人工作区分并由结果支持，不能仅列出三个模块就称三项创新。

现有 [搜索框架](search-framework.md) 与 [摘要](abstract-for-supervisor.md) 可以沿用此方向，不需另起整套系统。旧 temporal relationship memory 稿件可提供背景材料，但其中 Graphiti 未执行等状态已过时，七个构造案例不能改名成为正式实验。

相关候选题目核查见 [研究笔记](../../research/research_notes/2026-09-30-ironman-paper-topic-options.md)。本次未实现方法、运行新实验、更改生产或发送材料给导师/Mark。

## 导师方向补充：Damminda Alahakoon

Eva 于 2026-09-30 提供 [La Trobe 官方主页](https://scholars.latrobe.edu.au/dalahakoon)，确认这是她的导师。主页列出 AI/Business Analytics、文本与社交媒体分析、Business Intelligence、工业应用，以及 GSOM/self-structuring AI。由公开研究方向判断，本题与其应用 AI 和决策支持工作有交集；这不能证明他已经认可课题、方法或投稿目标。

已核对的具体关联：

- *Transforming Customer Digital Footprints into Decision Enablers in Hospitality*（2024）：将非结构化评论转成 emotion/aspect 表示并进行分群以支持决策；作者包含 Alahakoon。[出版社全文](https://mdpi-res.com/d_attachment/applsci/applsci-14-03114/article_deploy/applsci-14-03114.pdf?version=1712561340)
- *Multi-Agent RAG Chatbot Architecture for Decision Support in Net-Zero Emission Energy Systems*（2024）：使用 LLM/RAG 与多 agent 支持能源决策；作者包含 Alahakoon。[合作机构论文记录与摘要](https://inl.elsevierpure.com/en/publications/multi-agent-rag-chatbot-architecture-for-decision-support-in-net-/)
- 官方 [成果列表](https://scholars.latrobe.edu.au/dalahakoon/publications) 还列有 *Business optimization for digital manufacturing: A fine-tuned large language model approach*（2026）。本次只核对题目与发表元数据，未获取其全文，不据此推断具体实验方法。

因此保留本文件的检索选题，把研究动机表述为“从分散通信到有依据的商业决策支持”，把实验仍限定为多需求检索的证据覆盖、无依据推荐与成本。不要为了迎合导师把 GSOM、生物认知或多 agent 强加进方法，也不要把有引用的解释称为因果解释。接下来向导师确认：更适合方法比较还是设计/系统研究，以及其认可的第一篇评估范围。
