# Unipile V1: data security and platform restriction risk

Reviewed 2 October 2026. Scope: own-account Outlook, LinkedIn and WhatsApp ingestion, plus proposed LinkedIn profile enrichment. Public primary-source review and the separately documented small live ingestion trial; not an independent security audit, contractual opinion or measured ban-rate study.

## Decision

Unipile is technically promising, but our successful message and webhook tests establish functionality only. They do not demonstrate that accounts will remain unrestricted, that historical coverage is complete, or that the vendor's security controls operate as advertised. Continue a bounded pilot; do not describe the service as ban-proof or production-security approved.

Two different questions must remain separate:

- **Data security:** who can process the messages and credentials, where copies exist, how access is controlled, and what happens on deletion or breach.
- **Platform permission and enforcement:** whether the upstream platform permits the access method and might restrict a session, feature or account.

## Data security findings

Unipile's security page claims SOC 2 Type II, CASA Tier II, AES-256-GCM storage encryption, TLS, internal MFA, restricted production access and annual penetration tests. Reports and a DPA are offered on request. We have not inspected their scope, dates, exceptions, or the penetration-test results. SOC 2 is not platform authorization. [Security documentation](https://www.unipile.com/security-compliance/)

The English privacy policy is dated **28 September 2026**; older local notes referencing 7 September should not be treated as the current revision. It states:

- V1 messaging stores messages, conversations and participants until account deletion.
- V1 Microsoft/IMAP stores metadata, not email bodies; authenticated access is still required to process bodies.
- Session tokens are retained encrypted; Microsoft authentication uses external OAuth.
- Customer API data is not used for the vendor's own purposes or sold.
- Subprocessors include France-based hosting and proxy services with Israel, US and Singapore locations. Proxy content is described as encrypted in transit and not decrypted by those proxies.

The security page's blanket EU-only wording needs reconciliation with these disclosures. This is a documentation-scope issue, not evidence that proxy providers read plaintext messages. Request the actual account-specific processing locations and deletion schedule, including backups. [Privacy policy, sections 6–10](https://www.unipile.com/privacy-policy/)

Engineering implications:

1. Local application deployment does not keep all data local once a cloud aggregator is connected.
2. WhatsApp transport encryption does not make authorised endpoint exports unreadable to this integration: the tested API and webhook return readable content. Protect every new downstream copy.
3. Our temporary trial also adds Cloudflare as a relay and stores event payloads in a local SQLite file. It has an independent secret, account allowlist and expiry. This is not a production security architecture; payload retention and cleanup require their own policy.
4. An API key or session token can be sensitive even without a password. Keep it server-side and outside source control, isolate installations, rotate on exposure, and verify revocation.

The V1 API guide warns that its keys carry broad privileges. Microsoft's setup guide requests `Mail.ReadWrite`, `Mail.Send` and `Mail.Read`: read-only application behavior does **not** prove read-only granted permissions. We have not audited the scopes of this specific connected account. Ask whether an ingestion-only configuration can omit write/send permissions. [V1 API authentication](https://developer.unipile.com/docs/api-usage) · [Microsoft OAuth configuration](https://developer.unipile.com/docs/microsoft-oauth)

## Platform restriction findings

Unipile's FAQ identifies Outlook/email access as official API integration and LinkedIn/WhatsApp access as reverse-engineered. A unified API does not erase this difference. [Official API disclosure, FAQ 08](https://www.unipile.com/pricing-api/)

| Channel | Evidence | Decision implication |
|---|---|---|
| Outlook | Microsoft Graph/OAuth integration documented by Unipile | Focus on consent, least privilege, tenant policy, throttling and token lifecycle. It does not have the same unofficial-access issue as the two messaging connectors. |
| LinkedIn | LinkedIn prohibits third-party scraping/automation and describes account restrictions | No assurance of platform approval or exemption for own-account ingestion. Profile enrichment needs separate scrutiny. |
| WhatsApp | WhatsApp warns that linking unofficial apps/sites can lead to temporary or permanent bans | Successful pairing or receiving messages does not eliminate account risk. |

