"""Bounded process-local strategy runs; replay never bypasses evidence validation."""
from __future__ import annotations

import json
import secrets
import threading
import time
from copy import deepcopy
from typing import ClassVar

TERMINAL = frozenset({'completed', 'failed', 'cancelled', 'invalidated'})
# Plans and task labels can contain source-derived names before any partial.
EVIDENCE_EVENTS = frozenset({'plan', 'task_started', 'partial', 'assessment', 'completed'})


class StrategyBudgetError(RuntimeError):
    """Only allow-listed diagnostics may cross the result disclosure boundary."""
    messages: ClassVar[dict[str, str]] = {
        'model_output_limit': 'The model response reached its output limit. Completed results remain available; try a more focused goal.',
        'model_input_limit': 'The analysis context reached its input limit. Completed results remain available; try a more focused goal.',
    }

    def __init__(self, code):
        self.code = code
        super().__init__(self.messages[code])


class StrategyCancelled(RuntimeError):
    pass


class StrategyRun:
    def __init__(self, runner, validator, clock, max_seconds, request_data):
        self.id = secrets.token_urlsafe(24)
        self.clock = clock
        self.request_data = deepcopy(request_data or {})
        self.max_seconds = max_seconds
        self.created_at = clock()
        self.status = 'running'
        self.cancel = threading.Event()
        self.condition = threading.Condition(threading.RLock())
        self.validation_lock = threading.Lock()
        self.validator = validator
        self.dependencies = {}
        self.revision = 0
        self.events = []
        self.sequence = 0
        self.event_bytes = 0
        self.has_evidence = False
        self.thread = threading.Thread(target=self._execute, args=(runner,), daemon=True,
                                       name='network-strategy')

    def _append(self, kind, data):
        self.sequence += 1
        event = {'seq': self.sequence, 'type': kind, 'data': deepcopy(data)}
        self.events.append(event)
        self.event_bytes += len(json.dumps(event, ensure_ascii=False).encode())
        if kind in TERMINAL:
            self.status = kind
        self.condition.notify_all()

    def set_dependencies(self, dependencies):
        with self.condition:
            if any(k in self.dependencies and self.dependencies[k] != v
                   for k, v in dependencies.items()):
                self.invalidate()
                raise RuntimeError('source_changed')
            self.dependencies.update(dependencies)
            self.revision += 1

    def invalidate(self):
        with self.condition:
            if self.status == 'invalidated':
                return
            self.cancel.set()
            self.events.clear()
            self.event_bytes = 0
            self.has_evidence = False
            self.dependencies.clear()
            self._append('invalidated', {
                'code': 'evidence_unavailable',
                'message': 'These sources changed or could not be rechecked. Start a new analysis.'})

    def validate(self):
        with self.validation_lock:
            # A parallel dependency update must not make an older check authorize new evidence.
            for _ in range(3):
                with self.condition:
                    if self.status == 'invalidated':
                        return False
                    proof, revision = dict(self.dependencies), self.revision
                try:
                    valid = self.validator is None or self.validator(proof)
                except Exception:  # noqa: BLE001 - failed verification must close the disclosure boundary.
                    valid = False
                if not valid:
                    self.invalidate()
                    return False
                with self.condition:
                    if self.revision == revision:
                        return self.status != 'invalidated'
            self.invalidate()
            return False

    def emit(self, kind, data):
        if self.cancel.is_set():
            raise StrategyCancelled('strategy_cancelled')
        if kind in EVIDENCE_EVENTS and not self.validate():
            raise RuntimeError('source_changed')
        size = len(json.dumps(data, ensure_ascii=False).encode())
        with self.condition:
            if self.cancel.is_set() or self.status in TERMINAL:
                raise StrategyCancelled('strategy_cancelled')
            if len(self.events) >= 128 or self.event_bytes + size > 2_000_000:
                raise RuntimeError('strategy_result_budget')
            self.has_evidence = self.has_evidence or kind in EVIDENCE_EVENTS
            self._append(kind, data)

    def _execute(self, runner):
        timeout = threading.Timer(self.max_seconds, self._timeout)
        timeout.daemon = True
        timeout.start()
        try:
            self.emit('started', {'message': 'Preparing the analysis.', 'request': self.request_data})
            result = runner(self)
            self.emit('completed', result)
        except Exception as error:  # noqa: BLE001 - never expose provider/source exception contents.
            if str(error) == 'source_changed':
                self.invalidate()
            else:
                with self.condition:
                    if self.status not in TERMINAL:
                        if self.cancel.is_set():
                            self._append('cancelled', {'message': 'Analysis stopped. Completed results remain available.'})
                        elif isinstance(error, StrategyBudgetError):
                            self._append('failed', {'code': error.code, 'message': error.messages[error.code]})
                        else:
                            self._append('failed', {'code': 'analysis_unavailable',
                                'message': 'Analysis could not finish. Completed results remain available; you can try again.'})
        finally:
            timeout.cancel()
            with self.condition:
                self.condition.notify_all()

    def _timeout(self):
        with self.condition:
            if self.status not in TERMINAL:
                self.cancel.set()
                self._append('failed', {'code': 'strategy_time_budget',
                    'message': 'The analysis reached its time budget. Completed results remain available; unfinished areas are still unknown.'})

    def snapshot(self):
        with self.condition:
            evidence = self.has_evidence
        if evidence:
            self.validate()
        return self._copy_snapshot()

    def _copy_snapshot(self):
        """Internal copy only. HTTP delivery must perform its own disclosure check."""
        with self.condition:
            return {'run_id': self.id, 'status': self.status, 'events': deepcopy(self.events),
                    'request': deepcopy(self.request_data),
                    'elapsed_seconds': round(self.clock() - self.created_at, 3),
                    'retention': 'This local app session only; retained for up to 30 minutes.'}

    def stop(self):
        with self.condition:
            if self.status not in TERMINAL:
                self.cancel.set()
                self._append('cancelled', {'message': 'Stop requested. Completed results remain available. An already-started request may finish.'})


class StrategyJobs:
    def __init__(self, *, max_runs=8, ttl_seconds=1800, max_seconds=180, clock=time.monotonic):
        if min(max_runs, ttl_seconds, max_seconds) <= 0:
            raise ValueError('invalid_strategy_budget')
        self.max_runs, self.ttl_seconds, self.clock = max_runs, ttl_seconds, clock
        self.max_seconds = max_seconds
        self.runs = {}
        self.lock = threading.Lock()

    def _prune(self):
        expired = [key for key, run in self.runs.items()
                   if not run.thread.is_alive() and self.clock() - run.created_at > self.ttl_seconds]
        for key in expired:
            del self.runs[key]

    def start(self, runner, *, validator=None, request_data=None):
        with self.lock:
            self._prune()
            if any(run.thread.is_alive() for run in self.runs.values()):
                raise RuntimeError('strategy_busy')
            while len(self.runs) >= self.max_runs:
                del self.runs[next(iter(self.runs))]
            run = StrategyRun(runner, validator, self.clock, self.max_seconds, request_data)
            self.runs[run.id] = run
            run.thread.start()
            return run

    def get(self, run_id):
        with self.lock:
            self._prune()
            return self.runs[run_id]

    def snapshot(self, run_id):
        return self.get(run_id).snapshot()

    def cancel(self, run_id):
        run = self.get(run_id)
        run.stop()
        return run.snapshot()
