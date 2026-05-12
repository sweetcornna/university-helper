import re
import threading
from collections import OrderedDict
import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2.pool import ThreadedConnectionPool
from contextlib import contextmanager
from app.config import settings

main_pool = None
tenant_pools: OrderedDict[str, ThreadedConnectionPool] = OrderedDict()
_tenant_lock = threading.Lock()
MAX_TENANT_POOLS = 100
_TENANT_NAME_RE = re.compile(r"^tenant_[a-z0-9]+$")


def _get_main_pool():
    global main_pool
    if main_pool is None:
        main_pool = ThreadedConnectionPool(
            minconn=5,
            maxconn=30,
            host=settings.MAIN_DB_HOST,
            database=settings.MAIN_DB_NAME,
            user=settings.MAIN_DB_USER,
            password=settings.MAIN_DB_PASSWORD,
            port=settings.MAIN_DB_PORT,
            cursor_factory=RealDictCursor
        )
    return main_pool


def get_main_db_connection():
    return _get_main_pool().getconn()


def _validate_tenant_db_name(tenant_db_name: str) -> None:
    if not _TENANT_NAME_RE.match(tenant_db_name):
        raise ValueError(
            f"Invalid tenant database name: {tenant_db_name!r}. "
            "Must match pattern: tenant_[a-z0-9]+"
        )


def get_tenant_db_connection(tenant_db_name: str):
    _validate_tenant_db_name(tenant_db_name)

    with _tenant_lock:
        if tenant_db_name in tenant_pools:
            # Move to end (most recently used)
            tenant_pools.move_to_end(tenant_db_name)
        else:
            # Evict oldest pools if at capacity
            while len(tenant_pools) >= MAX_TENANT_POOLS:
                evicted_name, evicted_pool = tenant_pools.popitem(last=False)
                try:
                    evicted_pool.closeall()
                except Exception:
                    pass

            tenant_pools[tenant_db_name] = ThreadedConnectionPool(
                minconn=4,
                maxconn=20,
                host=settings.MAIN_DB_HOST,
                database=tenant_db_name,
                user=settings.MAIN_DB_USER,
                password=settings.MAIN_DB_PASSWORD,
                port=settings.MAIN_DB_PORT,
                cursor_factory=RealDictCursor
            )

        return tenant_pools[tenant_db_name].getconn()


@contextmanager
def get_db_session(db_name: str = None):
    if db_name:
        pool = tenant_pools.get(db_name)
        if not pool:
            conn = get_tenant_db_connection(db_name)
        else:
            conn = pool.getconn()
    else:
        conn = _get_main_pool().getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        if db_name and db_name in tenant_pools:
            tenant_pools[db_name].putconn(conn)
        else:
            _get_main_pool().putconn(conn)
