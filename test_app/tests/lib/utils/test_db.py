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


class TestAdvisoryLock:
    @pytest.fixture(autouse=True)
    def skip_if_sqlite(self):
        if connection.vendor == 'sqlite':
            pytest.skip('Advisory lock is not written for sqlite')

    @pytest.mark.django_db
    def test_get_unclaimed_lock(self):
        with advisory_lock('test_get_unclaimed_lock'):
            pass

    @staticmethod
    def background_task(django_db_blocker):
        # HACK: as a thread the pytest.mark.django_db will not work
        django_db_blocker.unblock()
        with advisory_lock('background_task_lock'):
            time.sleep(0.1)

    @pytest.mark.django_db
    def test_determine_lock_is_held(self, django_db_blocker):
        thread = threading.Thread(target=TestAdvisoryLock.background_task, args=(django_db_blocker,))
        thread.start()
        for _ in range(5):
            with advisory_lock('background_task_lock', wait=False) as held:
                if held is False:
                    break
            time.sleep(0.01)
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

    @pytest.mark.django_db
    def test_lock_session_timeout_milliseconds(self):
        with pytest.raises(OperationalError) as exc:
            # uses miliseconds units
            with advisory_lock('test_lock_session_timeout_milliseconds', lock_session_timeout_milliseconds=2):
                time.sleep(3)
        assert 'the connection is lost' in str(exc)
