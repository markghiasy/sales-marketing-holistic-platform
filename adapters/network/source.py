"""Read-only, paged source boundary. Never selects quarantined message.raw."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hashlib
import json
from typing import Iterator

import psycopg
from psycopg import sql
from psycopg.rows import dict_row


class SourceError(RuntimeError):
    """Safe diagnostic code, never a database exception or connection string."""


def fingerprint(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str, ensure_ascii=False,
                                     separators=(',', ':')).encode()).hexdigest()


def json_value(value):
    return json.loads(json.dumps(value, default=lambda x: x.isoformat() if isinstance(x, datetime) else str(x)))


@dataclass(frozen=True, order=True)
class Cursor:
    ingested_at: datetime
    id: str


@dataclass(frozen=True)
class SourceRecord:
    kind: str
    id: str
    fingerprint: str
    payload: dict

    @property
    def key(self):
        return self.kind + ':' + self.id


@dataclass(frozen=True)
class SourceBatch:
    records: tuple[SourceRecord, ...]
    cursor: Cursor | None
    manifests: dict[str, frozenset[str]]
    complete_kinds: frozenset[str]
    observed_at: datetime
    binding: str


FIELDS = {
    'person': 'id primary_name created_at merged_into',
    'identity': 'id channel handle display_name person_id is_self',
    'thread': 'id channel external_id title is_group last_message_at',
    'message': 'id thread_id channel external_id direction sent_at from_identity_id subject body_text is_automated ingested_at',
    'organization': 'id canonical_name',
    'fact': 'id subject_identity_id fact_type object_text object_identity_id object_org_id confidence source source_message_id status reason model prompt_version extracted_at reviewed_at',
    'linkedin_connection': 'id first_name last_name profile_url email company position connected_on synced_at',
    'contact_hidden': 'contact_key hidden_at',
}
REQUIRED = frozenset(('person', 'identity', 'thread', 'message', 'message_participant'))


class SourceRepository:
    def __init__(self, dsn: str, *, expected_binding: str | None = None):
        self._dsn = dsn
        self.expected_binding = expected_binding

    @contextmanager
    def connection(self):
        with psycopg.connect(self._dsn, row_factory=dict_row, connect_timeout=10) as conn:
            conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            conn.execute("SET LOCAL statement_timeout = '15s'")
            yield conn

    def _capabilities(self, conn):
        schema = conn.execute('select current_schema() as schema').fetchone()['schema']
        if not schema or schema == 'network':
            raise SourceError('invalid_source_schema')
        columns = {}
        for row in conn.execute('select table_name, column_name from information_schema.columns where table_schema=%s', (schema,)):
            columns.setdefault(row['table_name'], set()).add(row['column_name'])
        if not REQUIRED.issubset(columns):
            raise SourceError('missing_required_table')
        for kind, fields in FIELDS.items():
            if kind in columns and not set(fields.split()).issubset(columns[kind]):
                raise SourceError('missing_required_column')
        if not {'message_id', 'identity_id', 'role'}.issubset(columns['message_participant']):
            raise SourceError('missing_required_column')
        db = conn.execute('select current_database() as name').fetchone()['name']
        params = conn.info.get_parameters()
        binding = fingerprint([params.get('host'), params.get('port'), db, schema])
        if self.expected_binding and self.expected_binding != binding:
            raise SourceError('source_binding_mismatch')
        return schema, columns, binding

    def _read(self, conn, schema, columns, kind, where=sql.SQL('true'), params=(), limit=None, order=None):
        if kind not in columns:
            return []
        fields = FIELDS[kind].split()
        if kind == 'person' and 'preferred_name' in columns[kind]:
            fields.append('preferred_name')
        key = 'contact_key' if kind == 'contact_hidden' else 'id'
        query = sql.SQL('select {} from {} where {} order by {}').format(
            sql.SQL(',').join(map(sql.Identifier, fields)), sql.Identifier(schema, kind), where,
            order or sql.Identifier(key))
        if limit is not None:
            query += sql.SQL(' limit %s')
            params = (*params, limit)
        rows = list(conn.execute(query, params))
        if kind == 'message' and rows:
            participants = {}
            for p in conn.execute(sql.SQL('select message_id,identity_id,role from {} where message_id=ANY(%s) order by identity_id,role').format(sql.Identifier(schema, 'message_participant')), ([r['id'] for r in rows],)):
                participants.setdefault(str(p['message_id']), []).append({'identity_id': str(p['identity_id']), 'role': p['role']})
            for row in rows:
                row['participants'] = participants.get(str(row['id']), [])
        result = []
        for row in rows:
            payload = json_value(row)
            result.append(SourceRecord(kind, str(row[key]), fingerprint(payload), payload))
        return result

    def snapshot_pages(self, page_size: int = 500) -> Iterator[SourceBatch]:
        if not 1 <= page_size <= 5000:
            raise ValueError('page_size must be 1..5000')
        with self.connection() as conn:
            schema, columns, binding = self._capabilities(conn)
            at = datetime.now(UTC)
            manifests, watermark = {}, None
            for kind in FIELDS:
                ids, last = set(), None
                key = 'contact_key' if kind == 'contact_hidden' else 'id'
                while kind in columns:
                    where = sql.SQL('{} > %s').format(sql.Identifier(key)) if last else sql.SQL('true')
                    rows = self._read(conn, schema, columns, kind, where, (last,) if last else (), page_size)
                    if not rows:
                        break
                    ids.update(r.id for r in rows)
                    if kind == 'message':
                        for r in rows:
                            c = Cursor(datetime.fromisoformat(r.payload['ingested_at']), r.id)
                            watermark = max(watermark, c) if watermark else c
                    yield SourceBatch(tuple(rows), None, {}, frozenset(), at, binding)
                    last = rows[-1].id
                # An absent optional table is an authoritative empty source kind.
                manifests[kind] = frozenset(ids)
            yield SourceBatch((), watermark, manifests, frozenset(FIELDS), at, binding)

    def incremental(self, cursor: Cursor | None, lookback_seconds: int = 300, limit: int = 500) -> SourceBatch:
        if not 2 <= limit <= 5000 or not 0 <= lookback_seconds <= 86400:
            raise ValueError('invalid incremental bounds')
        with self.connection() as conn:
            schema, columns, binding = self._capabilities(conn)
            forward_limit = limit if cursor is None or not lookback_seconds else (limit + 1) // 2
            where = sql.SQL('(ingested_at,id) > (%s,%s)') if cursor else sql.SQL('true')
            params = (cursor.ingested_at, cursor.id) if cursor else ()
            rows = self._read(conn, schema, columns, 'message', where, params, forward_limit,
                              sql.SQL('ingested_at,id'))
            next_cursor = cursor
            for row in rows:
                c = Cursor(datetime.fromisoformat(row.payload['ingested_at']), row.id)
                next_cursor = max(next_cursor, c) if next_cursor else c
            if cursor and lookback_seconds:
                # Separate replay allowance cannot starve forward progress. Full reconciliation
                # guarantees recovery for older late commits outside this bounded window.
                rows += self._read(conn, schema, columns, 'message',
                                   sql.SQL('ingested_at >= %s and (ingested_at,id) <= (%s,%s)'),
                                   (cursor.ingested_at-timedelta(seconds=lookback_seconds), cursor.ingested_at, cursor.id),
                                   limit-forward_limit, sql.SQL('ingested_at desc,id desc'))
            return SourceBatch(tuple(rows), next_cursor, {}, frozenset(), datetime.now(UTC), binding)

    def metadata(self) -> SourceBatch:
        with self.connection() as conn:
            schema, columns, binding = self._capabilities(conn)
            kinds = frozenset(FIELDS)-{'message'}
            rows = tuple(r for kind in sorted(kinds) for r in self._read(conn, schema, columns, kind))
            manifests = {kind: frozenset(r.id for r in rows if r.kind == kind) for kind in kinds}
            return SourceBatch(rows, None, manifests, kinds, datetime.now(UTC), binding)

    def validate(self, dependencies: dict[str, str]) -> bool:
        with self.connection() as conn:
            schema, columns, _ = self._capabilities(conn)
            grouped = {}
            for key, expected in dependencies.items():
                kind, record_id = key.split(':', 1)
                if kind not in FIELDS:
                    return False
                grouped.setdefault(kind, {})[record_id] = expected
            for kind, expected in grouped.items():
                key = 'contact_key' if kind == 'contact_hidden' else 'id'
                # Text cast permits heterogeneous UUID/text ids; validation is bounded by selected evidence.
                rows = self._read(conn, schema, columns, kind, sql.SQL('{}::text=ANY(%s)').format(sql.Identifier(key)), (list(expected),))
                actual = {r.id: r.fingerprint for r in rows}
                if any(actual.get(k, 'absent') != v for k, v in expected.items()):
                    return False
            return True

    def audit(self) -> dict:
        with self.connection() as conn:
            schema, columns, binding = self._capabilities(conn)
            identities = self._read(conn, schema, columns, 'identity', sql.SQL('is_self'))
            if not identities:
                raise SourceError('owner_unresolved')
            people = {r.id: r.payload for r in self._read(conn, schema, columns, 'person')}
            owners = set()
            for identity in identities:
                person_id, seen = identity.payload['person_id'], set()
                while person_id and people.get(person_id, {}).get('merged_into'):
                    if person_id in seen:
                        raise SourceError('identity_cycle')
                    seen.add(person_id)
                    person_id = people[person_id]['merged_into']
                owners.add('person:'+person_id if person_id else 'identity:'+identity.id)
            owner_id = owners.pop() if len(owners) == 1 else 'owner:'+binding[:24]
            counts = {kind: conn.execute(sql.SQL('select count(*) as n from {}').format(sql.Identifier(schema, kind))).fetchone()['n'] for kind in FIELDS if kind in columns}
            return {'binding': binding, 'owner_id': owner_id, 'self_identity_count': len(identities), 'counts': counts,
                    'capabilities': sorted(k for k in FIELDS if k in columns), 'source_mode': 'real'}
