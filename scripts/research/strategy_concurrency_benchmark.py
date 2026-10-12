"""Measure worker overlap with fictional delayed lookups, never live sources.

Run: python -m scripts.research.strategy_concurrency_benchmark
This is a scheduler experiment, not an end-to-end database/model benchmark.
"""
import json
import threading
import time

from adapters.network.agent import Lookup
from adapters.network.strategy_progress import parallel_retrieve


def main():
    lookups = [Lookup(kind='people', terms=[term])
               for term in ('teaching', 'venue', 'recruitment')]

    def retrieve(lookup, _branch):
        time.sleep(.15)
        return {'term': lookup.terms[0]}

    samples = []
    for _ in range(5):
        start = time.perf_counter()
        serial = [retrieve(lookup, None) for lookup in lookups]
        serial_seconds = time.perf_counter() - start
        start = time.perf_counter()
        first_seconds = None
        completed = {}
        for completed, _failures in parallel_retrieve(
                lookups, object, retrieve, lambda *_: None, threading.Event()):
            if first_seconds is None:
                first_seconds = time.perf_counter() - start
        parallel_seconds = time.perf_counter() - start
        assert [completed[i][1] for i in range(3)] == serial
        samples.append({'serial_seconds': round(serial_seconds, 4),
                        'first_partial_seconds': round(first_seconds, 4),
                        'parallel_seconds': round(parallel_seconds, 4)})
    print(json.dumps({'simulated_delay_per_task_seconds': .15,
                      'samples': samples, 'same_results': True}, indent=2))


if __name__ == '__main__':
    main()
