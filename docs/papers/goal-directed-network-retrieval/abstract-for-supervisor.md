# Evidence-Grounded Multi-Requirement Retrieval in Professional Networks

**Eva Ng — Proposed research abstract for supervisor discussion**  
**30 September 2026**

Business professionals seeking collaborators, potential customers, or industry connections must identify complementary resources within fragmented communication histories. Retrieving individually relevant contacts may leave important requirements uncovered, while incomplete records can make recommendations appear better supported than they are. This study will investigate whether explicit tracking of requirement support improves evidence-grounded retrieval for business goals under constrained search budgets.

The proposed approach will operate over a heterogeneous professional-network graph containing people, organisations, projects, and source-backed assertions. A goal will be represented as requirements with explicit subject and contextual constraints. During retrieval, the system will update each requirement's evidence status and allocate further exploration to unresolved requirements. Results will comprise candidate resources, supporting evidence and relationship paths where available, together with an account of unresolved requirements. Shared affiliations will remain distinct from documented interpersonal relationships, and missing evidence will not be treated as proof of absence.

Using Ironman's communication-assistant prototype as an experimental platform, controlled comparisons will evaluate hybrid retrieval, fixed graph expansion, aspect-diversified reranking, and an adaptive retrieval controller under shared evidence rules and resource limits. Evaluation will use held-out, evidence-annotated queries to measure supported requirement coverage, unsupported recommendations, evidence-path validity, latency, and retrieval cost. Ablations and controlled evidence-removal experiments will examine the effects of adaptive exploration and incomplete observations. The intended contribution is an evaluated retrieval design and an account of its benefits and limitations for professional-network decision support.

**Keywords:** information retrieval; professional networks; knowledge graphs; evidence grounding; decision support.

---

## Status and intended use

This is a research-proposal abstract for supervisor feedback, not an abstract claiming completed experiments or a submission-ready journal article. The proposed adaptive retrieval method has not yet been implemented or evaluated. Existing storage and Graphiti acceptance probes are feasibility evidence only; they do not establish the proposed method's retrieval quality.

Related-work update, 30 September 2026: adaptive graph exploration and missing-evidence feedback already appear in closely related systems. The [framework and evaluation design](search-framework.md) therefore includes adaptive controllers as strong comparisons; novelty remains an open question.

For the supervisor, copy the title and the three abstract paragraphs above. The [Chinese research protocol](research-protocol.md) explains the research questions, methods, evaluation and permissible conclusions. A business benefit or positive experimental result is not assumed.

## Suggested accompanying email

Dear Professor Alahakoon,

Apologies for the delay in sending this through. Drawing on the Ironman communication-assistant project, I have narrowed the proposed research to evidence-grounded, multi-requirement retrieval in professional networks. The aim is to investigate how retrieval can support business goals while making the evidence and unresolved requirements explicit.

I have included a proposed abstract below. Could you please advise whether the scope is appropriate for a first paper, whether to emphasise retrieval-method evaluation or decision-support system design, and what evaluation would be needed for a suitable journal submission?

Best regards,  
Eva
