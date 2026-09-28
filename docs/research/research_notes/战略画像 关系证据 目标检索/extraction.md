# 从通信与项目工件抽取战略关系画像：来源、需求、角色、资源与能力证据

## 1. 已有研究能支持什么，不能支持什么？

### Takeaway
可以研究和实现，但“识别技能词”“将证据归属于人”“证明这个人在具体情境下能做好任务”是三个不同问题。最有价值的路线是证据支持的能力断言与检索，不是让 LLM 给每个人生成一段稳定人格描述或通用能力分数。

**范围修正：这是战略关系画像，能力只是其中一个 facet。** Mark 的主要问题可以是找潜在买家、组织试点、找渠道、调动资源、识别正确决策参与者、判断时机与设计下一次沟通。以下技能文献只覆盖“谁有什么专业经验”的一部分，不能让整个产品变成招聘系统。

### Cited Findings — 战略场景补充
- Webster/Wind 的组织购买模型将采购看作组织情境中的决策过程，涉及预算、成本及组织因素；作者明确它是 general model，不能直接量化为具体交易预测器。用于提醒我们将人、组织、机会与具体决策分开建模，而非由 title 生成成交分数。— [原作者 Wharton PDF](https://faculty.wharton.upenn.edu/wp-content/uploads/2012/04/7215_A_General_Model_for_Understanding.pdf)
- Purver 等讨论多方对话的 action-item extraction，要求识别 owner、task、timeframe，并指出 owner 往往需要由交互中的请求/承诺推定，不能仅找显式人名。— [SIGDIAL 2007](https://aclanthology.org/2007.sigdial-1.4/)
- COLING 2020 的 intent mining 使用对话语料形成意图类别，涉及自动聚类与标注；它支持“从对话提取需求/意图”的研究方向，但客服意图标签不能等价于真实购买意愿、预算或可成交性。— [Intent Mining](https://aclanthology.org/2020.coling-main.366/)

### Inferences — 战略场景与画像边界
- “这个人对我的目标有什么作用”必须是 query-specific fit。持久层存事实/报告/事件；查询层生成候选角色：潜在买家、行业顾问、渠道合作者、试点方、赞助者、资源持有人、引荐人。候选角色不是永久标签，且不能未经验证写回“决策者/愿意购买”。
- 职位、行业、组织资产、个人权限互不等价。企业拥有数据或试点场景，不代表某员工有权提供；VP 不自动等于本次采购签字人；认识客户不自动代表能介绍或愿意介绍。
- “Why now” 的依据应是最近明确 initiative、需求、采购窗口、正在招标/评估、承诺再次联系等；不能由最近聊得多自动推出“高购买意向”。
- 下一步建议可以是验证未知项：“询问 Alice 是否负责试点审批”，并把 authority=unknown 展示出来；这比虚构 authority 来凑齐 subgraph 更实用。

### Cited Findings
- 专家发现并非新问题。Balog 等 SIGIR 2006 对比 person/profile-centric 与 document-centric 两种概率模型；后者先检索相关文档，再汇总关联的人，在其 TREC 实验中表现更好。论文明确说 document-candidate association 质量很关键；这并不意味着每一个发信人都是正文技能的拥有者。— [Formal Models for Expert Finding](https://krisztianbalog.com/files/sigir2006-expertsearch.pdf)
- NIST TREC 2006 发布 expert topics、expert qrels 及 supporting-document qrels，可用于“推荐谁 + 哪份文档支持”的检索基线；它不是个人技能熟练度或团队交付能力金标。— [TREC 2006 Enterprise data](https://trec.nist.gov/data/t15_enterprise.html)
- SkillSpan 是英文招聘文本的 span 标注数据，约 14.5K 句、12.5K 以上技能/知识跨度，附专家标注与指南；目标是提取岗位所需的能力表述。不能将 job-ad 提及识别效果视作从聊天证明能力的效果。— [SkillSpan, NAACL 2022](https://aclanthology.org/2022.naacl-main.366/)
- TECH/HOUSE 扩展 SkillSpan，将 skill spans 映射到 ESCO；TECHWOLF 在句子级标注 ESCO，作者 repo 固定 ESCO 1.1.0，说明标签与词表版本必须匹配。— [Official skill-extraction benchmark](https://github.com/jensjorisdecorte/skill-extraction-benchmark)
- NLP4HR 2024 将六个数据集统一来比较 LLM few-shot extraction；作者报告 LLM 并未整体追平监督模型，但对复杂句法的技能提及有优势。因此“换大模型即可”并非研究支持的通则。— [Rethinking Skill Extraction](https://aclanthology.org/2024.nlp4hr-1.3/)
- 2025 GenAIK 已有 skill extraction → ESCO alignment → multilingual knowledge graph → job/CV matching 的研究，故 “LLM + skills graph + matching” 本身不能直接宣称创新。— [Kavas et al. 2025](https://aclanthology.org/2025.genaik-1.15/)
- EACL 2026 SkiLLens 使用候选提取、embedding 候选映射、LLM 与人工复核，区分新技能与新表达；原文映射 prompt 强制从三个候选中选一个，且部分评估为 ESCO alternative-label→preferred-label 代理任务。它适合借鉴模块结构，但并未证明真实通信的归属正确性，也不能把其 mapping 准确率外推为个人能力准确率。— [SkiLLens PDF, §§3–4](https://aclanthology.org/2026.eacl-industry.65.pdf)

### Inferences
- 推荐采用双通道：持久化的能力证据画像用于可解释过滤；查询时仍检索原始事件/文档以发现尚未抽取或尚未归一化的经验。不要要求全部价值先压缩进几个永久标签。
- taxonomy 提供一致名称、层级和跨语种检索，不充当事实裁判。保存原始表达与 canonical concept，并允许 exact / broader / related / unmapped；特别是 AI red teaming、agent security 等新复合术语，不能强行贴近但错误的已有词。
- 人的“技能存在”与“当前可用”“愿意合作”“能替你引荐”各自需要独立证据；不能从关系强度一并推出。
- 初版基础排序可以比较：(A) profile/tag lexical；(B) document BM25 → author/subject aggregation；(C) hybrid document retrieval；(D) evidence-typed temporal assertions。D 是待验证方案，不预设优于全部基线。

### Gaps
- 本次找到的开放技能抽取 benchmark 主要来自岗位/CV，未找到同时覆盖多渠道私信、正确人物归属、真实交付、动态技能与引荐路径的单一可靠金标。
- 未核验 TREC 原始 corpus 今日下载与许可流程；官方 qrels 可见，不等于所有原文可自由商用。
- 本次不是系统性综述，不能证明 proposed combination 首创；需后续按 expertise retrieval、competency evidence、temporal profiling、team recommendation 检索近邻工作。

## 2. 该怎样抽取、保存、更新，并避免把“说过”当“做过”？

### Takeaway
最小对象应是一条带来源与限定范围的 CapabilityAssertion，下面挂可核查的事件/工件证据。提取置信度、来源独立性、行为证据与真实熟练度分开表达；允许不知道、冲突与人工修正。

### Cited Findings
- FactBank 将事件事实性定义为相对于不同 discourse sources 的解释；同一事件可以有互相分歧的来源视角，标注结构包含事件、来源及其事实状态。因此 source attribution 与 factuality 不是把 source URL 填上就解决。— [FactBank official LDC catalog](https://catalog.ldc.upenn.edu/LDC2009T23)
- CODI 2025 研究多种 LLM 的事件、来源、belief 联合提取；混合 event tagger + LLM 与 source normalization 有帮助，但 nested belief 仍是突出弱点。作者分析包括把嵌套来源错归 author，以及 unknown 被判 true/possibly true。注意原文附录文字与表 5 的 Full F1 提升有不一致，笔记不转引该增幅；无需靠这个数字支撑架构决策。— [Zero-Shot Belief, PDF §§5, G](https://aclanthology.org/2025.codi-1.10.pdf)
- 早期 email 专家发现明确剔除被引用邮件内容，再计算新贡献长度；活跃度/长度/线程位置仅是启发式，作者报告最终表现不理想。不能把高通信量直接定义为高能力。— [Pitt at TREC 2006](https://trec.nist.gov/pubs/trec15/papers/upitt.ent.final.pdf)
- 本地 demo 的 retrieval 接入 profile_assertions/work_records，检查 evidence_ids 与 observed_at，并保留 valid_from 等字段；现有生产 structured_facts 从 LinkedIn connection 写 works_at / has_title，没有在这两个文件中实现细粒度能力抽取。此处是有限代码检查，不是整个 repo 的不存在证明。— [retrieval.py](../../../../adapters/network/retrieval.py); [structured_facts.py](../../../../adapters/resolution/structured_facts.py)

### Inferences
以下是针对本项目的建议设计，并非声称某一论文已验证了整套系统。

**建议的抽取与验证流水线**

1. 原文规范化：保留 message/artifact ID、channel、author、reply-to、thread、source timestamps、原始文本 hash；分离引用/转发/签名，保留引用来源指针，去重跨渠道复制。不可丢掉否定、时态与 modal。
2. 人物归属：分别提取 speaker、claimant（真正作出主张者）、subject（能力/行动归属者）、recipient、mentioned people；“我推荐 Alice 做安全测试”不能成为发送者安全测试能力，“我们团队做了”不能自动给所有成员。
3. 原子事件/断言：提取 action、object、role、artifact/outcome、project、organization、时间；同时标注 factuality（completed/ongoing/planned/hypothetical/negated/unknown）。先写“声称完成威胁模型”，有验收/工件证据后另记“存在相关工件/被验收”，不要把前者静默升格成后者。
4. 证据种类使用分维度而非单一等级：claim_relation = self_report / third_party_report / reviewer_assessment；evidence_medium = message / authored_artifact / task_event / acceptance_event / credential；verification_state = unreviewed / source_checked / human_confirmed / disputed。独立第三方传闻不必比有署名工件的自述更可信。
5. 精确 grounding：每个 candidate 保留 source spans 的 start/end、原文引用、指代解释所用的上下文引用；程序检查 span 确实存在、实体有效、项目时间一致。验证 extraction 是否蕴含于原文，不要求提取器输出隐式 chain-of-thought。
6. 技能归一化：原始 span → taxonomy top-k candidate（label+description+parent+version）→ contextual matcher；允许不匹配、比词表更具体、待人工定义。不能靠“Security engineer”职位推出 pentesting、red teaming、incident response 全会。
7. 证据聚合：每个能力展示独立 event/project/source groups 数，而非消息条数；同一交付被 20 次转发仍是一组，感谢/点赞不能作为另一次交付。独立不是简单 unique sender，须考虑共同来源与引用链。初版显式组别比未经校准的贝叶斯独立假设更稳。
8. 更新与冲突：source_received_at/observed_at 与 valid/event time 分开；追加 supersedes/retracts/disputes，保留旧证据；“目前不做安全咨询”改变可接项目状态，不抹去过去安全经验；“上封邮件写错，实际是 Bob 完成”应撤销 Alice 归属并重算投影。
9. 人工修正：允许改 subject、skill mapping、project、date、claim type；保存 reviewer、reason、superseded assertion、model/prompt/taxonomy version。修正后检索和图投影共同更新；identity merge/unmerge 后重新检查 subject binding，避免修复人名后留下污染画像。
10. 画像投影：显示“2025 年项目 X 中负责 Y；已有署名工件与验收记录”“自述熟悉 Z，尚无交付证据”；可视化 strongest examples、last observed use、independent contexts、unresolved conflicts。不上“能力 92 分”。

**建议最小数据对象**

CapabilityAssertion:
id, subject_identity_id, canonical_person_id_at_resolution, raw_capability_text,
concept_id?, taxonomy_version?, mapping_relation,
action_event_id?, project_id?, organization_id?, role?,
claimant_id?, source_chain, claim_relation, evidence_medium, factuality,
source_id, source_span_start/end, supporting_source_ids,
event_start/end?, observed_at, independent_evidence_group_id,
extraction_version, verification_state, supersedes_id?, dispute_ids.

ProjectParticipation 与 Availability/Interest 应独立于 CapabilityAssertion。ProjectDelivery 的 artifact、status、due date、acceptance、owner 不要全挤进 skill 的属性。

**失败例子必须进入测试**

- “我想学习 threat modeling”→ interest/planned learning，非已具备；
- “招聘一个会 Kubernetes 的人”→需求，非招聘者能力；
- “Alice 说 Bob 完成了测试”→ subject Bob，claimant Alice，sender 可能第三人；
- 转发 Bob 简历→ Bob 自述来源链，非转发者能力；
- “我们的团队做过”→ team-level evidence，人物未知；
- “没做过 PCI audit，但做过 threat modeling”→分别否定与正向；
- “应该下周完成”→计划，非交付；
- 无消息→未观察到，不能判能力不存在；
- “我不再负责项目”→当前角色终止，历史经验保留；
- 多次复制同一自述→不能提高独立支持数。

### Gaps
- Extraction confidence 不能直接解释为 competence probability；没有校准标注时，不应给用户展示伪精确概率。
- 当前 demo 可复用来源与时间结构，但我没有检查所有生产 LLM extraction 路径，不能断言仓库没有任何技能字段。
- 从某工件“由某人署名/被接受”仍不能证明独立完成、总体质量或跨环境可迁移能力；是否要判断熟练度，需要另行设计专家 rubric 与评价资料。

### Inferences — 将 CapabilityAssertion 扩展为多面战略证据
不要用无类型的万能 person_summary。建议统一 EvidenceAssertion 的 provenance/时态骨架，再分有类型的对象：

| facet | 要存什么 | 不允许直接推出什么 |
|---|---|---|
| Experience/Capability | 做过的任务、行业经验、项目责任及交付 | 有经验≠本次可用、胜任全部范围 |
| RoleInContext | 在组织/项目/机会中的具体职责，审批/评估/使用/执行角色 | 职位高≠任何预算都有决定权 |
| Need/Initiative | 谁明确需要什么、为谁解决、当前阶段、痛点、成功标准 | 提到问题≠准备购买 |
| Offer/Resource | 可提供的服务、数据、场景、渠道、资金等；控制主体与条件 | 所在公司有资源≠个人有权调动 |
| Goal/Constraint | 对方明确目标、时间、预算范围、地域、依赖、排除条件 | 我方认为有价值≠对方目标 |
| RelationshipEpisode | 一次合作、介绍、邀请、承诺、交付、拒绝、恢复联系 | 同公司/同项目≠私人熟识，历史介绍≠此次愿意介绍 |
| OpportunityRole | 针对某个 opportunity 的角色、来源、有效时间 | 一个机会的角色≠永久属性 |
| QueryFit | 本次目标中的潜在作用、证据、缺口、建议验证问题 | LLM建议≠已确认事实 |

统一字段应增加：
assertion_type, subject_type/person_or_org, subject_id, predicate, object,
context_project_id?, opportunity_id?, counterparty_id?,
source_author, attributed_claimant, source_chain, origin_kind,
event_time/valid_from/valid_to, observed_at, last_confirmed_at?,
explicit_expires_at?, review_after?, status, negation/modality,
evidence_group_id, source_spans, contradicted_by/supersedes, visibility_scope,
extractor_version, human_correction.
其中 origin_kind 可供 UI 显示 observed_record / self_declared / reported / inferred。observed_record 只说明“系统看到了这个工件/事件”，仍不表示其业务内容已经被独立证实。verification_state 与 origin_kind 分开；inferred 永不自动转 confirmed。

**时效与可观察性**
- 行业经验可保留历史；预算窗口、角色、当前需求、资源可用性、引荐承诺通常更需重新确认。review_after 是需要复核的调度日期，不能凭它断言事实为假。
- 显式截止、拒绝、已解决、已换职位、介绍已完成等更新状态；没有新消息用 stale/unknown，不用 expired=false 或“失去兴趣”。
- 保存渠道/时间范围覆盖信息，如“仅见邮件至 9 月 20 日”；不可见渠道没有证据不代表没有关系、项目或需求。避免把高可见度人物天然排在低可见度但相关的人物之前。
- 临时 QueryFit 不回写事实图；它引用 eligible assertions 形成目标子图。展示 source-backed role 与 hypothetical role 不同视觉状态。

**可落地示例（合成，仅示意）**
目标：“为新的 cybersecurity offering 找到 2 个金融业试点，并找一位能牵线的人。”
解析成：金融业/真实试点场景/近期安全initiative/试点参与条件/决策路径/可验证引荐路径。
子图可能有：
A → self-declared 当前在推动金融企业安全评估；
A → reported B 负责本次技术评估；
C → observed 过去曾把用户介绍给 A；
D → capability 有相关安全测试交付记录；
Gap → 谁能批试点预算、A 是否愿意参与、C 此次是否愿意引荐仍未知。
图给的是“可验证的切入假设”，不是已确认买家名单。技能D只是四类证据中的一类。

**新增高价值反例**
- “我朋友公司需要安全审计”→需要主体是朋友公司，非发信人自己的采购需求。
- “今年预算已经用完”与“下财年再聊”→近期窗口关闭但未来follow-up，不是永远无需求。
- “我能帮问问”→条件性意愿，非已承诺成功引荐。
- “Alice以前管采购，现在由Bob负责”→上下文角色更新，不能保留Alice当前决策权。
- “我们有100家客户”→声明渠道覆盖，不等于有权提供客户数据/承诺分销。
- “谢谢你的介绍”→一次介绍事件，不能自动造出双方持续强关系。
- “邮件抄送CEO”→参与通信，不能推出该CEO审批该采购。

## 3. 如何评估，什么是能给导师看的研究贡献？

### Takeaway
论文应将“有依据的经验检索”设成可测任务。用公开数据验证部件，再用独立标注的真实通信/项目工件做端到端验证；合成 demo 仅用于可控回归与产品展示，不能作为工业有效性的证据。

### Cited Findings
- SkillSpan 发布 span-level 数据与指南，适合测抽取；其 job-ad 域与通信域不同。— [SkillSpan](https://aclanthology.org/2022.naacl-main.366/)
- TREC 2006 同时提供人员 relevance 与 supporting documents，适合衡量专家排序及解释证据召回。— [NIST data](https://trec.nist.gov/data/t15_enterprise.html)
- FactBank 有 source-relative factuality，适合测试 “谁声称什么、实际/不确定/否定” 子任务；须遵守数据许可。— [LDC](https://catalog.ldc.upenn.edu/LDC2009T23)
- 关于隐性人格推断不能只选乐观论文。一篇 2025 arXiv 预印本以真实访谈及 BFI-10 自评对照，发现一致性并不等于效度，最高 item-level 相关仅 0.27；它不是工作能力研究，也不能据此断言所有 soft skill 预测无效。另一方面 2026 Nature Human Behaviour 原研究摘要的研究简报报告了更积极的 narrative-based personality 结果。两者输入、任务与评估不同，不宜直接比较数字。— [Zhu et al. preprint](https://arxiv.org/abs/2507.14355); [NHB research briefing](https://www.nature.com/articles/s41562-025-02397-x)
- NHB 原研究链接为下面 DOI，本次受网站访问限制未读取正文，因此不引用其具体效应大小。— [Wright et al. original study](https://doi.org/10.1038/s41562-025-02389-x)

### Inferences
**实用评估分层（我们的方案）**

| 层 | 推荐指标 | 关键分母/定义 |
|---|---|---|
| skill mention | exact span P/R/F1；overlap F1 作辅助 | 标注了所有候选与负例的文本，不只抽取成功样本 |
| subject attribution | person accuracy；完整 assertion tuple F1 | speaker/subject/claimant 分开；人物未定应可 abstain |
| source grounding | span validity；human entailment precision；contradiction rate | 引用存在不等于引用支持结论；用人工盲评做主指标 |
| semantics | claim type/factuality macro-F1 | 自述、计划、否定、他人归属、团队归属要独立报告 |
| normalization | exact concept accuracy；Recall@k/MRR；NIL F1 | freeze taxonomy version；精确与 broader mapping 单独报告 |
| time/project | temporal/project binding accuracy；future leakage rate | as-of 查询不得看到之后证据；跨项目污染专门测 |
| evidence aggregation | duplicate inflation；independent group accuracy | 重复转发/同一个交付更新，不当多份独立支持 |
| profile assertions | precision at chosen review threshold；risk-coverage曲线 | abstain 后的高精度要同时报告保留了多少记录 |
| person retrieval | nDCG@k、Recall@k、MAP；support evidence P/R | 相关性金标“有依据可咨询”，不是保证成功 |
| operations | latency、input/output tokens、cost、review minutes | 整条pipeline计费，包含失败重试与人工负担 |

**建议可执行实验**

- Baseline 1：岗位/主题标签 + 关键词；Baseline 2：document-first BM25 → candidate aggregation；Baseline 3：原始片段 hybrid retrieval + LLM；Proposed：source-attributed、event/project/time-bound assertions + evidence retrieval。保持语料、query、模型预算一致。
- 先形成 annotation guideline，用小规模双人 pilot 修订，不把尚在变化的标签混入最终 test。标注文本是否支持事实与真实人的实际能力分别记录；Mark 可以评 groundedness/usefulness，专业 cybersecurity 能力需相应领域评审。
- 按 conversation thread / project / duplicate group 划分 train/dev/test，再做时间外推。随机消息切分可能让同一事实副本进入两边，造成高估；最终 query 应由未看输出的人独立编写，不从已有 skill 标签反向生成全部问题。
- 初版可规划 300–500 个真实候选断言 + 足量 no-claim 消息，覆盖自述/他述/工作记录/需求/否定/转发/中英混合；数字只是可行的 pilot 预算，不是统计充分性保证。收集样本后用误差区间决定扩展规模。
- 请求数据授权与适用研究审批应单独遵循项目现有约束；可以本地私有测试，公开匿名标注协议、可重现代码、聚合结果；不能宣称合成数据等价 Mark 工业数据。
- 设计 targeted ablations：移除 subject attribution、quote dedup、factuality、temporal filter、taxonomy abstention；观察错误推荐、错人、重复膨胀和时间泄漏如何变化。比“图好看/回答更长”更能说明贡献。
- 增加少量 counterfactual tests：换发信人但不改引用者、重复同一邮件、插入未来日期、交换项目名、把 completed 改 planned；期望对应字段改变，其他能力证据不漂移。
- soft skills 初版评估“是否存在可核查行为例子”，如协调跨部门评审、明确风险、提出权衡，而非“领导力/靠谱程度分数”；若要后者，必须有独立可靠 criterion，与实际绩效的外部效度验证。

**适合论文但仍需验证的新颖性候选**
题目可聚焦 Evidence-grounded, temporally scoped capability retrieval from heterogeneous communications。研究问题：来源归属、事实状态和证据依赖建模，能否在不显著牺牲召回的前提下降低 unsupported capability recommendation？可能贡献是 annotation schema + 困难案例数据 + retrieval方法/消融 + 人工评估。不能把普通 ESCO normalization、GraphRAG、LLM JSON 抽取各自当原创。

### Gaps
- 没有取得 Mark 真实样本或运行模型，没有任何属于我们系统的能力抽取准确率、人员排序增益或工业效率提升结果。
- 人格推断研究并非 teamwork/leadership 能力的直接验证，不能跨构念外推。
- 候选团队的互补性、引荐可达性属于另一个评估层，需要独立任务 gold 与人员可用性信息；本笔记未研究完整 team formation 算法。

### Inferences — 论文任务扩展到战略检索
- 论文任务可表述：给定一个业务目标和 as-of 时间，从多渠道证据检索“候选人/组织/机会 + 可支持的目标角色 + 行动路径 + 未知项”。不限定为找技能或组技术团队。
- Gold 应有 facet-specific labels：need-owner、resource-controller、role-in-opportunity、commitment-holder、expiry/timewindow、introduction-status。用 source attribution tuple F1 和 unsupported strategic assertion rate 测量。
- 用商业场景 query families：找试点/潜客；找渠道伙伴；找行业洞察；找资源/赞助；跟进已承诺事项。每类包含可回答、部分可答、完全不可答案例。
- 评估“回答有用且证据足够”的盲评，与最终成交/项目成功分开。成交受价格、市场等大量因素影响，不能用小样本demo宣称带来业绩因果提升。
- 加入 authority hallucination、willingness hallucination、stale-need recommendation、wrong organization need attribution 四项错误率；这比通用回答BLEU更贴近Mark场景。
- 合成数据覆盖状态迁移和反例；真实经授权case用于外部效度。候选方案仍需对比普通 CRM filters、BM25/hybrid retrieval、plain LLM summary；不能以“复杂图比标签多”替代效果证据。
