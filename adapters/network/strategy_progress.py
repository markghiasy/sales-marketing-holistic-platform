"""Bounded isolated retrieval workers; publication stays on the coordinator."""
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from time import monotonic

# Shared across runs: cancelling a synchronous database read cannot terminate its
# thread. Repeated cancel/retry must not create an unbounded number of readers.
_EXECUTOR = ThreadPoolExecutor(max_workers=3, thread_name_prefix='strategy-retrieval')


class StrategyCancelled(RuntimeError):
    def __init__(self):
        super().__init__('strategy_cancelled')


def with_task_coverage(pack, tasks):
    """Failed scope is unknown even if another lookup returned no match."""
    ledger = [dict(row) for row in tasks]
    coverage = []
    for original in pack['coverage']:
        row = dict(original)
        failed = [task['task_id'] for task in ledger if task['status'] == 'failed'
                  and row['id'] in task['requirement_ids']]
        if failed:
            row.update(search_status='incomplete', failed_task_ids=failed)
            if not row.get('evidence_ids'):
                row['status'] = 'search_incomplete'
        coverage.append(row)
    return {**pack, 'coverage': coverage, 'tasks': ledger,
            'scope': {**pack['scope'], 'search_complete': all(task['status'] == 'completed' for task in ledger)}}


def check_cancel(cancel):
    if cancel is not None and cancel.is_set():
        raise StrategyCancelled()


def parallel_retrieve(lookups, factory, retrieve, emit, cancel, *, task_offset=0, round_number=1):
    """Yield successful task states without sharing mutable retrieval instances."""
    pending = {}
    completed = {}
    failures = []

    def work(lookup):
        check_cancel(cancel)
        branch = factory()
        started = monotonic()
        result = retrieve(lookup, branch)
        check_cancel(cancel)
        return branch, result, monotonic() - started

    try:
        for index, lookup in enumerate(lookups):
            check_cancel(cancel)
            task_id = f'task-{task_offset + index + 1}'
            emit('task_started', {'task_id': task_id, 'round': round_number,
                 'label': ', '.join(lookup.terms) or lookup.entity_id, **lookup.model_dump()})
            pending[_EXECUTOR.submit(work, lookup)] = index
        while pending:
            check_cancel(cancel)
            ready, _ = wait(pending, timeout=.1, return_when=FIRST_COMPLETED)
            for future in sorted(ready, key=lambda f: pending[f]):
                index = pending.pop(future)
                check_cancel(cancel)
                task_id = f'task-{task_offset + index + 1}'
                try:
                    branch, result, seconds = future.result()
                except StrategyCancelled:
                    raise
                except Exception as error:  # noqa: BLE001 - isolate failures and sanitize worker errors
                    # A source conflict is never an ordinary incomplete search.
                    if str(error) == 'source_changed':
                        raise RuntimeError('source_changed') from None
                    failures.append(index)
                    emit('task_failed', {'task_id': task_id, 'code': 'retrieval_unavailable',
                         'message': 'This search could not finish; its coverage remains unknown.'})
                    continue
                completed[index] = (branch, result)
                emit('task_completed', {'task_id': task_id, 'seconds': round(seconds, 4)})
                yield dict(completed), tuple(failures)
    finally:
        for future in pending:
            future.cancel()
