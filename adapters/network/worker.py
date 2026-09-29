"""Single-writer, bounded refresh. Completed source snapshots publish atomically."""
from __future__ import annotations

import json
import threading
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime

import psycopg

from .real_projection import project_records
from .store import StoreError, entity_ids


class SourceBudgetExceeded(ValueError):
    pass


class NetworkWorker:
    def __init__(self, source, store, *, incremental_seconds=60, metadata_seconds=300,
                 reconciliation_seconds=900, batch_size=500, lookback_seconds=300,
                 max_records=100000, max_bytes=256*1024*1024):
        if min(incremental_seconds,metadata_seconds,reconciliation_seconds)<=0 or not 2<=batch_size<=5000:
            raise ValueError('invalid_worker_limits')
        self.source,self.store=source,store
        self.intervals={'incremental':incremental_seconds,'metadata':metadata_seconds,'reconciliation':reconciliation_seconds}
        self.batch_size,self.lookback_seconds=batch_size,lookback_seconds
        self.max_records,self.max_bytes=max_records,max_bytes
        self.cache=None
        self.messages_by_identity=defaultdict(set)

    @contextmanager
    def lease(self):
        # Binding-specific advisory lock is held by a dedicated session for the run.
        key=int(self.store.binding[:15],16)
        with psycopg.connect(self.store._dsn,autocommit=True,connect_timeout=10,
                             application_name='ironman-network-worker-lease') as conn:
            held=conn.execute('select pg_try_advisory_lock(%s)',(key,)).fetchone()[0]
            try:
                yield held
            finally:
                if held:
                    conn.execute('select pg_advisory_unlock(%s)',(key,))

    def _bounded(self, rows):
        if len(rows)>self.max_records:
            raise SourceBudgetExceeded()
        size=0
        for row in rows:
            size+=len(json.dumps(row.payload,ensure_ascii=False).encode())
            if size>self.max_bytes:
                raise SourceBudgetExceeded()

    def _load_cache(self, rows):
        self._bounded(rows)
        self.cache={r.key:r for r in rows}
        self.messages_by_identity=defaultdict(set)
        for r in rows:
            if r.kind=='message':
                for iid in self._participants(r):
                    self.messages_by_identity[iid].add(r.key)

    @staticmethod
    def _participants(record):
        return {p['identity_id'] for p in record.payload.get('participants',[])} | ({record.payload['from_identity_id']} if record.payload.get('from_identity_id') else set())

    def _reconcile(self, now, state):
        records=[]
        final=None
        byte_count=0
        for page in self.source.snapshot_pages(self.batch_size):
            records.extend(page.records)
            byte_count+=sum(len(json.dumps(r.payload,ensure_ascii=False).encode()) for r in page.records)
            if len(records)>self.max_records or byte_count>self.max_bytes:
                raise SourceBudgetExceeded()
            if page.complete_kinds:
                final=page
        if final is None:
            raise OSError('incomplete_snapshot')
        changed=(self.cache is None or {r.key:r.fingerprint for r in records}!={k:r.fingerprint for k,r in self.cache.items()})
        projection=project_records(tuple(records),self.store.reviews(),now,binding=self.store.binding) if changed or state['version']==0 else None
        batch=replace(final,records=tuple(records))
        schedules={key:now.isoformat() for key in self.intervals}
        self.store.apply(batch,projection,schedules=schedules,expected_version=state['version'])
        self._load_cache(records)

    def _incremental_projection(self, updates, now, owner):
        metadata=[r for r in self.cache.values() if r.kind!='message']
        identities={r.id:r.payload for r in metadata if r.kind=='identity'}
        people={r.id:r.payload for r in metadata if r.kind=='person'}
        def canonical(iid):
            row=identities.get(iid)
            if row is None:
                return None
            if row['is_self']:
                return owner
            person=row.get('person_id'); seen=set()
            while person and people.get(person,{}).get('merged_into'):
                if person in seen:
                    raise ValueError('identity_cycle')
                seen.add(person); person=people[person]['merged_into']
            return 'person:'+person if person else 'identity:'+iid
        mappings={i:canonical(i) for i in identities}
        before=[self.cache[r.key] for r in updates if r.key in self.cache]
        affected={canonical(i) for r in [*before,*updates] for i in self._participants(r)}-{None,owner}
        aliases={i for i,p in mappings.items() if p in affected}
        message_keys=set().union(*(self.messages_by_identity[i] for i in aliases)) if aliases else set()
        sources={k:self.cache[k] for k in message_keys}
        sources.update({r.key:r for r in updates})
        projected=project_records(tuple(metadata)+tuple(sources.values()),self.store.reviews(),now,binding=self.store.binding)
        # Only affected people's derived items are replaced. Owner is an endpoint,
        # not a wildcard which would erase every other contact's relationships.
        sections={kind:tuple(r for r in rows if set(entity_ids(kind,r)) & affected)
                  for kind,rows in projected.sections().items() if kind!='node'}
        referenced={e for kind,rows in sections.items() for r in rows for e in entity_ids(kind,r)} | affected | {owner}
        nodes=tuple(r for r in projected.entities if r['id'] in referenced)
        return replace(projected,entities=nodes,assertions=sections['claim'],evidence=sections['evidence'],
                       messages=sections['message'],profiles=sections['profile'],strategies=sections['strategy'],
                       work=sections['work'],affected_ids=tuple(sorted(affected)))

    def _tick(self, now):
        state=self.store.worker_state()
        schedules=state['schedules']
        due={k:k not in schedules or (now-datetime.fromisoformat(schedules[k])).total_seconds()>=v for k,v in self.intervals.items()}
        if self.cache is None and state['version']:
            self._load_cache(self.store.records())
        if due['reconciliation'] or state['version']==0:
            self._reconcile(now,state)
            return
        if not any(due.values()):
            return
        if due['metadata']:
            metadata=self.source.metadata()
            new={r.key:r.fingerprint for r in metadata.records}
            old={k:r.fingerprint for k,r in self.cache.items() if r.kind!='message'}
            if old!=new:
                # Canonical/visibility/affiliation changes can invalidate a wide
                # neighborhood. Reconcile a complete source snapshot before publishing.
                self._reconcile(now,state)
                return
        batch=self.source.incremental(self.store.checkpoint(),self.lookback_seconds,self.batch_size)
        updates=[r for r in batch.records if r.key not in self.cache or self.cache[r.key].fingerprint!=r.fingerprint]
        known={r.id for r in self.cache.values() if r.kind=='identity'}
        if any(not self._participants(r).issubset(known) or 'thread:'+r.payload['thread_id'] not in self.cache for r in updates):
            self._reconcile(now,state)
            return
        candidate={**self.cache,**{r.key:r for r in updates}}
        self._bounded(candidate.values())
        projection=self._incremental_projection(updates,now,state['owner_id']) if updates else None
        next_schedules={**schedules,'incremental':now.isoformat()}
        if due['metadata']:
            next_schedules['metadata']=now.isoformat()
        self.store.apply(batch,projection,schedules=next_schedules,expected_version=state['version'])
        for row in updates:
            before=self.cache.get(row.key)
            if before:
                for iid in self._participants(before):
                    self.messages_by_identity[iid].discard(row.key)
            self.cache[row.key]=row
            for iid in self._participants(row):
                self.messages_by_identity[iid].add(row.key)

    def tick(self, now: datetime):
        try:
            self._tick(now)
        except SourceBudgetExceeded:
            self.store.record_failure('source_budget_exceeded')
        except StoreError as exc:
            if str(exc)!='version_conflict':
                raise
            self.store.record_failure('version_conflict')
        except (OSError,psycopg.Error):
            self.store.record_failure('source_unavailable')
        except ValueError:
            self.store.record_failure('projection_failed')
        return self.store.status()

    def run(self, stop: threading.Event):
        with self.lease() as held:
            if not held:
                raise StoreError('worker_already_running')
            while not stop.is_set():
                self.tick(datetime.now(UTC))
                stop.wait(1)
