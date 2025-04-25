import threading
import time

import pytest
from django.db import connection
from django.db.utils import OperationalError

from ansible_base.lib.utils.db import advisory_lock, migrations_are_complete


@pytest.mark.django_db
def test_migrations_are_complete():
    "If you are running tests, migrations (test database) should be complete"
    assert migrations_are_complete()


class SkipIfSqlite:
    @pytest.fixture(autouse=True)
    def skip_if_sqlite(self):
        if connection.vendor == 'sqlite':
            pytest.skip('Advisory lock is not written for sqlite')


class TestAdvisoryLock(SkipIfSqlite):
    THREAD_WAIT_TIME = 0.1

    @pytest.mark.django_db
    def test_get_unclaimed_lock(self):
        with advisory_lock('test_get_unclaimed_lock'):
            pass

    @staticmethod
    def background_task(django_db_blocker):
        # HACK: as a thread the pytest.mark.django_db will not work
        django_db_blocker.unblock()
        with advisory_lock('background_task_lock'):
            time.sleep(TestAdvisoryLock.THREAD_WAIT_TIME)

    @pytest.mark.django_db
    def test_determine_lock_is_held(self, django_db_blocker):
        thread = threading.Thread(target=TestAdvisoryLock.background_task, args=(django_db_blocker,))
        thread.start()
        for _ in range(5):
            with advisory_lock('background_task_lock', wait=False) as held:
                if held is False:
                    break
            time.sleep(TestAdvisoryLock.THREAD_WAIT_TIME / 5.0)
        else:
            raise RuntimeError('Other thread never obtained lock')
        thread.join()

    @pytest.mark.django_db
    def test_tuple_lock(self):
        with advisory_lock([1234, 4321]):
            pass

    @pytest.mark.django_db
    def test_invalid_tuple_name(self):
        with pytest.raises(ValueError):
            with advisory_lock(['test_invalid_tuple_name', 'foo']):
                pass


# Special transaction=True parameter is used, because we do not want in normal test transactions
# because dropping the connection would break the transaction context, erroring at end of test
@pytest.mark.django_db(transaction=True)
class TestAdvisoryLockPostgresErrors(SkipIfSqlite):
    """Tests related to connection management and the advisory_lock"""

    def kick_connection(self):
        """
        These (somewhat evil) tests are not gentle with the connection

        At the start of one tests there is a good chance the connection is broken by the last test.
        """
        connection.ensure_connection()
        # sanity checks
        assert connection.connection
        assert connection.connection.closed is False

    def test_timeout_under_lock_by_sleep(self):
        self.kick_connection()

        with pytest.raises(OperationalError) as exc:
            # uses miliseconds units
            with advisory_lock('test_lock_session_timeout_milliseconds', lock_session_timeout_milliseconds=5):
                time.sleep(0.1)

        # This exception comes from the __exit__, either releasing the lock or closing the cursor
        assert 'terminating connection due to idle-session timeout' in str(exc)

        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')

    def test_idle_after_exception(self):
        self.kick_connection()

        with pytest.raises(RuntimeError) as exc:
            with advisory_lock('test_timeout_under_lock_with_query', lock_session_timeout_milliseconds=5):
                with connection.cursor() as cursor:
                    raise RuntimeError('exception from test')

        assert 'exception from test' in str(exc)

        time.sleep(0.1)

        # The fact that this works shows that the timeout was reset in the context manager __exit__
        # Prior bug was giving exception with
        # consuming input failed: terminating connection due to idle-session timeout server closed the connection unexpectedly
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
