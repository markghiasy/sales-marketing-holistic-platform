# Strategic profile and opportunity map experiment

This local demo adds a commercial lens to the existing network, using authored fictional source messages. It does not ingest customer profiles or scrape LinkedIn.

## Try it

Open http://127.0.0.1:5055/inbox and use the existing search field:

> I want to bring an AI security product into the logistics market. Who has a pilot need, who could be a channel partner, what decision roles are recorded, and what should I validate before approaching them?

Supported simple searches retain quick results. Other questions hand off once to Claude after the user presses Search. Typing does not call Claude. The answer includes an opportunity map, requirements, sources and next questions. Dashed links are query matches, not permanent relationships or verified eligibility. Suggested requirements are marked. The map is a bounded explanation; omitted evidence stays explicit.

In Network, select Alex Morgan, Atlas Logistics or Harbour expansion and scroll the inspector to Strategic profile. Inspect authored needs, evaluation roles and constraints. The author of a company statement is not automatically its subject. Source and review lets you correct the subject, confirm or reject a record. Extract draft assertions with Claude creates pending proposals from synthetic messages only. Proposals cannot support answers until reviewed.

Reviews are append-only events in local demo memory with version checks. Their time is propagated to the graph; older knowledge dates preserve the previous state. Reset/restart restores the authored fixture. This is an experiment, not production persistence or a full document-upload workflow.

## Verification and limitations

Profile tests cover exact quotes, existing entities, dates, source authorship, history, rejected/pending exclusion and review revisions. Integration tests cover organization ownership, atomic failed extraction, shared paid-call limits, stale edits and graph-local coverage. Browser tests cover one-shot search handoff, source escaping, mobile maps, corrections, extraction errors and a delayed response racing with an SSE refresh.

Live artifact: [strategy-live-smoke.json](../research/network-demo/strategy-live-smoke.json). One extraction produced six pending proposals; commercial strategy answers were also exercised. Earlier output is retained. The final prompt distinguishes explicit/suggested requirements and attributed statements; the focused graph omits unrelated adjacent-role results. These smoke cases do not measure accuracy or prove business value. Mechanical quotation/citation checks cannot prove a generated interpretation is true; human review and real-data evaluation remain necessary.

The current 1-3 hop control still counts graph edges. The separate four-scope relationship UX was researched in this session and is not yet implemented; see the relationship-scope research report. Do not interpret hop count or owner communication activity as familiarity with an intermediary.

Final local verification: **469 passed, zero skipped, including 17 browser cases**. Scoped Ruff and independent re-review passed.

Known generative limitation observed in the live artifact: the advisory summary can group occupational functions under decision roles even though only a scoped decision_role assertion establishes that role. Use source excerpts and typed profile fields as the evidence lane; this experiment does not certify strategic eligibility.

A user request was interrupted around the local server restart. Replaying that exact synthetic Cybertest request against port 5055 returned HTTP 200 in 24.7 seconds, with a 12-node graph. Network disconnects now retain the question and explain manual retry; no automatic paid retry is performed. The additional browser regression reproduces a connection reset.

After the disconnect-message change, all six strategic browser tests passed (18.74 seconds), including the new connection-reset case. The earlier full-suite run remains 469 passed; it preceded this added test.
