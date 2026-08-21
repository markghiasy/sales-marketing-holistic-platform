"""The envelope every channel normalises to before it touches the store (build plan §6).

Vendor payloads stop at the adapter. Nothing past this module may reference a
Graph field name, an aggregator's JSON shape, or a LinkedIn identifier —
only this dataclass. Swapping an aggregator is a few days of work here; if
that boundary gets blurred anywhere downstream, it's a rewrite instead.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class Channel(str, Enum):
    outlook = "outlook"
    whatsapp = "whatsapp"
    linkedin = "linkedin"


class Direction(str, Enum):
    inbound = "inbound"
    outbound = "outbound"


@dataclass
class Envelope:
    channel: Channel
    external_id: str            # stable per-channel identifier — see the
                                 # Outlook idempotency warning below before
                                 # choosing this for a new channel
    thread_external_id: str     # Graph conversationId | chat id | conversation id
    direction: Direction        # computed against the self-identity table at
                                 # ingest, stored — not derived downstream
    sent_at: datetime           # UTC; conversion happens at the adapter
    from_handle: str            # normalised: email lowercased, phone E.164,
                                 # LinkedIn member id
    to_handles: list[str] = field(default_factory=list)   # groups produce many
    from_display_name: str | None = None  # best-effort human-readable name —
                                           # not in the original §6 field
                                           # list, added because every
                                           # channel actually has this and
                                           # the graph is unreadable
                                           # without it (identity.handle is
                                           # a URL/phone/email, not a name)
    to_display_names: list[str | None] = field(default_factory=list)  # parallel
                                           # to to_handles, same index —
                                           # use None for "no name", not
                                           # "" (an empty-string name
                                           # would pass a SQL `is not
                                           # null` check and permanently
                                           # block a real name from ever
                                           # being backfilled later — see
                                           # store_writer.py's defensive
                                           # normalisation, added after
                                           # this exact bug was found in
                                           # the Outlook adapter)
    subject: str | None = None  # Outlook only. Leave None elsewhere — don't
                                 # synthesise one
    body_text: str = ""         # plain text, quoted-reply chains stripped
    is_group: bool = False      # a commitment in a group chat is weaker
                                 # evidence than one in a 1:1 — matters
                                 # downstream in action extraction
    is_automated: bool = False  # set by parser tier 1 at ingest (§9), not here
    raw: dict = field(default_factory=dict)  # original payload, quarantined
                                              # for debugging. nothing
                                              # downstream reads this field


# Outlook idempotency — this one will bite if it's missed (build plan §6):
#
# Graph message `id` values are NOT stable across folder moves. Archive a
# message, or let a rule file it, and the same message reappears under a
# new id — so a naive UNIQUE(channel, external_id) on Graph's `id` silently
# duplicates the mailbox over time. Reciprocity scores go quietly wrong
# weeks later.
#
# Key on `internetMessageId` (the RFC 5322 Message-ID) instead: stable
# across moves, stable across mailboxes, and re-running a full backfill
# adds exactly zero rows. Keep Graph's `id` alongside for API calls; don't
# key on it.
