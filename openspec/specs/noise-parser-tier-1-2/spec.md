# noise-parser-tier-1-2 Specification

## Purpose
TBD - created by archiving change noise-parser-tier-1-2. Update Purpose after archive.
## Requirements
### Requirement: is_automated is persisted at ingest
`store_writer.upsert` SHALL include `is_automated` in the `insert into
message` statement, using the value already computed on the `Envelope`.

#### Scenario: An envelope with is_automated=True is ingested
- **WHEN** `store_writer.upsert` is called with an `Envelope` whose
  `is_automated` field is `True`
- **THEN** the resulting `message` row's `is_automated` column is `True`

#### Scenario: An envelope with is_automated=False is ingested
- **WHEN** `store_writer.upsert` is called with an `Envelope` whose
  `is_automated` field is `False`
- **THEN** the resulting `message` row's `is_automated` column is `False`

### Requirement: Outlook tier 1 detects List-Unsubscribe headers
`adapters.outlook.sync._to_envelope` SHALL set `is_automated = True` when
the message's `internetMessageHeaders` contains a header named
`List-Unsubscribe` (case-insensitive), regardless of the header's value.

#### Scenario: Message carries a List-Unsubscribe header
- **WHEN** a raw Outlook message's `internetMessageHeaders` includes an
  entry named `List-Unsubscribe`
- **THEN** the resulting `Envelope.is_automated` is `True`

#### Scenario: Message has no List-Unsubscribe header and no other tier-1 signal
- **WHEN** a raw Outlook message has no `List-Unsubscribe` header, a Graph
  `inferenceClassification` other than `"other"`, and a sender not matching
  any known automated pattern or domain
- **THEN** the resulting `Envelope.is_automated` is `False`

### Requirement: Outlook tier 1 detects no-reply / bulk sender patterns
`_to_envelope` SHALL set `is_automated = True` when the sender's local-part
(the substring before `@` in `from_handle`) case-insensitively matches one
of: `noreply`, `no-reply`, `donotreply`, `do-not-reply`, `notifications`,
`notification`, `alerts`, `alert`, `mailer-daemon`, `postmaster`.

#### Scenario: Sender local-part matches a known automated pattern
- **WHEN** a message's `from_handle` is `noreply@example.com`
- **THEN** the resulting `Envelope.is_automated` is `True`

#### Scenario: Sender local-part does not match any pattern
- **WHEN** a message's `from_handle` is `eric.tham@example.com`
- **THEN** this rule alone does not set `is_automated` to `True`

### Requirement: Outlook tier 1 detects known automated domains
`_to_envelope` SHALL set `is_automated = True` when the sender's domain
(the substring after `@` in `from_handle`, case-insensitive) is in a
documented seed list of known automated/ESP domains.

#### Scenario: Sender domain is a known automated domain
- **WHEN** a message's `from_handle` domain matches an entry in the known
  automated domains list
- **THEN** the resulting `Envelope.is_automated` is `True`

### Requirement: Tier 1 signals combine with OR
`is_automated` SHALL be `True` if any one of the tier 1 signals (Graph
classification, List-Unsubscribe header, sender pattern, sender domain)
is `True`, and `False` only when none are.

#### Scenario: Only one signal fires
- **WHEN** a message's Graph `inferenceClassification` is `"other"` but no
  other tier-1 signal matches
- **THEN** the resulting `Envelope.is_automated` is `True`

### Requirement: Tier 2 reply-signal lookup by contact
The system SHALL provide `adapters.reply_signal.reply_signal(cur,
contact_key)` returning the sender's `sent_count`, `received_count`,
`reciprocity_ratio`, and `last_contact_at` as read from the existing
`contact_stats`/`contact_reciprocity` views, with all fields `None` when
the contact has no message history.

#### Scenario: Contact with message history
- **WHEN** `reply_signal` is called with a `contact_key` present in
  `contact_stats`
- **THEN** it returns that contact's real `sent_count`, `received_count`,
  `reciprocity_ratio`, and `last_contact_at` values

#### Scenario: Contact with no message history
- **WHEN** `reply_signal` is called with a `contact_key` not present in
  `contact_stats`
- **THEN** it returns an object with all fields `None`, not an error

