"""Sanitized, read-only readiness audit; no application .env is loaded implicitly."""
import argparse
import json

from dotenv import dotenv_values

from adapters.network.source import SourceError, SourceRepository


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file', required=True)
    args = parser.parse_args()
    config = dotenv_values(args.env_file)
    if not config.get('DATABASE_URL'):
        parser.exit(2, 'missing_database_url\n')
    try:
        print(json.dumps(SourceRepository(config['DATABASE_URL']).audit(), indent=2))
    except SourceError as exc:
        parser.exit(2, str(exc)+'\n')
    except Exception:  # noqa: BLE001 - sanitize configuration/DB failures at the CLI boundary.
        parser.exit(2, 'source_unavailable: check connection, credentials and schema locally\n')


if __name__ == '__main__':
    main()
