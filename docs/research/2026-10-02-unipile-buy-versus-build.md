# Unipile: alternatives and buy-versus-build assessment

Assessed 2 October 2026. Public prices are snapshots, not quotes. USD is not AUD; listed subscription comparisons exclude tax, our infrastructure and AI usage. This assessment does not authorize a subscription or migration.

## Decision

For a small deployment needing LinkedIn, WhatsApp and Outlook together, no materially cheaper like-for-like hosted replacement was established in this review. Cheaper single-channel and self-hosted options exist, but leave substantial integration and operations work with us. Unipile's strongest incremental value is LinkedIn live ingestion/profile enrichment and outsourcing connector maintenance. It does not replace our identity resolution, evidence model, knowledge graph or strategic retrieval.

Continue a bounded pilot. Keep the existing adapters as alternatives behind the application boundary; prioritize LinkedIn evaluation. Retain direct Outlook integration unless there is a measured operational reason to replace it. Do not claim improved ban safety, complete history or long-term reliability from a short trial.

## Published costs and comparability

| Option | Public price | Fit and limitations |
|---|---|---|
| Unipile | EUR49 / USD55 per month total up to 10 linked accounts; 11–50 at USD5.50 each | Unified messaging/email/calendar API. Each channel identity counts separately. [Price](https://www.unipile.com/pricing-api/) |
| LinkupAPI | USD55 up to 10; USD5.50 each at 11–50; USD5 at 51–200; USD4.50 at 201–640; USD3,000 unlimited | Current price page advertises LinkedIn, Gmail, Outlook, WhatsApp and webhooks. Small-scale price is not lower. No live verification of historical inbox completeness or recovery. [Price](https://linkupapi.com/pricing) |
| Linked API | Core USD69 per LinkedIn seat monthly; USD49/month equivalent annually | LinkedIn-only; not cheaper for this multi-channel requirement. [Price](https://linkedapi.io/pricing), [vendor's monthly/annual breakdown](https://linkedapi.io/vs/dripify) |
| GREEN-API | Business USD12/month advertised | WhatsApp portion only. Pre-connection history retrieval is documented with configuration/reauthorization steps, limited to history supplied by WhatsApp; no established complete lifetime archive. [Price](https://green-api.com/en), [history behavior](https://green-api.com/en/docs/api/journals/GetChatHistory/) |
| WAHA | Current site advertises free open-source software | Self-hosted WhatsApp only; hosting, operations and implementation remain ours. Site explicitly cautions it is not entirely safe from platform restrictions. [Official site](https://waha.devlike.pro/) |
| Existing application adapters | No new aggregator subscription | Not zero total cost: maintenance, hardware/hosting, monitoring and recovery remain ours. Code evidence below. |

LinkupAPI's current official price page explicitly says no credits/per-call fees. Unipile's comparison page still describes older USD29/150 credit plans. Use the vendor's current price page, not a competitor's pricing description. LinkupAPI's own prose says its unlimited tier becomes cheaper around 640 accounts, but USD3,000 / USD4.50 is about 667 accounts; do not present the marketing threshold as exact arithmetic. [LinkupAPI current price](https://linkupapi.com/pricing), [conflicting Unipile comparison](https://www.unipile.com/linkupapi-alternative/)

## Cost for this deployment

Each person connecting one LinkedIn, one WhatsApp and one Outlook identity consumes three linked accounts. Under **one billing subscription**, the USD examples are:

| People | Linked accounts | Monthly subscription |
|---:|---:|---:|
| 1 | 3 | 55 |
| 2 | 6 | 55 |
| 3 | 9 | 55 |
| 5 | 15 | 82.50 |
| 10 | 30 | 165 |

These are calculations from the published USD tiers, not prices per end user. Separate vendor subscriptions can each incur the minimum; do not assume independent installations share billing or authorize pooled communication data. More contacts or messages do not themselves increase the published subscription, although storage, enrichment throughput and model costs increase. Billing is based on peak simultaneous linked accounts. The EUR51–200 table and its worked example disagree; obtain a quote before relying on that tier. [Pricing](https://www.unipile.com/pricing-api/)

Keeping Outlook direct does not reduce a USD55 floor while still within ten accounts. It can nevertheless reduce migration work and third-party processing. At 10 people, changing from three vendor accounts each (30) to LinkedIn+WhatsApp only (20) changes the subscription from USD165 to USD110, provided both cases use the published 11–50 tier under one subscription.

## Comparison with code actually present

Inspected `ironman/repo/adapters` source; these are code capabilities, not fresh runtime acceptance tests, and worktree/deployment versions may differ.

- LinkedIn: `linkedin/client.py` uses Playwright; `linkedin/config.py` defaults to four sessions/day and bounds pages/scrolling. `linkedin/export_sync.py` imports connection fields including company and position. The inspected path is not equivalent to a managed profile-enrichment API. Unipile documents richer user data and account/message events. [User retrieval](https://developer.unipile.com/docs/retrieving-users), [features](https://developer.unipile.com/docs/list-provider-features)
- WhatsApp: `whatsapp/node/ingest.js` already handles `messages.upsert` and `messaging-history.set` through Baileys. Real-time receipt is therefore not a capability unique to Unipile. Its potential benefit is maintained API coverage and reduced protocol/session operations, not a demonstrated speed win against our live connector.
- Outlook: `outlook/client.py` and `outlook/sync.py` already use Microsoft Graph and per-folder delta cursors. Unipile's incremental value is managed auth/unified API rather than a fundamentally new data source. This review does not certify the checked-out folder coverage as the latest deployed version.
- `adapters/envelope.py` already defines the normalization boundary and `store_writer.py` persists stable source identities. Replacing a connector should preserve provider identifiers and idempotency, not reimplement graph logic around vendor-specific IDs.

Unipile can supply richer evidence, but cannot turn a self-reported profile skill into verified delivery competence, infer a relationship solely from a shared company, or replace identity review. Strategy search, graph updates, summaries and labels remain application work. A connector replacement alone does not fix the previously observed 77-second strategic answer.

## Evidence strength and remaining cost

The [local trial assessment](2026-10-02-unipile-live-trial-assessment.md) records one successfully delivered new test message per channel, paginated reads, older-history existence checks and an Outlook attachment matching the original hash. It does not establish history completeness, sustained delivery reliability, outage recovery or lower account-ban rates. LinkedIn profile enrichment is documented, not yet verified on a representative contact sample.

Total decision cost is subscription + integration amortization + maintenance + monitoring/reconciliation + any durable webhook relay + migration/exit effort. Avoided engineering hours are a legitimate benefit, but have not yet been measured. As a hypothetical only, at USD50/hour, a USD55 subscription equals 1.1 hours/month before those additional costs; this is not an estimate of actual savings or the user's labor rate.

Before rollout, compare representative history against known local records, verify identity/attachment fidelity, test reconnect and missed-event recovery, and resolve provider-side activity controls. Local laptops can go offline; webhook receipt alone is not an offline backlog/reconciliation design. Do not run two active LinkedIn collectors indiscriminately during comparison, since both contribute account activity.

The [security assessment](2026-10-02-unipile-security-and-platform-risk.md) remains separate: buying hosted connectors transfers some maintenance work, not all account risk or data-custody obligations.
