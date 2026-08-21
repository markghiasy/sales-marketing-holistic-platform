"""The one place that writes an Envelope into the store. Every adapter
(Outlook, WhatsApp, LinkedIn, ...) calls this — it's what got the
message_participant fix during Block A testing; that fix should only ever
need to exist in one place.
"""

from __future__ import annotations

import psycopg

from .envelope import Envelope


def upsert(conn: psycopg.Connection, env: Envelope, self_handle: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            insert into thread (channel, external_id, is_group)
            values (%s, %s, %s)
            on conflict (channel, external_id) do nothing
            returning id
            """,
            (env.channel.value, env.thread_external_id, env.is_group),
        )
        row = cur.fetchone()
        if row is None:
            cur.execute(
                "select id from thread where channel = %s and external_id = %s",
                (env.channel.value, env.thread_external_id),
            )
            row = cur.fetchone()
        thread_id = row[0]

        from_identity_id = _get_or_create_identity(
            cur, env.channel.value, env.from_handle, self_handle, env.from_display_name
        )

        cur.execute(
            """
            insert into message
                (thread_id, channel, external_id, direction, sent_at,
                 from_identity_id, subject, body_text, raw)
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            on conflict (channel, external_id) do nothing
            returning id
            """,
            (
                thread_id, env.channel.value, env.external_id, env.direction.value,
                env.sent_at, from_identity_id, env.subject, env.body_text,
                psycopg.types.json.Json(env.raw),
            ),
        )
        row = cur.fetchone()
        message_already_existed = row is None

        # Always resolve/update the "to" identities — even when the
        # message itself already existed — so a re-run (e.g. backfilling
        # display_name onto old data, which is exactly what happened
        # twice this session) still updates names for contacts who were
        # only ever a recipient, never a sender. Found while
        # self-reviewing before the first git push: the earlier version
        # returned immediately on an existing message, before this loop
        # ran at all, so a "to"-only contact's name could never be
        # backfilled on re-run.
        to_identity_ids = [
            _get_or_create_identity(
                cur, env.channel.value, to_handle, self_handle,
                env.to_display_names[i] if i < len(env.to_display_names) else None,
            )
            for i, to_handle in enumerate(env.to_handles)
        ]

        if message_already_existed:
            # message_participant rows were already recorded on first
            # insert — only the identity upserts above needed re-running
            return
        message_id = row[0]

        # message_participant IS the graph's edge table (§10) — populate it
        # at ingest time, not deferred to Block B
        cur.execute(
            "insert into message_participant (message_id, identity_id, role) "
            "values (%s, %s, 'from') on conflict do nothing",
            (message_id, from_identity_id),
        )
        for to_identity_id in to_identity_ids:
            cur.execute(
                "insert into message_participant (message_id, identity_id, role) "
                "values (%s, %s, 'to') on conflict do nothing",
                (message_id, to_identity_id),
            )


def _get_or_create_identity(
    cur, channel: str, handle: str, self_handle: str, display_name: str | None = None
) -> str:
    # defensive: an empty string is "not null" in SQL, so it would satisfy
    # the `is not null` guard below and permanently block a real name from
    # ever being backfilled later (found in the Outlook adapter, which
    # used to pass "" instead of None for missing names — fixed there too,
    # but this is the one place all channels funnel through)
    display_name = display_name or None
    cur.execute(
        """
        insert into identity (channel, handle, is_self, display_name)
        values (%s, %s, %s, %s)
        on conflict (channel, handle) do update
            set display_name = excluded.display_name
            where identity.display_name is null and excluded.display_name is not null
        """,
        (channel, handle, handle == self_handle, display_name),
    )
    cur.execute(
        "select id from identity where channel = %s and handle = %s",
        (channel, handle),
    )
    return cur.fetchone()[0]
