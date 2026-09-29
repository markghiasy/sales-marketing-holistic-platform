"""Recoverable real-network worker; run separately from the web service."""
import argparse
import atexit
import json
import threading
from dataclasses import asdict
from datetime import UTC, datetime

from dotenv import dotenv_values

from adapters.network.database import NetworkDatabase
from adapters.network.source import SourceRepository
from adapters.network.store import PostgresNetworkStore
from adapters.network.worker import NetworkWorker


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file',required=True)
    parser.add_argument('--once',action='store_true')
    args=parser.parse_args()
    config=dotenv_values(args.env_file)
    if not config.get('DATABASE_URL'):
        parser.exit(2,'missing_database_url\n')
    try:
        database=NetworkDatabase(config['DATABASE_URL'],max_size=3)
        atexit.register(database.close)
        source=SourceRepository(config['DATABASE_URL'],database=database)
        store=PostgresNetworkStore(config['DATABASE_URL'],source.audit()['binding'],database=database)
        worker=NetworkWorker(source,store,
            incremental_seconds=int(config.get('NETWORK_REFRESH_SECONDS') or 60),
            metadata_seconds=int(config.get('NETWORK_METADATA_SECONDS') or 300),
            reconciliation_seconds=int(config.get('NETWORK_RECONCILE_SECONDS') or 900),
            max_records=int(config.get('NETWORK_MAX_RECORDS') or 100000),
            max_bytes=int(config.get('NETWORK_MAX_BYTES') or 268435456))
        if args.once:
            with worker.lease() as held:
                if not held:
                    parser.exit(2,'worker_already_running\n')
                status=worker.tick(datetime.now(UTC))
                print(json.dumps(asdict(status),default=str))
                if status.error_code:
                    parser.exit(2)
        else:
            worker.run(threading.Event())
    except KeyboardInterrupt:
        pass
    except Exception:  # noqa: BLE001 - sanitize configuration/DB failures at the CLI boundary.
        parser.exit(2,'network_worker_unavailable: inspect sanitized health and database configuration\n')


if __name__=='__main__':
    main()
