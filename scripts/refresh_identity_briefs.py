"""Preview a bounded stale-brief batch; --apply explicitly enables provider calls.

Run from the repository root: python -m scripts.refresh_identity_briefs
"""
from __future__ import annotations

import argparse
import os

import psycopg
from dotenv import load_dotenv

from adapters.ai_brief import refresh_touched


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', help='Regenerate selected briefs; uses the provider API')
    parser.add_argument('--limit', type=int, default=25)
    args = parser.parse_args(argv)
    if not 1 <= args.limit <= 500:
        parser.error('--limit must be between 1 and 500')
    return args


def stale_keys(cur, limit: int) -> set[str]:
    cur.execute('''select b.person_key from ai_brief b
        join contact_stats cs on cs.contact_key=b.person_key
        where not exists (select 1 from current_ai_brief c where c.person_key=b.person_key)
          and not exists (select 1 from contact_hidden h where h.contact_key=b.person_key)
        order by cs.last_contact_at desc, b.person_key limit %s''', (limit,))
    return {str(row[0]) for row in cur.fetchall()}


def main(argv=None):
    args = parse_args(argv)
    load_dotenv()
    with psycopg.connect(os.environ['DATABASE_URL']) as conn, conn.cursor() as cur:
        keys = stale_keys(cur, args.limit)
    print(f'{len(keys)} stale visible briefs selected (limit {args.limit}).')
    if not args.apply:
        print('Preview only. Add --apply to use the provider API for this batch.')
        return
    refresh_touched(keys)
    print('Refresh attempts recorded. Check ai_brief_status for success, truncation or failure.')


if __name__ == '__main__':
    main()
