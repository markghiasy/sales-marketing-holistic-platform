# 战略联系人与组织画像：成熟本体和证据建模

研究日期：2026-09-28。范围：为 Outlook / WhatsApp / LinkedIn 联系人及组织建立可溯源战略画像，支持客户、伙伴、资源、引荐和执行人选的目标导向查找。以下 Cited Findings 为来源事实，Inferences 为针对本项目的设计建议，不代表标准强制要求。未发送客户消息到任何 API，未更改应用代码。

**范围修正（优先于下文技能子模型）**：Mark 与老板的核心需求是商业战略联系人/组织画像，技能仅是一个切面。总体应采用四层：
1. **较稳定事实**：人、组织、任职/成员关系、行业、地区、明确服务或资源；仍保留有效时间。
2. **有时间的商业情境**：当前目标、痛点、采购/合作项目、评估过程、时机、已表达约束、待办承诺。
3. **关系与接近路径**：谁认识谁、曾介绍谁、过去合作、可用联系渠道，以及是否明确愿意为此次目标介绍。
4. **查询时战略相关性**：对“卖给谁”“找谁做渠道”“谁能提供试点”“通过谁接近”的临时解释/排序，不能永久写成此人天生属于“高价值客户”。

最小底座建议是 Entity + EvidenceAssertion + Context/Initiative + Relationship + GoalMatch，能力词典和经验记录作为类型化扩展。不要把整个画像系统围绕人员招聘或项目组队设计。

## 1. 哪些成熟框架适合本项目？

### Takeaway

总体优先组合是 W3C ORG 的人/组织/角色结构 + PROV 与文本片段的证据底座 + 本产品少量商业情境关系。ESCO / NICE / SFIA 用于其中的能力与经验切面，不能主导商业画像整体结构。没有一个现成本体能把通讯自动变成已验证的购买意图、决策权限或个人熟练度。

### Cited Findings