Sources: [Microsoft integration](https://developer.unipile.com/docs/microsoft-oauth), [LinkedIn automated activity](https://www.linkedin.com/help/linkedin/answer/a1340567/automated-activity-on-linkedin?lang=en), [WhatsApp linked-device policy](https://faq.whatsapp.com/378279804439436/).

Distinguish an expired session requiring login, a 429 throttling response, a temporary feature restriction, and an account suspension. They require different recovery and incident reporting. Do not count every disconnect as a ban or dismiss an actual restriction as normal reconnect churn.

### Inbox ingestion and profile enrichment have different exposure

V1 documentation says messaging history is synchronised server-side. Profile retrieval acts against the provider and the guidance of roughly 100 profile visits/day is explicitly a recommendation, not an enforced safe ceiling. This is **not** a promise that using fewer than that number complies with LinkedIn policy or prevents restriction. [V1 provider restrictions](https://developer.unipile.com/docs/provider-limits-and-restrictions)

V2 documents enforced request limits but still distinguishes provider-side throttling; that feature cannot be assumed for V1, and rate limiting is not permission to automate. [V2 rate limits](https://developer.unipile.com/v2.0/docs/rate-limits)

For this product, do not immediately enrich the entire address book. Evaluate a small, user-selected set; cache permitted results, refresh only when useful, and stop on platform warnings/restrictions. These measures limit activity and operational exposure; they do not constitute a platform-approved exemption. Read-only ingestion avoids outreach-related behavior, but still uses an authenticated automated session.

The existing LinkedIn browser workflow and WhatsApp Baileys bridge already involve unofficial-access considerations. There is no matched evidence here that Unipile has a lower ban rate than those implementations. Moving to Unipile outsources maintenance and adds a processor; it does not transfer ownership of account consequences.

## Contract and evidence gaps

Unipile's terms prohibit using the service in violation of upstream providers' terms. They also disclaim uninterrupted/error-free/secure operation and exclude standard SLA commitments unless separately agreed. No specific protection against upstream account bans was established in this review. Ask the vendor to reconcile the supported use case with those obligations in writing. A service-availability SLA would not automatically compensate for a platform account ban. [Terms, sections 6 and 8](https://www.unipile.com/terms-of-use/)

No defensible numerical ban probability was found. Meaningful vendor evidence would need denominators, observation duration, channels, ingest-only versus outreach/profile-enrichment workloads, and separation of session expiry from restrictions. Testimonials and a few successful tests cannot supply that evidence.

## Questions ready for Unipile support — not sent

1. For V1 own-account inbox ingestion with no automated outbound activity, what provider authorisation or contractual basis applies to LinkedIn and WhatsApp? Are there written account-restriction commitments or exclusions?
2. Can you provide observed restriction rates for ingestion-only customers separately from outreach and profile enrichment, with sample sizes, observation windows and definitions?
3. Which V1 limits are enforced automatically, especially profile retrieval, and which remain the integrator's responsibility? What stop/reconnect behavior occurs on a provider warning?
4. Please provide the current SOC 2 Type II report, scope/period, relevant exceptions, penetration-test summary and DPA.
5. For our actual V1 configuration, where are content, attachments, tokens, logs and backups processed/stored? Which subprocessors and proxy locations apply? How do these reconcile with the EU-only security-page wording?
6. Can email ingestion use read-only OAuth scopes and a suitably restricted API key? What isolation and key-rotation options exist in V1?
7. What exactly happens when an account is disconnected, deleted, or the trial expires? Include backup deletion, session revocation and breach-notification commitments. Can you confirm contractually that customer communication data is not used for model training?

## Suggested wording for the stakeholder

> The technical tests are promising, but data security and platform-account risk are separate. Unipile publishes SOC 2 Type II and encryption controls, which still need document-level review. Outlook uses official Microsoft APIs; LinkedIn and WhatsApp use reverse-engineered access, so I cannot claim they are ban-free. Our ingestion-only use avoids outreach activity, but that does not remove platform-policy risk. I recommend continuing the limited pilot while confirming retention, permissions, subprocessors and the vendor's position on account restrictions. LinkedIn profile enrichment should be evaluated separately before scaling it across contacts.

This research did not send messages, contact Unipile, change account connections or expand profile harvesting.
