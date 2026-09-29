"""Transactional PostgreSQL derived state, with a restricted writer role."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
import time

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .source import Cursor, SourceBatch, SourceRecord, SourceRepository, fingerprint

WRITER = 'ironman_network_writer'
SECTIONS = {'node':'nodes', 'claim':'claims', 'evidence':'evidence', 'message':'messages',
            'profile':'profile_assertions', 'strategy':'strategic_assertions', 'work':'work_records'}


class StoreError(RuntimeError):
    pass


@dataclass(frozen=True)
class Snapshot:
    version: int
    data: dict
    dependencies: dict[str, str]


@dataclass(frozen=True)
class NetworkStatus:
    version: int
    last_success_at: datetime | None
    source_checked_at: datetime | None
    error_code: str | None


@dataclass(frozen=True)
class Projection:
    entities: tuple[dict, ...]
    assertions: tuple[dict, ...]
    evidence: tuple[dict, ...]
    dependencies: dict[str, tuple[str, ...]]
    messages: tuple[dict, ...] = ()
    profiles: tuple[dict, ...] = ()
    strategies: tuple[dict, ...] = ()
    work: tuple[dict, ...] = ()
    affected_ids: tuple[str, ...] | None = None
    owner_id: str | None = None

    def sections(self):
        return dict(zip(SECTIONS, (self.entities, self.assertions, self.evidence, self.messages,
                                   self.profiles, self.strategies, self.work)))


def entity_ids(kind, row):
    if kind == 'node':
        if row.get('kind') not in ('person','organization','project') or not row.get('name'):
            raise ValueError('invalid_entity')
        return [row['id']]
    result = [row[k] for k in ('source','target','subject_id','claimant_id','context_id','contact_id','person_id','project_id','author_id') if row.get(k)]
    return sorted(set(result + row.get('entity_ids', []) + row.get('participant_ids', [])))


class PostgresNetworkStore:
    def __init__(self, dsn: str, binding: str):
        self._dsn, self.binding = dsn, binding

    def initialize(self):
        audit = SourceRepository(self._dsn, expected_binding=self.binding).audit()
        with psycopg.connect(self._dsn, row_factory=dict_row, connect_timeout=10) as conn:
            conn.execute('select pg_advisory_xact_lock(741031)')
            exists = conn.execute("select to_regnamespace('network') as schema").fetchone()['schema']
            if exists:
                if not conn.execute("select to_regclass('network.state') as t").fetchone()['t']:
                    raise StoreError('unrecognized_network_schema')
                self._state(conn)
            else:
                path = Path(__file__).resolve().parents[2]/'db/network/0001_network.sql'
                conn.execute(path.read_text(encoding='utf-8'))
                conn.execute('insert into network.state(schema_version,binding,owner_id) values (1,%s,%s)', (self.binding,audit['owner_id']))
            role = conn.execute('select rolsuper,rolcanlogin,rolcreaterole,rolcreatedb,rolreplication,rolbypassrls from pg_roles where rolname=%s', (WRITER,)).fetchone()
            if role is None:
                conn.execute(sql.SQL('create role {} nologin noinherit').format(sql.Identifier(WRITER)))
            elif any(role.values()):
                raise StoreError('unsafe_writer_role')
            user = conn.execute('select current_user as name').fetchone()['name']
            conn.execute(sql.SQL('grant {} to {}').format(sql.Identifier(WRITER),sql.Identifier(user)))
            conn.execute(sql.SQL('grant usage on schema network to {}').format(sql.Identifier(WRITER)))
            conn.execute(sql.SQL('grant select,insert,update,delete on all tables in schema network to {}').format(sql.Identifier(WRITER)))
            conn.execute(sql.SQL('revoke update,delete on network.review_event from {}').format(sql.Identifier(WRITER)))
            conn.execute(sql.SQL('grant usage,select on all sequences in schema network to {}').format(sql.Identifier(WRITER)))
            # Inherited/public source privileges would defeat the writer boundary: refuse,
            # rather than changing source grants or pretending SET ROLE is sufficient.
            schema = conn.execute('select current_schema() as s').fetchone()['s']
            unsafe = conn.execute("select count(*) as n from pg_tables where schemaname=%s and has_table_privilege(%s,quote_ident(schemaname)||'.'||quote_ident(tablename),'INSERT,UPDATE,DELETE,TRUNCATE')", (schema,WRITER)).fetchone()['n']
            if unsafe:
                raise StoreError('writer_has_source_write_privileges')

    @contextmanager
    def connection(self, *, read_only=False):
        with psycopg.connect(self._dsn, row_factory=dict_row, connect_timeout=10) as conn:
            conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ'+(' READ ONLY' if read_only else ''))
            conn.execute(sql.SQL('set local role {}').format(sql.Identifier(WRITER)))
            conn.execute("SET LOCAL statement_timeout='15s'")
            yield conn

    def _state(self, conn, *, lock=False):
        row = conn.execute('select * from network.state'+(' for update' if lock else '')).fetchone()
        if not row or row['schema_version'] != 1:
            raise StoreError('unsupported_schema_version')
        if row['binding'] != self.binding:
            raise StoreError('source_binding_mismatch')
        return row

    def status(self):
        with self.connection(read_only=True) as conn:
            row = self._state(conn)
            return NetworkStatus(row['version'],row['last_success_at'],row['source_checked_at'],row['error_code'])

    def checkpoint(self):
        with self.connection(read_only=True) as conn:
            row = self._state(conn)['cursor']
            return Cursor(datetime.fromisoformat(row['ingested_at']),row['id']) if row else None

    def records(self, kind: str | None = None) -> tuple[SourceRecord, ...]:
        with self.connection(read_only=True) as conn:
            self._state(conn)
            rows = conn.execute('select * from network.source_record'+(' where kind=%s' if kind else '')+' order by key', (kind,) if kind else ())
            return tuple(SourceRecord(r['kind'],r['source_id'],r['fingerprint'],r['payload']) for r in rows)

    def apply(self, batch: SourceBatch, projection: Projection | None = None, *,
              schedules: dict | None = None, expected_version: int | None = None) -> int:
        if batch.binding != self.binding:
            raise StoreError('source_binding_mismatch')
        with self.connection() as conn:
            state = self._state(conn, lock=True)
            if expected_version is not None and state['version']!=expected_version:
                raise StoreError('version_conflict')
            keys = [r.key for r in batch.records]
            old = {r['key']:r['fingerprint'] for r in conn.execute('select key,fingerprint from network.source_record where key=ANY(%s)',(keys,))}
            updates = {r.key:r for r in batch.records if old.get(r.key) != r.fingerprint}
            changed = set(updates)
            for kind in batch.complete_kinds:
                if kind not in batch.manifests:
                    raise ValueError('incomplete_manifest')
                removed = conn.execute('delete from network.source_record where kind=%s and not (source_id=ANY(%s)) returning key',(kind,list(batch.manifests[kind]))).fetchall()
                changed.update(r['key'] for r in removed)
            if updates:
                with conn.cursor() as cur:
                    cur.executemany('insert into network.source_record(key,kind,source_id,fingerprint,payload) values (%s,%s,%s,%s,%s) on conflict(key) do update set fingerprint=excluded.fingerprint,payload=excluded.payload',
                                    [(r.key,r.kind,r.id,r.fingerprint,Jsonb(r.payload)) for r in updates.values()])
            if changed:
                conn.execute('delete from network.item i using network.dependency d where i.kind=d.item_kind and i.id=d.item_id and d.source_key=ANY(%s)',(list(changed),))
            projection_changed = self._project(conn,projection) if projection else False
            version = state['version']+int(bool(changed) or projection_changed)
            cursor = state['cursor']
            if batch.cursor:
                before = Cursor(datetime.fromisoformat(cursor['ingested_at']),cursor['id']) if cursor else None
                if before is None or batch.cursor > before:
                    cursor = {'ingested_at':batch.cursor.ingested_at.isoformat(),'id':batch.cursor.id}
            conn.execute('update network.state set version=%s,cursor=%s,last_success_at=%s,source_checked_at=%s,error_code=null where singleton',
                         (version,Jsonb(cursor),datetime.now(UTC),batch.observed_at))
            if projection and projection.owner_id:
                conn.execute('update network.state set owner_id=%s',(projection.owner_id,))
            if schedules is not None:
                conn.execute('update network.state set schedules=%s',(Jsonb(schedules),))
            return version

    def _project(self, conn, projection):
        changed = False
        all_deps = sorted({k for keys in projection.dependencies.values() for k in keys})
        fingerprints = {r['key']:r['fingerprint'] for r in conn.execute('select key,fingerprint from network.source_record where key=ANY(%s)',(all_deps,))}
        for kind, rows in projection.sections().items():
            ids = [r['id'] for r in rows]
            delete = 'delete from network.item where kind=%s and not (id=ANY(%s))'
            args = [kind,ids]
            if projection.affected_ids is not None:
                delete += ' and entity_ids && %s'
                args.append(list(projection.affected_ids))
            changed = bool(conn.execute(delete,args).rowcount) or changed
            old = {r['id']:r['fingerprint'] for r in conn.execute('select id,fingerprint from network.item where kind=%s and id=ANY(%s)',(kind,ids))}
            items, deps_to_write = [], []
            for row in rows:
                key, digest = kind+':'+row['id'],fingerprint(row)
                entities = entity_ids(kind,row)
                text = ' '.join(str(row.get(k,'')) for k in ('name','role','label','text','quote','relation','value','title'))
                if old.get(row['id'])!=digest:
                    items.append((kind,row['id'],entities,Jsonb(row),digest,text))
                    changed = True
                deps = projection.dependencies.get(key,())
                deps_to_write.extend((kind,row['id'],k,fingerprints.get(k,'absent')) for k in deps)
            with conn.cursor() as cur:
                if items:
                    cur.executemany('insert into network.item(kind,id,entity_ids,payload,fingerprint,search_text) values (%s,%s,%s,%s,%s,%s) on conflict(kind,id) do update set entity_ids=excluded.entity_ids,payload=excluded.payload,fingerprint=excluded.fingerprint,search_text=excluded.search_text',items)
                cur.execute('delete from network.dependency where item_kind=%s and item_id=ANY(%s)',(kind,ids))
                if deps_to_write:
                    cur.executemany('insert into network.dependency(item_kind,item_id,source_key,fingerprint) values (%s,%s,%s,%s)',deps_to_write)
        return changed

    def worker_state(self) -> dict:
        with self.connection(read_only=True) as conn:
            return self._state(conn)

    def record_failure(self, code: str):
        if code not in {'source_unavailable','source_budget_exceeded','version_conflict','projection_failed'}:
            raise ValueError('invalid_error_code')
        with self.connection() as conn:
            self._state(conn,lock=True)
            conn.execute('update network.state set error_code=%s',(code,))

    def capture(self, entity_ids: tuple[str, ...] = (), limit: int = 200) -> Snapshot:
        if not 1 <= limit <= 1000:
            raise ValueError('snapshot_limit')
        with self.connection(read_only=True) as conn:
            state = self._state(conn)
            selected = list(entity_ids)
            if not selected:
                selected = [r['id'] for r in conn.execute("select id from network.item where kind='node' order by id limit %s",(limit,))]
            rows = conn.execute('select * from network.item where entity_ids && %s order by kind,id limit %s',(selected,limit*20+1)).fetchall()
            truncated = len(rows)>limit*20
            rows = rows[:limit*20]
            # Include endpoints of the selected claims without fetching unrelated neighborhoods.
            endpoints = sorted({e for row in rows for e in row['entity_ids']})
            nodes = conn.execute("select * from network.item where kind='node' and id=ANY(%s) order by id limit %s",(endpoints,limit+1)).fetchall()
            allowed = {r['id'] for r in nodes[:limit]}
            truncated = truncated or len(nodes)>limit
            rows = [r for r in rows if r['kind']!='node' and set(r['entity_ids']).issubset(allowed)] + nodes[:limit]
            evidence_ids = sorted({e for r in rows for e in r['payload'].get('evidence_ids',[])})
            extra = conn.execute("select * from network.item where kind='evidence' and id=ANY(%s) order by id limit %s",(evidence_ids,limit*20)).fetchall()
            rows = list({(r['kind'],r['id']):r for r in [*rows,*extra]}.values())
            data = {section:[] for section in SECTIONS.values()}
            data.update(owner_id=state['owner_id'],data_source='real',truncated=truncated)
            deps = {}
            for row in rows:
                data[SECTIONS[row['kind']]].append(row['payload'])
            if rows:
                keys = [r['kind']+':'+r['id'] for r in rows]
                for r in conn.execute("select source_key,fingerprint from network.dependency where (item_kind||':'||item_id)=ANY(%s)",(keys,)):
                    deps[r['source_key']] = r['fingerprint']
            return Snapshot(state['version'],data,deps)

    def dependencies_current(self, dependencies: dict[str, str]) -> bool:
        with self.connection(read_only=True) as conn:
            self._state(conn)
            actual = {r['key']:r['fingerprint'] for r in conn.execute('select key,fingerprint from network.source_record where key=ANY(%s)',(list(dependencies),))}
            return all(actual.get(k,'absent')==v for k,v in dependencies.items())

    def reviews(self) -> tuple[dict,...]:
        with self.connection(read_only=True) as conn:
            self._state(conn)
            return tuple(conn.execute('select * from network.review_event order by id'))

    def wait_for_version(self, after: int, timeout: float) -> int:
        deadline = time.monotonic()+timeout
        while True:
            version = self.status().version
            if version>after or time.monotonic()>=deadline:
                return version
            time.sleep(min(1,max(0,deadline-time.monotonic())))
