"""Explicit, derived-only schema initialization for the local network trial."""
import argparse
from dataclasses import asdict
import json

from dotenv import dotenv_values
from adapters.network.source import SourceRepository, SourceError
from adapters.network.store import PostgresNetworkStore, StoreError


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file', required=True)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--check', action='store_true')
    action.add_argument('--initialize', action='store_true')
    args = parser.parse_args()
    config = dotenv_values(args.env_file)
    if not config.get('DATABASE_URL'):
        parser.exit(2,'missing_database_url\n')
    try:
        source = SourceRepository(config['DATABASE_URL'])
        store = PostgresNetworkStore(config['DATABASE_URL'],source.audit()['binding'])
        if args.initialize:
            store.initialize()
        print(json.dumps(asdict(store.status()),default=str))
    except (SourceError,StoreError) as exc:
        parser.exit(2,str(exc)+'\n')
    except Exception:
        parser.exit(2,'network_schema_unavailable: verify database binding and initialization privileges locally\n')


if __name__ == '__main__':
    main()
