"""Small process-local pool; callers retain explicit transaction and role boundaries."""
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool


class NetworkDatabase:
    def __init__(self,dsn,*,max_size=6):
        self.pool=ConnectionPool(dsn,min_size=0,max_size=max_size,max_waiting=24,
            timeout=10,max_idle=120,open=True,name='network-db',
            kwargs={'row_factory':dict_row,'connect_timeout':10,'prepare_threshold':None})

    def connection(self):
        return self.pool.connection()

    def close(self):
        self.pool.close()

    def __enter__(self):
        return self

    def __exit__(self,*args):
        self.close()
