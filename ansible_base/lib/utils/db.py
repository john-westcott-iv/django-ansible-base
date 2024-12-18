from contextlib import contextmanager
from zlib import crc32

from django.db import DEFAULT_DB_ALIAS, connection, connections, transaction
from django.db.migrations.executor import MigrationExecutor


@contextmanager
def ensure_transaction():
    needs_new_transaction = not transaction.get_connection().in_atomic_block

    if needs_new_transaction:
        with transaction.atomic():
            yield
    else:
        yield


def migrations_are_complete() -> bool:
    """Returns a boolean telling you if manage.py migrate has been run to completion

    Note that this is a little expensive, like up to 20 database queries
    and lots of imports.
    Not suitable to run as part of a request, but expected to be okay
    in a management command or post_migrate signals"""
    executor = MigrationExecutor(connection)
    plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
    return not bool(plan)


# NOTE: the django_pglocks_advisory_lock context manager was forked from the django-pglocks v1.0.4
# that was licensed under the MIT license


@contextmanager
def django_pglocks_advisory_lock(lock_id, shared=False, wait=True, using=None):

    if using is None:
        using = DEFAULT_DB_ALIAS

    # Assemble the function name based on the options.

    function_name = 'pg_'

    if not wait:
        function_name += 'try_'

    function_name += 'advisory_lock'

    if shared:
        function_name += '_shared'

    release_function_name = 'pg_advisory_unlock'
    if shared:
        release_function_name += '_shared'

    # Format up the parameters.

    tuple_format = False

    if isinstance(
        lock_id,
        (
            list,
            tuple,
        ),
    ):
        if len(lock_id) != 2:
            raise ValueError("Tuples and lists as lock IDs must have exactly two entries.")

        if not isinstance(lock_id[0], int) or not isinstance(lock_id[1], int):
            raise ValueError("Both members of a tuple/list lock ID must be integers")

        tuple_format = True
    elif isinstance(lock_id, str):
        # Generates an id within postgres integer range (-2^31 to 2^31 - 1).
        # crc32 generates an unsigned integer in Py3, we convert it into
        # a signed integer using 2's complement (this is a noop in Py2)
        pos = crc32(lock_id.encode("utf-8"))
        lock_id = (2**31 - 1) & pos
        if pos & 2**31:
            lock_id -= 2**31
    elif not isinstance(lock_id, int):
        raise ValueError("Cannot use %s as a lock id" % lock_id)

    if tuple_format:
        base = "SELECT %s(%d, %d)"
        params = (
            lock_id[0],
            lock_id[1],
        )
    else:
        base = "SELECT %s(%d)"
        params = (lock_id,)

    acquire_params = (function_name,) + params

    command = base % acquire_params
    cursor = connections[using].cursor()

    cursor.execute(command)

    if not wait:
        acquired = cursor.fetchone()[0]
    else:
        acquired = True

    try:
        yield acquired
    finally:
        if acquired:
            release_params = (release_function_name,) + params

            command = base % release_params
            cursor.execute(command)

        cursor.close()


@contextmanager
def advisory_lock(*args, lock_session_timeout_milliseconds=0, **kwargs):
    """Context manager that wraps the pglocks advisory lock

    This obtains a named lock in postgres, idenfied by the args passed in
    usually the lock identifier is a simple string.

    @param: wait If True, block until the lock is obtained
    @param: shared Whether or not the lock is shared
    @param: lock_session_timeout_milliseconds Postgres-level timeout
    @param: using django database identifier
    """
    if connection.vendor == "postgresql":
        cur = None
        idle_in_transaction_session_timeout = None
        idle_session_timeout = None
        if lock_session_timeout_milliseconds > 0:
            with connection.cursor() as cur:
                idle_in_transaction_session_timeout = cur.execute("SHOW idle_in_transaction_session_timeout").fetchone()[0]
                idle_session_timeout = cur.execute("SHOW idle_session_timeout").fetchone()[0]
                cur.execute("SET idle_in_transaction_session_timeout = %s", (lock_session_timeout_milliseconds,))
                cur.execute("SET idle_session_timeout = %s", (lock_session_timeout_milliseconds,))
        with django_pglocks_advisory_lock(*args, **kwargs) as internal_lock:
            yield internal_lock
            if lock_session_timeout_milliseconds > 0:
                with connection.cursor() as cur:
                    cur.execute("SET idle_in_transaction_session_timeout = %s", (idle_in_transaction_session_timeout,))
                    cur.execute("SET idle_session_timeout = %s", (idle_session_timeout,))
    elif connection.vendor == "sqlite":
        yield True
    else:
        raise RuntimeError(f'Advisory lock not implemented for database type {connection.vendor}')
