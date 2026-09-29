import psycopg
import pytest


def test_pool_reuses_connection_without_leaking_writer_role_or_transaction(network_database):
    from adapters.network.database import NetworkDatabase
    from adapters.network.source import SourceRepository
    from adapters.network.store import PostgresNetworkStore
    dsn,ids=network_database
    with NetworkDatabase(dsn,max_size=1) as database:
        source=SourceRepository(dsn,database=database)
        store=PostgresNetworkStore(dsn,source.audit()['binding'],database=database)
        store.initialize()
        with source.connection() as conn:
            first=conn.execute('select pg_backend_pid() as pid,current_user as role').fetchone()
        with store.connection() as conn:
            writer=conn.execute('select pg_backend_pid() as pid,current_user as role').fetchone()
            assert writer['role']=='ironman_network_writer'
            assert writer['pid']==first['pid']
        with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
            with source.connection() as conn:
                conn.execute("update identity set display_name='must not write'")
        with source.connection() as conn:
            after=conn.execute('select current_user as role').fetchone()
            assert after['role']==first['role']
            assert conn.execute('select display_name from identity where id=%s',(ids['contact'],)).fetchone()['display_name']=='Morgan'