- W3C ORG 用 Membership 把人、组织、角色组合成可附时间限定的关系，并区分 Role 与可以独立于任职者存在的 Post；同时明确组织结构本体并不完整表达控制、问责与授权流。因此组织头衔不足以推出购买决定权。— [W3C Organization Ontology](https://www.w3.org/TR/vocab-org/)
- schema.org Role 允许 roleName、startDate、endDate 等限定关系，ContactPoint 描述联系渠道与用途。二者适合轻量互操作，均不证明该联系人愿意帮忙或具有采购权限。— [schema.org Role](https://schema.org/Role)；[schema.org ContactPoint](https://schema.org/ContactPoint)

- ESCO 明确区分 knowledge 与 skill/competence，但不进一步区分 skill 和 competence；每个概念有首选词、别名和描述，并组织为知识、技能、态度价值观、语言四类。它是概念词典，不是某个人已经掌握技能的证明。页面显示 v1.2.1；实现应固定导入版本。— [ESCO skills pillar](https://esco.ec.europa.eu/en/classification/skill-main)
- ESCO 的职业、知识、技能概念有持久 URI，适合跨数据源连接，不能仅以中文或英文标签作为数据库身份。— [ESCO URI](https://esco.ec.europa.eu/en/about-esco/escopedia/escopedia/uniform-resource-identifier-uri)；本次该页面全文请求失败，搜索返回官方定义；可用 [官方 Handbook](https://esco.ec.europa.eu/system/files/2021-07/Handbook.pdf) 作备用核查入口。
- O*NET Content Model 区分 worker characteristics（能力、工作风格）、worker requirements（技能、知识、教育）、experience requirements、work activities/context、occupation-specific tasks 等；其职业数据用于描述职业要求，不是从职业名称认定某个联系人个人达到该水平。— [O*NET Content Model](https://www.onetcenter.org/content.html)；[O*NET database](https://www.onetcenter.org/database.html)
- NICE 用 Task 表示工作活动，Knowledge 表示所需概念，Skill 表示可观察行动能力，并组合成 Work Roles 和 Competency Areas。非常贴近“我要启动某安全项目，需要完成什么工作”。— [NICE Getting Started](https://www.nist.gov/itl/applied-cybersecurity/nice/nice-framework-resource-center/getting-started)
- NICE 特别指出 Work Role 不等于职位名称/职业；一个岗位可能只承担某 role 的一部分，一个团队也可能共同承担多个 role。— [NICE Occupations, Jobs and Work Roles](https://www.nist.gov/itl/applied-cybersecurity/nice/nice-framework-resource-center/resources/occupations-jobs-and-work)
- NICE 框架结构 SP 800-181r1 与组件数据分开维护；当前版本页显示组件 2.2.0，可下载 JSON/XLSX。应保存组件版本，不能假设论文年份等于数据版本。— [NICE Current Versions](https://www.nist.gov/itl/applied-cybersecurity/nice/nice-framework-resource-center/nice-framework-current-versions)
- SFIA 将“理解知识”“可执行技能”“在真实职责与后果下持续可靠地运用能力”视为不同证据主张，不是仅凭年资自动升级的线性阶段。— [SFIA assessment and recognition guidance](https://sfia-online.org/en/about-sfia/about-sfia-appendices/guidance-for-assessment-and-recognition-schemes-using-sfia)
- SFIA 的七级责任等级涉及责任、影响和通用属性，不应理解为一个聊天标签的熟练度。商业产品中使用或映射 SFIA 有许可要求。— [SFIA how it works](https://sfia-online.org/en/about-sfia/how-sfia-works)；[SFIA how we work](https://sfia-online.org/en/about-us/how-we-work)

### Inferences

建议“轻本体、重证据”，初期不导入所有框架：

| 框架 | 本项目用途 | 不应做的事 |
|---|---|---|
| ESCO | 通用技能/知识 canonical concept、同义词、概念层级 | 将职业关联技能自动授予该职位联系人 |
| NICE | cybersecurity 目标拆成任务、知识、技能，再匹配证据 | 将 cybersecurity 或 Engineering 大标签等同 red teaming 能力 |
| O*NET | 检查领域覆盖、区分技能/工作风格/任务 | 把职业平均/要求评分变成个人评分 |
| SFIA | 借鉴责任与持续交付的评估维度 | 自动标记 SFIA Level 5 或称认证；未核许可直接分发词库 |
| W3C PROV + Web Annotation | 记录抽取、证据来源、说话人、文本片段 | 以“有 provenance”宣称事实必然真实 |

产品内部先定义 30–80 个 demo 所需概念是范围建议，不是经研究验证的最佳数量。允许 local concept（例如 AI red teaming、agent security evaluation）暂不映射，以免强行对齐泛化概念。保留原语句；中文查询/同义词由本地别名层处理，不能把 ESCO 多语言支持理解为已提供本产品需要的中文标注。

职业、领域、技能、角色、经验分别存：cybersecurity 是领域；threat modelling 是可执行活动技能；security lead 是角色；在某项目交付某份威胁模型是经验事件。一个人可以同时拥有多个角色和经验。

### Gaps

没有找到能直接保证本项目非正式通讯到完整能力画像准确率的标准；框架覆盖度必须针对实际目标评测。最新 AI 安全技能是否完整覆盖 ESCO/NICE 未逐项核查，因此不宣称现成词库足够。

## 2. 如何保存能力主张、证据、时间和不确定性？

### Takeaway

核心记录应是“在何时、何项目/任务中，谁声称或展示过什么能力，有何证据”。把人永久挂一个 skill 标签会丢失这些限定条件，难以撤回错误抽取，也无法向用户解释推荐。

### Cited Findings

- W3C PROV-O 提供 Entity、Activity、Agent 及 wasDerivedFrom、wasGeneratedBy、wasAttributedTo 等关系，能表达来源、生成过程和责任归属；这些关系表达来源，不提供事实真实性评分。— [PROV-O](https://www.w3.org/TR/prov-o/)
- W3C Web Annotation 可用 TextQuoteSelector 的 exact/prefix/suffix 或文本位置标注来源中的具体片段，比仅引用整封邮件更便于审查。— [Web Annotation Data Model](https://www.w3.org/TR/annotation-model/#text-quote-selector)
- SKOS 区分 exactMatch、closeMatch、broadMatch、narrowMatch、relatedMatch；exactMatch 具有传递性，因此“语义相近”不应随意写成 exactMatch。— [SKOS mapping properties](https://www.w3.org/TR/skos-reference/#mapping)
- 本地生产 fact 表已有 subject_identity_id、fact_type、object_*、confidence、source/source_message_id、status、reason、model、prompt_version、extracted_at/reviewed_at；尚无多来源关联表、能力概念对象或双时间字段。— [本地 migration](../../../../db/migrations/0005_identity_resolution.sql)（链接按仓库根理解：db/migrations/0005_identity_resolution.sql）。
- 本地合成 fixture 有 26 条 profile_assertions（当前类型 function/industry）、5 条 work_records；profile 已有 observed_at、valid_from、valid_to 和 evidence_ids，work 有 project/person/area/status/due。检索器会排除空证据或缺失来源记录。— [fixture](../../../../tests/fixtures/network_demo.json)；[retrieval](../../../../adapters/network/retrieval.py)。以上为本轮直接读取代码的事实，不代表生产已有同等数据量或能力画像。

### Inferences

**商业战略画像优先扩展（设计建议）**

下文 CapabilityAssertion 是通用 EvidenceAssertion 的特例。基础断言允许 subject_type=person/organization/initiative，predicate 属于小而可审查的词汇：
- affiliation / offers_service / operates_in_domain / serves_market；
- expressed_need / pursuing_initiative / evaluating_option / stated_constraint；
- participates_in_decision / owns_budget_for_scope / evaluates_technical_fit / approves_purchase_for_scope；
- introduced / collaborated_on / offered_introduction_for / offered_resource_for；
- committed_action / requested_followup / declined_for_scope。

以上例子是内部词汇候选，不是声称已找到一套“统一商业战略本体”。从 10–20 个本次 demo 真正需要的关系起步，后续用标注误差决定扩充，避免改造成完整 CRM。

商业情境记录 BusinessContext：
- organization/person、initiative/topic、need/problem、desired_outcome；
- phase（仅在证据支持时，如 researching/evaluating/pilot/procurement）、time_window、constraints；
- decision_process_assertions[]、stakeholder_roles[]、next_action；
- evidence_ids、source_at/known_at/validity、status/conflicts、visibility。
预算、购买意图、决策权必须各自成断言并附范围。例如“我负责 CRM 预算”不等于负责安全采购预算；“发份资料看看”不等于有已批准预算或强购买意图；“Director”不等于 economic buyer。

StakeholderRole 应以 人 × initiative/decision × role × period 建模。角色可以是 user、technical evaluator、commercial evaluator、approver、introducer 等本地受控值；未知时留空。常见销售框架的角色只能作为询问/标注模板，不能靠职位或语气自动填满。

Resource/Access 也有范围：有企业联系、能提供技术执行、能接入试点场地、拥有合作渠道、明确愿意介绍，分别需要不同 predicate。资源属于组织时不能永久赋给联系人个人；离职后是否仍有 access 必须重新核实。

GoalMatch 应同时输出：
- proposed_strategic_role：prospective_customer / partner / channel / resource_holder / introducer / practitioner；
- fit_evidence：为何与本目标有关；
- business_context_evidence：为何可能现在值得谈；
- access_path：每一条真实关系边及来源；
- unknowns：需求、预算、权限、时机、意愿、可用性哪些尚未知；
- suggested_next_question：下一步最能减少不确定性的询问。
例如某制造企业有明确安全评估需求，一位联系人负责技术评估，另一位已表示可介绍采购负责人；子图可呈现 企业—当前 initiative—技术评估人—引荐人—待确认购买流程。不能将所有联系人压成“技能匹配度”。

建议 demo 优先支持三个商业问题：为产品找首批试点客户；找渠道/合作伙伴；找到某组织的有效进入路径。项目组队是第四个视图，复用证据底座即可。

以下是能力/经验切面的六种记录，可用现有 Postgres 实现，不要求 RDF store 或新增图数据库：

1. **CapabilityConcept**
   - id, kind(skill/knowledge/domain/role/behavior), preferred_label, aliases, description。
   - mappings[]: scheme, concept_uri/code, scheme_version, relation(exact/close/broader/narrower/related), mapping_method, reviewed_at。
   - 不把 ontology-mapping confidence 与 person-skill confidence 混用。

2. **CapabilityAssertion**
   - id, subject_identity_id（连接现有可逆身份解析）, concept_id, predicate。
   - predicate 如 self_reports_skill / participated_in / performed / delivered / assessed_at_level；保留原主张。
   - assertion_basis: self_report / third_party_report / observed_activity / artifact / assessment / model_inference。
   - attribution: asserted_by_identity_id, speaker_identity_id, subject_resolution_version。转发邮件中的作者与转发者分开。
   - project_id / organization_id / experience_id 可空，但有上下文时必须保存。
   - assertion_status: proposed / accepted / disputed / rejected / superseded；accepted 仅表示该证据主张经接受，不自动等于能力已认证。
   - evidence_refs[] 非空；polarity 与否定/假设/未来计划标记；“我要学 Python”不等于“已会 Python”。

3. **Evidence**
   - source_record_id, channel, external_source_id, content_hash, text_selector/quote, source_author, source_created_at, ingested_at。
   - original_source_group_id 处理同一消息转发/复制/跨频道重复，避免被算成三个独立佐证。
   - extractor/model/prompt_version, extraction_run_id；人工新增记录也记 creator/method。
   - 用户只能检索有权看见的证据；来源删除/撤回后重算依赖主张，不留没有依据的能力标签。

4. **Experience / Contribution**
   - person_id, project_id, activity/task, role/responsibility, relevant_concepts[]。
   - started/ended/observed_at, deliverable_ref, outcome_status, outcome_evidence, scope, supervision/autonomy 可空。
   - “发送报告”只支持交付事件；是否被验收、质量如何另有证据。参与项目不等于完成该项目所有技能。

5. **Assessment（可选，默认空）**
   - assessor, assessment_method, rubric/scheme_version, capability, level, assessed_at, evidence_refs。
   - 明确区分 self-assessment 与 independent assessment。未评估就显示 unknown，不由 LLM 猜 beginner/intermediate/expert。
   - proficiency_level 是该 rubric 下的评估结论；extraction_confidence 是系统是否抽对主张；evidence_support 是佐证情况。三个量不能相乘包装成“能力 93 分”。

6. **RelationshipObservation（复用现有关系层）**
   - 双方、频道、时间窗口、互惠交流/最近活动等现有观测指标。
   - 跟能力记录分开。联系方便、愿意介绍、能完成任务分别需要不同证据；同公司只证明共同组织背景，不证明认识。

时间建议至少四项：
- source_created_at：消息何时产生；
- observed_at / recorded_at：系统何时知道；
- valid_from / valid_to：主张声称适用的现实期间；
- superseded_at / retracted_at：系统何时撤销或更正。
不强造精确日期；保留 time_precision、unknown 或原句。历史查询同时限制事实有效期和当时可知范围，避免“用未来消息回答过去问题”。这是本产品设计建议，不是 PROV 规定的完整双时间数据库方案。

冲突以 assertion-level 关系表达：contradicts / corrects / supersedes，并保留双方来源及 reviewer rationale。技能旧证据默认是“最近未观察到”，不是“能力过期为零”；对当前可用性、任职等时效性更强字段可有独立失效规则。

一个合成示例：
- 原句：“I completed the threat model for Project A; Priya reviewed it.”
- 可存：Alex delivered threat-model artifact in Project A；claimed reviewer = Priya。
- 能否标记 demonstrated activity 取决于是否只有本人汇报还是实际附件/审阅记录可查；只有邮件时展示“本人报告曾交付”。
- 不可自动存：Alex = expert cybersecurity consultant；Priya = available to join；二人已形成强关系。

### Gaps

本次不做数据库迁移；应进一步核查最新事实抽取封闭词汇及 merge/unmerge 的引用更新方案。生产数据是否有足够工件、验收和任务状态尚未知，因此不能承诺交付可靠性评分。

## 3. 如何以画像支持商业战略，并保留能力/项目视图？

### Takeaway

先构建可解释的“经验与证据档案”，再做目标匹配。软实力呈现可观察行为；项目强度拆参与、职责、产出与可观测范围，不能从聊天量制造人格和绩效结论。

### Cited Findings

- O*NET 将 Work Styles 与 Skills、Knowledge、Work Activities 分开，是区分“怎么工作”“能做什么”“做过什么”的现成概念参照。— [O*NET Content Model](https://www.onetcenter.org/content.html)
- SFIA 评估指导要求证据与主张类型相称，并强调持续工作结果、责任和专业情境；时间长本身不能证明能力。— [SFIA assessment guidance](https://sfia-online.org/en/about-sfia/about-sfia-appendices/guidance-for-assessment-and-recognition-schemes-using-sfia)
- NICE 允许团队承担 work role，并将工作映射到 task/knowledge/skill，为“多人互补覆盖一个目标”提供描述语言；它本身不是最优团队选择算法。— [NICE occupations/jobs/roles](https://www.nist.gov/itl/applied-cybersecurity/nice/nice-framework-resource-center/resources/occupations-jobs-and-work)

### Inferences

**软实力**：存 contextual behavior observation，如“主持三方需求澄清”“将争议拆成两个待决事项”“替新成员完成 onboarding”，标注项目、时间、原文、报告者。若原文仅写“great leader”，存 third-party appraisal，不升级为经过测量的领导力。性格、诚信、情绪稳定性不从交流风格猜测。产品初版用观察记录和人工确认，避免雷达图伪精度。

**项目强度**用并列维度，拒绝一个混合总分：
- involvement：已观察到的任务参与/活跃日期/角色覆盖，附窗口与频道覆盖；
- responsibility：owner/contributor/reviewer/introduced by，必须有来源；
- delivery：承诺、交付、验收、阻塞与跟进分别建事件；
- relevance：此项目与本次目标的相似任务/领域；
- recency：最近一次相关行为，不等于能力衰减曲线；
- availability：当前是否愿意/有空参与，未知就写未确认。
活跃度不用于替代交付；交付次数不能跨不同任务规模直接比较个人绩效。

**战略检索**时目标拆成 Requirement，而非一次性给人加新永久标签：
Requirement(id, text, concept_candidates, must/prefer/exclude, context, min_evidence_basis?, temporal_constraint)。
每个 Person × Requirement 的匹配产生临时 MatchAssessment：
- supported：有具体相关证据；
- adjacent：背景相关但不直接证明；
- unknown：资料不足；
- contradicted：有冲突或明确不符合。
输出 evidence_refs、scope、reason、missing_information。候选子图连接目标需求—人—经验项目—证据，再单独叠加真实引荐路径。图边必须区分“匹配本次需求”与“现实人际关系”。

**MVP 建议顺序**：
1. 从现有五条工作记录和少量人工编写的合成安全项目证据扩充 schema，先呈现人与证据。
2. 标注小批真实授权样本的主语、任务、能力概念、原文依据和时间，测抽取 precision / 错人率 / unsupported claim rate / reviewer correction rate。
3. 再做本体归一化和候选检索，分别测 concept mapping、需求覆盖与引荐路径有效性。
4. 需求驱动地索取缺失信息，例如“是否实际负责过 threat modelling？相关交付在哪里？”；不能用生成式补全填数据库真值。
5. 与用户共同定义何为好团队后，再比较团队覆盖/重复能力/联系成本方案；不要先发明权重并称其研究结论。

研究可发表的切口不是“又一个 skill ontology”，而是“在稀疏、多渠道、时间变化且存在不确定性的通讯中，证据约束能力画像是否提升可解释团队检索”。至少比较 broad tags、LLM-flat profile、evidence-backed assertions 三种表示，控制相同检索器与模型，再比较带/不带 provenance/time 的消融。以上是实验设计建议，尚未验证效果。

### Gaps

尚无本项目标注集、用户对团队质量的稳定标准、能力证据足够性的阈值或关系权重校准。不能声称该 schema 已提升推荐准确率。角色和能力可以进入同一图，但 graph topology 不会自动解决技能真伪、工作质量或人选意愿。


### 商业目标的验证重点（设计建议）

在技能实验之外，加入客户发现、伙伴/渠道、试点资源、引荐路径四类目标。标注原文是否真的支持组织需求、联系人的决策角色、时间窗口和介绍意愿；重点统计 unsupported authority/intent claims、过时商业情境引用、路径中断、跨组织资源误归属。可以比较纯职能标签、静态联系人摘要、带时间和证据的目标条件画像。图是否漂亮与战略建议是否有用分开评分；由 Mark 评估下一步行动是否合理，不能只用 LLM 自评。此实验尚未执行。