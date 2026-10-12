# Unipile: cost first, usability second

Research date: 30 September 2026. Decision: Friday, 2 October 2026. Public primary sources only; no signup, account connection, provider API call, private-data upload, or vendor contact was performed. Reliability below is a proposed acceptance test, not a measured result.

## Recommendation

Consider a small, capped trial for LinkedIn and WhatsApp if the recurring floor fits the client's budget. Keep the existing direct Outlook adapter during the pilot. Decide on cost before spending integration time; decide on adoption only after history, recovery, identity consistency, and ordinary client usability pass. Unipile is a hosted dependency even when our Python app and PostgreSQL run locally.

## Cost and billing

Prices exclude VAT; dollars mean USD, not AUD. Each connected LinkedIn profile, WhatsApp number, or mailbox counts separately; contacts are not billed accounts. Outlook/Gmail email plus calendar counts once. Minimum: EUR 49 / USD 55 for up to ten accounts. The 11–50 rate is EUR 5 / USD 5.50 per account. [Official pricing](https://www.unipile.com/pricing-api/)

Assumption: one LinkedIn, one WhatsApp, one Outlook account per user.

| Users | Connected accounts | EUR/month | USD/month |
| ---: | ---: | ---: | ---: |
| 1 | 3 | 49 | 55 |
| 2 | 6 | 49 | 55 |
| 5 | 15 | 75 | 82.50 |
| 10 | 30 | 150 | 165 |
| 25 | 75 | Unconfirmed | 375 from FAQ table |

The 51–200 FAQ table lists EUR 4 / USD 5; its 60-account example instead uses EUR 4.50. Hence no firm EUR quote for 25 users. All endpoints/tools are advertised as included, without add-ons; provider subscriptions are separate expenses. [Pricing](https://www.unipile.com/pricing-api/)

V2 bills the organization's maximum simultaneous connected-account count, across all applications; development accounts count too. Removing accounts after the peak does not reduce that period's bill. Its trial allows ten accounts, and paid organizations can set an account cap to prevent unexpected additions. Calls, webhooks, bandwidth, and data processing do not incur usage charges. [V2 billing](https://developer.unipile.com/v2.0/docs/billing)

The trial is seven days without a card. [Pricing](https://www.unipile.com/pricing-api/) This research did not verify the checkout currency available to an Australian customer, tax treatment, conversion/card fees, or a binding quote. Our total budget also includes our local/server hosting, backups, LLM usage, and implementation/support time. These are project costs, not Unipile's advertised fee.

Keeping Outlook direct means two Unipile accounts per user. That does not reduce the minimum for one or two users; it can delay crossing later account tiers. Calculate the final pilot from the actual connected accounts, including test accounts, rather than the number of app seats.

## Versions, limits, and proxy costs

V2 is explicitly labelled beta; its notice permits breaking changes and temporary interruptions. Pin the version and confirm the supported production choice before implementing. [V2 welcome](https://developer.unipile.com/v2.0/docs/welcome)

V1 and V2 have different account, object, endpoint, pagination, and ID conventions. V2 favors retrieval on demand with caching rather than V1's broad presynchronization. Do not mix snippets from both doc sets. [Migration introduction](https://developer.unipile.com/v2.0/docs/migration-introduction)

An existing customer can transfer the subscription for unified V1/V2 billing at the higher version's peak, rather than their combined counts. Separate subscriptions can produce separate invoices. WhatsApp must reconnect during migration. This project has no Unipile subscription to migrate. [Subscription transfer](https://developer.unipile.com/v2.0/docs/transfer-accounts-subscription)

Unlimited billing usage does not promise unrestricted operation: V2 enforces route/account rate limits and can return `429 api/too_many_requests` before reaching a provider. A provider can independently return `provider/too_many_requests`. Follow retry guidance and observe freshness rather than tight polling. [V2 rate limits](https://developer.unipile.com/v2.0/docs/rate-limits)

Automatic proxies are used for LinkedIn, WhatsApp, and Instagram. Custom proxies are supported; their purchase/operation would be a separate expense if we choose one. Automatic routing normally selects a country based on the user; fallback may use another region. A required automatic proxy cannot simply be disabled. Obtain confirmation of included standard proxy traffic and any dedicated/regional/custom-proxy charges before choosing that configuration. [V2 proxies](https://developer.unipile.com/v2.0/docs/proxys)

## Practical ease and reliability

Hosted Auth handles Microsoft OAuth, WhatsApp QR linking, and LinkedIn sessions/challenges in a redirect flow, reducing the authentication UI and session management we maintain. This is the vendor's documented capability, not evidence that this client can onboard without help. [Authentication on behalf](https://www.unipile.com/developer-auth-on-behalf/)

LinkedIn/WhatsApp use reverse engineering; email/calendar use official interfaces according to Unipile's FAQ. Vendor maintenance is useful, but it cannot establish provider endorsement or eliminate upstream changes and account restrictions. [Pricing FAQ](https://www.unipile.com/pricing-api/)

LinkedIn Recruiter can encounter simultaneous-session prompts; cookie linking may require developer tools or an extension. The vendor also documents provider quotas and WhatsApp restrictions. Start the pilot with existing ordinary inboxes and minimal read operations, rather than outreach. [Provider limits and restrictions](https://developer.unipile.com/docs/provider-limits-and-restrictions)

V1 message retrieval supports webhooks or scheduled polling, with paginated history and overlap plus ID deduplication for recovery. A local-only app can make outbound polling requests without a public inbound endpoint; it still needs internet access. Webhooks require a reachable receiver, so introduce them only if their latency benefit justifies hosting/relay work. V2 must use its own routes and rate limits. [Retrieving messages](https://developer.unipile.com/docs/get-messages), [Retrieving emails](https://developer.unipile.com/docs/retrieving-emails)

WhatsApp requires initial sync in V2. History is partial until completion, and failed sync can leave history incomplete while the account remains usable. Track sync status separately from connection success. The docs themselves describe varying durations; do not promise instant complete history. [Initial sync](https://developer.unipile.com/v2.0/docs/initial-sync)

Security and uptime statements are vendor claims. The published security page advertises SOC 2 Type II and makes France-only/no-outside-EU-transfer claims; we have not inspected its audit report or measured uptime. [Security and compliance](https://www.unipile.com/security-compliance/)

## What changes in this app

Source review: `adapters/envelope.py` defines our canonical `Envelope`; `adapters/store_writer.py` writes it to PostgreSQL; `adapters/outlook/client.py` uses Microsoft Graph; `adapters/linkedin/client.py` uses a logged-in browser's network responses. Unipile should replace the relevant ingestion/auth adapters behind that boundary, preserving the graph, identity resolution, and UI contract. This is an architectural recommendation, not an implemented integration.

Preserve channel identifiers, UTC timestamps, self identity/direction, group participants, names, quoted-body cleanup, and stable thread/message keys. The current store deduplicates by `(channel, external_id)` without an account dimension. Before multi-user ingestion, explicitly resolve account/tenant ownership and isolation. V2 says some messaging IDs are unique only within a chat; use a stable composite/account-aware key and crosswalk existing IDs rather than blindly assigning the returned message ID. [Messaging migration](https://developer.unipile.com/v2.0/docs/migration-messaging-api)

For Outlook, preserve RFC Message-ID semantics across folder moves; the existing Envelope comments explicitly warn that Graph message IDs can change. Unipile's V2 email migration changes ID/header fields, so test interoperability before switching email sources. Running both adapters against a shared store without an ID crosswalk could duplicate existing evidence. [Email migration](https://developer.unipile.com/v2.0/docs/migration-emails-api)

## Data handling to confirm before a real-data pilot

The live privacy policy is dated **28 September 2026**, superseding the earlier 7 September reference. V1 messaging is retained until account deletion; V2 WhatsApp retains encrypted messages/conversations/participants until deletion, while other V2 messaging is transient. V1 Microsoft/IMAP retain metadata; V2 email is transient. Connection tokens persist until account deletion/service end; IMAP credentials are encrypted. [Privacy policy, section 6](https://www.unipile.com/privacy-policy/)

The policy lists French cloud hosting but proxy subprocessors with Israel/EU, US, and Singapore/EU data locations, plus support processing in US/EU. It says proxies route encrypted traffic without reading/storing message content and transient network metadata is not retained. This is broader than the security page's blanket France-only/no-outside-EU wording. Confirm which promise covers hosting, routing, support, and selected pilot configuration; do not present the service as wholly local or France-only. [Privacy policy, sections 6–9](https://www.unipile.com/privacy-policy/), [Security page](https://www.unipile.com/security-compliance/)

## Cheap trial acceptance checklist

These are proposed gates for a later explicitly authorized trial; none has been run.

- [ ] Record the version, invoice currency, tax treatment, account cap, and a maximum acceptable recurring spend before connecting anything. Start with one user's two social/messaging accounts and direct Outlook; add the second user only when ownership isolation is ready.
- [ ] Choose an ordinary active account with the owner's approval and documented history window. Record expected counts/known conversations locally; do not upload the entire database as a test shortcut.
- [ ] Time first connection and one reconnect. Both owners should complete the supported flow with ordinary instructions; record any developer-tool, CAPTCHA, admin, or manual-support requirement.
- [ ] Check a small set of known inbound/outbound and group messages against each provider UI: content, timestamp, participants, and stable source evidence must match. Quantify missing history rather than assuming sync success proves completeness.
- [ ] Import the same window twice: the second run adds zero duplicate messages and changes no unrelated ownership/identity links. Compare existing IDs before any shared-store switch.
- [ ] Pause the app for 24 hours, restart, and verify the missed window is recovered within the agreed polling interval. Test disconnect/reconnect and show stale/incomplete status to the user.
- [ ] Validate pagination and conservative rate handling without intentionally exhausting an account's limits. Measure API errors, freshness delay, retry burden, and client effort over the trial.
- [ ] Exercise the app's relationship/search examples with imported evidence; ingestion success alone is insufficient to prove product usefulness.
- [ ] Confirm deletion/export and account disconnection; verify the final billable peak. Stop or remove the trial connections before a paid continuation unless that continuation is agreed.

Adopt only if the recurring cost is accepted, no material sample evidence is missing, retry/reconnect behavior works, users can operate it, and version/data-location questions are resolved. A short trial can establish pilot fit; it cannot establish long-term service reliability.

## Questions for Unipile, prepared but not sent

1. Which binding EUR and USD prices apply at 15, 30, and 75 connected accounts, and why does the 51–200 table differ from the example? Which billing currencies/taxes apply to an Australian organization?
2. Is the minimum per organization/subscription, and exactly which disconnected/failed/deleted accounts count toward the peak? Can an existing provider identity connected to two applications count twice?
3. Does the quoted plan include automatic proxies, auth, webhooks, history/attachments, and support in both V1 and V2? Are any dedicated proxy, geography, onboarding, or production-support options chargeable?
4. Is V2 still beta for our required LinkedIn/WhatsApp/Outlook features? What stability commitment, V1 support horizon, and migration assistance are offered?
5. What history is actually recoverable for WhatsApp and LinkedIn, including reconnects and long offline periods? What freshness/error/disconnection guarantees or SLA remedies exist per channel?
6. Which routing/support subprocessors and countries apply to our accounts, can geography be fixed without fallback, and how should France-only marketing be interpreted? Provide the current DPA, audit scope, deletion/backup timelines, and incident terms.
7. How do provider IDs remain stable across reconnects, chat/account boundaries, and Outlook folder moves? What exact webhook retry/replay guarantees apply to the chosen version?

## Short reply to Mark

> Hi Mark — two users with three channels each cost EUR 49 / USD 55 monthly before tax. I'd trial LinkedIn/WhatsApp with Outlook direct before committing.

All external links above were accessed on 30 September 2026. Prices and documentation should be rechecked at checkout; the report intentionally leaves conflicting upper-tier EUR pricing unresolved.
