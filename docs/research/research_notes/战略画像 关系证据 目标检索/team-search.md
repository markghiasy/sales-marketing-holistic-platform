# 商业目标驱动的网络检索、资源画像与解释子图

研究日期：2026-09-28。范围：文献与本地实现核对，未修改应用代码，未运行客户数据或能力抽取实验。以下 Cited Findings 是来源支持的事实；Inferences 是本项目的设计提案，尚未测量收益。

## 一、这属于什么成熟研究问题，为什么不是直接取 top-k 人？

### Takeaway
**按用户最新澄清，主要用户是业务决策者，不能把问题缩窄为技术技能或招聘组队。** 总体任务应是“战略目标 → 所需角色/资源/信息/约束 → 候选机会与接触路径 → 证据与缺口”。Expert finding 和 team formation 是其中一类任务；市场进入、获客、合作渠道、融资与商业引荐不必求一个共同工作的团队。GraphRAG 可以支持上下文检索，但不会自动产生符合业务目标的机会决策。

### Cited Findings
- Burt 2004 讨论跨群体结构洞的 brokerage 如何提供不同信息与选项，并在一家美国电子公司的经理网络中观察相关性。这支持把跨圈信息入口纳入分析，不支持从图位置直接推断一个人愿意引荐、能调动资源或有交易决策权。[原论文](https://snap.stanford.edu/class/cs224w-readings/Burt04StructureHole.pdf)
- Balog、Azzopardi、de Rijke 的 SIGIR 2006 论文比较两条路线：先聚合一个人的文档再匹配问题，以及先找相关文档再通过文档—人关联找专家。作者强调可靠归属的重要性；在其 TREC Enterprise 实验中第二条路线更好。这不等于“文档提到某人就证明其专业能力”。[作者论文](https://krisztianbalog.com/files/sigir2006-expertsearch.pdf)
- Lappas、Liu、Terzi 的 KDD 2009 把任务定义为技能集合，选择覆盖技能的成员，并减少社会网络上的沟通成本；研究 diameter 与 MST 成本，相关决策问题为 NP-complete。论文给出 RarestFirst、CoverSteiner、EnhancedSteiner 等方法，说明单独先覆盖技能再连接图可能造成很高的连接成本甚至失败。[作者机构论文](https://cs-people.bu.edu/evimaria/cs591/lappas09finding.pdf)
- Anagnostopoulos 等 WWW 2012 的后续工作加入持续到达任务和负载平衡，研究技能覆盖、沟通开销和成员负载的冲突；实验是演员与科学家协作网，不是私人通讯中的真实可用性或推荐意愿。[作者论文](https://chato.cl/papers/anagnostopoulos_becchetti_castillo_gionis_leonardi_2012_online_team_formation_social_network.pdf)
- Microsoft 的 GraphRAG 论文主要针对全局语料总结；社区摘要支持“整个资料讲了哪些主题”。官方 local search 则以相关实体为入口，组合关系、文本、社区报告等上下文。这些资料没有声称提供本项目所需的强制技能覆盖求解器。[论文](https://arxiv.org/abs/2404.16130)；[官方 local search](https://microsoft.github.io/graphrag/query/local_search/)
- G-Retriever 将文本图检索写成 Prize-Collecting Steiner Tree，以相关节点/边的收益和连接成本选择子图，再用于图问答；研究包含模型训练/soft prompting，不是可以无需训练直接替换本 demo 的功能。它提供“有预算的相关子图”参考，而非能力资格验证方法。[作者论文](https://arxiv.org/abs/2402.07630)
- 本地代码：NetworkRetrieval.people 仍是规范化词项 OR 召回；pack.coverage 表示文本命中。Agent Requirement 已有 require/prefer/exclude，但没有据此确定性求解一个满足约束的团队。neighborhood 目前保留 confirmed/active 人际路径与 shared_context 的区别，已有 1–3 跳和完整来源包基础。[retrieval.py](../../../adapters/network/retrieval.py)；[agent.py](../../../adapters/network/agent.py)

### Inferences
- 商业画像应包含：做过什么；覆盖哪些市场/行业/地区；当前组织角色；有来源的资源或渠道关系；明确表达的业务需求；公开或明确提供的资金/采购授权范围；过去合作；最近发生的变化与时机。每项存来源和时间，不能由头衔推断决策权，也不能由投资公司任职推断其个人财富或愿意投资。
- 目标决定检索模式：市场进入找当地行业理解、渠道、试点入口；获客找已表达需求、匹配场景和接触路径；合作找互补资源与已有合作依据；融资找明确投资范围和已有引荐路径；实施项目才调用互补团队选择。统一返回机会+路径+缺口，而不是所有任务都给“最优团队”。
- 社会资本指标只辅助发现可能的信息桥梁。部分观测图中的 betweenness、结构洞和弱连接不代表完整社会网络；关系频率低不自动意味着能提供新资源。不要输出稳定的“商业价值分数”或把联系人物化为资源所有者。
- 三层应分开：证据召回（哪些材料相关）→能力依据评估（材料究竟支持什么）→目标团队选择（组合如何覆盖要求）。不能把第一层 lexical matching_evidence 直接改名为 skill_verified。
- top-k 联系人可能全是技术人员，漏掉试点资源；团队目标是边际覆盖和互补，而非简单相加独立分数。
- 当前几十人的 demo 不需要 GNN 或全量社区摘要。先用轻量数据结构和可复现的小规模优化，GraphRAG/PCST 留作规模或多跳需求证明后再比较。
- 团队成员、引荐中间人、参考项目是不同角色。一个桥梁联系人能帮用户找到专家，不自动被算成技能覆盖成员。
- 同一需求可有多条替代团队方案，例如“证据更完整”“更容易接触”；这些是对明确目标的建议，不是全局能力排行榜。

### Gaps
- 上述经典研究通常把技能集合和社会图当作输入，不能直接解决从私人消息中判断技能、贡献归属、过期事实、意愿与可用性的问题。
- 尚无本项目的真实能力标签、匹配金标准或团队效果实验，因此不能宣称此方案比现有方案更准确、更便宜或能保证成功组队。

## 二、小 demo 应如何从复杂需求生成可靠的子图？

### Takeaway
先产生可编辑的需求列表，再构造 person × requirement × evidence 矩阵，以确定性约束选择互补人选，最后附上有来源的关系路径。未知硬需求应返回“部分可用团队 + 明确缺口”，不能把未知说成满足，也不应把整个结果清空。

### Cited Findings
- 开放世界知识表示区分“没有记录”与“事实为假”；W3C OWL Primer 明确说明缺失的事实可能仍是真的。本项目可借用此原则而不必采用 RDF/OWL 技术栈。[W3C](https://www.w3.org/TR/owl2-primer/)
- 当前 pack 已区分 matching_evidence、searched_no_match、budget_omitted、not_searched，并提供 scope/as_of。它们属于检索过程状态，既不是一个人的真实能力状态，也不是完成评估的证明。[本地实现](../../../adapters/network/retrieval.py)

### Inferences
建议流程（尚未实施；先按战略类型分支）：

0. **Strategic task routing**。明确用户想获得的是信息、客户线索、渠道关系、资本线索、引荐还是交付团队。LLM 先给可编辑的 strategy brief：目标/阶段/目标市场/要解决的问题/时间/已知约束/需要的角色与资源。未说明预算或采购权就标 unknown；用户自己的假设也单独标 hypothesis。对于非组队任务，以下第 5 步替换为 opportunity ranking：匹配的业务需求/资源依据优先，然后看联系路径、时机证据和补足网络信息的价值；不强迫所有结果彼此相识或组成一队。

1. **目标拆解**。LLM 输出目标、3–8 个 requirement；每项带 requirement_id、用户原话、规范化能力/领域、must/prefer/exclude、团队级或个人级约束、最低证据类型、时间范围。用户明说的条件与模型建议补充的条件分开。歧义可以保留 provisional，不偷偷扩大硬要求。
2. **逐需求召回**。在全库能力断言、工作记录、项目、原文中找候选，再把证据归给实际主体与角色。词项/同义词可做第一版，随后实验 BM25/dense/hybrid。召回罕见需求时不能先按“总相关度”截断掉其唯一候选。
3. **证据匹配矩阵**。每个 (person, requirement) 返回 supporting/adjacent/contradicted/unknown 和 evidence_ids、项目、日期、主客体、本人参与程度、review_status。supporting 只意为符合明确的证据规则；自述、工作产物、第三方评价、正式考核应分别显示。项目交付记录可以支持“做过这件事”，不自动证明其认证、熟练等级或工作质量。
4. **硬条件判定**。只有 evidence policy 所允许的 supporting 才覆盖 must。adjacent 只作为需要确认的候选线索；unknown 不能通过硬条件；contradicted 需要时间/对象范围正确才算冲突。若要求“必须确认可在十月投入”，未记录可用性的人不能被标为已满足，但可以放在待确认队列。exclude 也要三态：已确认触犯则排除，缺少信息则待确认；不要把没有负面记录解释成已获许可。
5. **选择团队**。小 demo 先枚举不超过 5 位的候选组合，预先缓存需求覆盖位图和关系路径；只在有限候选集内声称最优。候选过多时采用按“新增 must 覆盖 → 新增 prefer 覆盖 → 来源强度/新鲜度 → 更小人数/较短已有路径”的贪心或 beam search，然后单人替换优化。先处理罕见 must，可保留 2–3 个不同组合。所有分数是可调启发式，不是人的真实能力数值。
6. **无完整解时**。返回最大可证据支持的部分覆盖团队和 uncovered requirements。明确“现有资料未发现 AI 红队交付经历；A 有相邻工程经验可先确认；B 是有来源的潜在接触路径”。不要返回“网络中没有会的人”，不要虚构安全专家。
7. **路径与预算**。只从实际有来源的人际边找至多 2–3 跳的接触路径；保留所有中间人和逐边来源。共享公司/项目走 shared_context 路径，不能当互相认识。现有“Advises / Reports to / Client of”关系也不意味着有引荐意愿；需要按关系类型、方向和角色解释。显示“可以尝试通过 B 询问”，而非“B 将介绍你”。
8. **子图视图**。实线表示存储的有来源事实；单独样式表示本次需求到人的 matches_requirement 建议边。建议边带 query_id、计算版本、证据，放在 query result 层，不写回永久关系事实。缺口是 requirement 卡片，不是假人物。允许若干未连通分量，不能为了“酷炫连成一张图”生成认识边。
9. **动画和解释**。需求 chips → 候选浮现 → 支撑项目/作品 → 接触路径 → 缺口，按真实完成阶段渲染。点击需求高亮实际支持者；点击人看主张—来源链。先产出结构化结果，由 UI 可重放动画，不用动画模拟尚未发生的调查。

例如“把 cybersecurity program 推进企业试点”的子图可以呈现：用户 → 已合作的业务介绍人 → 可能的试点公司联系人；公司 → 明确表达的安全测试需求；项目 → 已有可复用成果。需求匹配连线是本次机会假设，不是已达成商机。图旁列出“预算未知、采购批准人未确认、引荐意愿未确认、技术交付证据缺口”。系统建议的下一步是先验证哪个假设，而不是宣布某人会购买或能融资。

建议返回对象：
- requirements[]：用户/系统来源、优先级、scope、time。
- candidates[]：person_id、支持哪些需求、相邻经验、待核验条件、来源。
- opportunities[]：task_type、candidate_people/orgs、matched_needs/resources、observed_basis、hypotheses_to_validate、timing、next_question、gaps。
- teams[]：仅实施/组队模式；member_ids、per_requirement_coverage、uncovered、tradeoffs。
- paths[]：typed edges、完整 evidence_ids、是否缺少引荐意愿。
- result_graph：existing_fact_edges 与 query_recommendation_edges 分列。
- search_scope：资料覆盖、截至时间、过滤/预算截断、没有搜索的内容。

关系亲近程度可用于“先联系谁”的次级排序，不能弥补专业要求未满足。沟通次数也不是 workload；没有日历/任务容量记录时负载只能未知，不应套用 2012 论文的负载变量。

### Gaps
- 来源证据的最低标准需要与产品用途对齐。研究原型可以说明 evidence-supported；不能默认把观察到的任务记录称为 assessment-certified competence。
- 并没有用户批准的团队规模、路径数、证据新鲜度阈值；上述 5 位、2–3 跳是 demo 初始配置建议，要通过案例调整。
- 如果需要判断“能否胜任”的真实概率，需要有独立评估标签和校准数据。先避免显示 92% 等伪精确分数。

## 三、什么能作为论文问题，怎么测而不夸大创新？

### Takeaway
可研究“不完整、时变、带归属歧义的通讯证据中，如何产生可解释且承认未知的战略网络推荐”。团队推荐是受控子任务，而非整个产品定义。技能覆盖、Steiner 子图和 LLM 拆需求本身都有先例；可能贡献在证据语义、时间/归属约束和可验证的 end-to-end 评估，但目前只是研究假设。

### Cited Findings
- 专家文档关联、网络团队覆盖、在线负载平衡、预算子图问答均已有明确研究先例，因此不能以“首次用图/LLM 找团队”为创新主张。[专家检索](https://krisztianbalog.com/files/sigir2006-expertsearch.pdf)；[组队](https://cs-people.bu.edu/evimaria/cs591/lappas09finding.pdf)；[在线组队](https://chato.cl/papers/anagnostopoulos_becchetti_castillo_gionis_leonardi_2012_online_team_formation_social_network.pdf)；[G-Retriever](https://arxiv.org/abs/2402.07630)

### Inferences
候选研究问题：

> 在证据不完整的商业通信网络中，保留人物/组织角色、业务需求、资源关系与事件的主体、时间和未知状态，并按战略目标选择机会与路径，能否在固定证据预算下提高被证据支持的目标覆盖，减少无依据的能力、商业需求、决策权与引荐断言？

建议分离评估，避免一个生成模型既创造画像又担任唯一评分者：
- **抽取/归属**：主体、技能、参与角色、项目、时间、否定的 precision/recall；本人工作 vs 转发/第三人工作区分。
- **能力证据匹配**：supporting/adjacent/contradicted/unknown 的混淆矩阵；“交付过”与“认证/考核通过”混淆率。
- **候选检索**：per-requirement recall@k、罕见需求召回；单人 nDCG 只作辅助。
- **团队结果**：有证据支持的 must/prefer 覆盖、违规硬条件率、重复技能人数、真实存在的完整路径比例、无依据关系/引荐声明率。
- **未知处理**：未满足/资料不足缺口的准确率与召回率；unsupported-satisfaction rate。无证据不能在 gold 中简单标成负能力。
- **成本/体验**：source token budget、调用次数、P50/P95 延迟；人工判断解释是否足以决定联系谁。不能把动画喜欢度等同任务成功率。

战略场景另需标注：观察到的需求 vs 系统推测的机会、联系人 vs 决策权、接触路径存在 vs 对方愿意引荐、当前时机 vs 过期事件。指标应包括 opportunity evidence precision、未验证假设识别率、下一步验证问题的业务相关性；成交率/融资成功率只有真实长期跟踪才可能评估，当前不能声称改善。

最小基线组（组队子任务；战略机会任务采用对应的机会排序基线）：
A. 当前 literal OR + LLM 回答。
B. 先检索证据再归人，独立 top-k。
C. 相同证据/候选的 coverage-only team selection。
D. C + typed path cost + evidence/time/unknown constraints。
E. 可选 generic graph-neighborhood/PCST retrieval + same answerer；只有投入合理时才做完整 GraphRAG，不应拿弱化实现冒充原论文。

消融：
- 去掉贡献角色归属；去掉有效时间；把 adjacent/unknown 当支持；去掉团队互补项；去掉路径类型；去掉完整路径预算保护。
- 相同候选证据、相同 LLM、相同提示/上下文预算；固定开发集与未调参测试集，重复随机生成，报告离散度。
- 小规模枚举可提供“给定人工标注矩阵和限定候选集”的优化 oracle，帮助区分召回失败、证据理解失败和组合算法失败。

数据与边界：
- 第一轮可构造合成对照对：工程泛标签但无安全经历；转发了他人项目；两位同公司却无相识证据；过去强合作现已离职；技能唯一持有人与 owner 没直接联系；一名桥梁不具备技能；完全缺失必须项；负面证据后续被修正。
- 这些合成案例只能验证语义规则与系统行为，不能证明工业泛化。若后续用真实案例，应由独立领域评阅者标注，并按许可与隐私约束处理。
- 现在没有任何上述指标的实测数值。已完成的浏览器/回归测试和少量 Claude smoke checks 不能替代该研究评估。
- 最谨慎的论文定位是 system + evaluated evidence-aware recommendation；是否达到算法新颖性，要在更完整 related work 与实验后判断。

### Gaps
- 未证明方案能预测项目成功、未来交付或人际合作质量，也不应把这些列为已实现能力。
- 尚未完成针对现代专门 team recommendation、competence assessment 与不确定图检索的穷尽式文献综述；本笔记是可实施起点，不是 novelty clearance。
