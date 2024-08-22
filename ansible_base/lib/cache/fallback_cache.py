import logging

try:
    import uwsgi

    # This line is unreachable in unit tests
    _HAS_UWSGI = True  # pragma: no cover
except ImportError:
    _HAS_UWSGI = False
import multiprocessing
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from os import getpid
from pathlib import Path

from django.core import cache as django_cache
from django.core.cache.backends.base import BaseCache

from ansible_base.lib.utils.settings import get_setting

logger = logging.getLogger('ansible_base.cache.fallback_cache')

DEFAULT_TIMEOUT = None
PRIMARY_CACHE = 'primary'
FALLBACK_CACHE = 'fallback'

_fail_over_uwsgi_lock_number = get_setting('ANSIBLE_BASE_FALLBACK_CACHE_FAIL_OVER_LOCK_NUMBER', 0)
_fail_back_uwsgi_lock_number = get_setting('ANSIBLE_BASE_FALLBACK_CACHE_FAIL_BACK_LOCK_NUMBER', 0)

_temp_file = Path().joinpath(tempfile.gettempdir(), 'gw_primary_cache_failed')


class DABCacheWithFallback(BaseCache):
    _instance = None
    _primary_cache = None
    _fallback_cache = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super(DABCacheWithFallback, cls).__new__(cls)
            cls.__initialized = False
        return cls._instance

    def __init__(self, location, params):
        if self.__initialized:
            return
        BaseCache.__init__(self, params)

        self._primary_cache = django_cache.caches.create_connection(PRIMARY_CACHE)
        self._fallback_cache = django_cache.caches.create_connection(FALLBACK_CACHE)
        self.thread_pool = ThreadPoolExecutor()

        if _temp_file.exists():
            _temp_file.unlink()

        self.__initialized = True

    def get_active_cache(self):
        return FALLBACK_CACHE if _temp_file.exists() else PRIMARY_CACHE

    # Main cache interface
    def add(self, key, value, timeout=DEFAULT_TIMEOUT, version=None):
        return self._op_with_fallback("add", key, value, timeout=timeout, version=version)

    def get(self, key, default=None, version=None):
        return self._op_with_fallback("get", key, default=default, version=version)

    def set(self, key, value, timeout=DEFAULT_TIMEOUT, version=None, client=None):
        return self._op_with_fallback("set", key, value, timeout=timeout)

    def delete(self, key, version=None):
        return self._op_with_fallback("delete", key, version=version)

    def clear(self):
        return self._op_with_fallback("clear")

    def _op_with_fallback(self, operation, *args, **kwargs):
        if _temp_file.exists():
            response = getattr(self._fallback_cache, operation)(*args, **kwargs)
            self.thread_pool.submit(DABCacheWithFallback.check_primary_cache)
        else:
            try:
                response = getattr(self._primary_cache, operation)(*args, **kwargs)
                return response
            except Exception:
                logger.debug("Failed to get response from primary cache")
                if not _HAS_UWSGI:
                    logger.debug("Not running under uwsgi, locking with multiprocessing")
                    with multiprocessing.Lock():
                        self.fallback_cache()
                else:  # pragma: no cover
                    # The else part of this block can't be covered because the unit tests never run under uwsgi
                    logger.debug("Locking with uwsgi")
                    got_lock = False
                    if not uwsgi.is_locked(_fail_over_uwsgi_lock_number):
                        logger.debug("Trying to get failover lock")
                        try:
                            got_lock = DABCacheWithFallback.get_lock(_fail_over_uwsgi_lock_number)
                            self.fallback_cache()
                        except Exception:
                            pass
                        finally:
                            if got_lock:
                                uwsgi.unlock(_fail_over_uwsgi_lock_number)
                    else:
                        logger.debug("The failover lock is already locked")

                response = getattr(self._fallback_cache, operation)(*args, **kwargs)

        return response

    def fallback_cache(self):
        if not _temp_file.exists():
            logger.error("Primary cache unavailable, switching to fallback cache.")
        logger.debug("Adding fallback cache file indicator")
        _temp_file.touch()

    @staticmethod
    def recover_cache(primary_cache):
        # Clear the primary cache
        logger.debug("Clearing primary cache from recovery")
        primary_cache.clear()
        logger.debug("Removing fallback cache file indicator")
        _temp_file.unlink()
        # Clear the backup cache just incase we need to fall back again (don't want it out of sync)
        fallback_cache = django_cache.caches.create_connection(FALLBACK_CACHE)
        logger.debug("Clearing fallback cache from recovery")
        fallback_cache.clear()
        logger.warning("Primary cache recovered resuming use.")

    @staticmethod
    def check_primary_cache():
        if uwsgi.is_locked(_fail_back_uwsgi_lock_number):
            logger.debug("Cache is already locked")
            return

        try:
            logger.debug(f"Thread starting check_primary_cache {getpid()}")
            primary_cache = django_cache.caches.create_connection(PRIMARY_CACHE)
            primary_cache.get('up_test')
            logger.debug(f"Was able to read cache, attempting to revert to primary cache {getpid}")
            if not _HAS_UWSGI:
                logger.debug("Not running under uwsgi, locking with multiprocessing")
                with multiprocessing.Lock():
                    DABCacheWithFallback.recover_cache(primary_cache)
            else:  # pragma: no cover
                # The else part of this block can't be covered because the unit tests never run under uwsgi
                logger.debug("Locking with uwsgi")
                got_lock = False
                try:
                    got_lock = DABCacheWithFallback.get_lock(_fail_back_uwsgi_lock_number)
                    if _temp_file.exists():
                        DABCacheWithFallback.recover_cache(primary_cache)
                except Exception:
                    pass
                finally:
                    if got_lock:
                        uwsgi.unlock(_fail_back_uwsgi_lock_number)
        except Exception:
            pass

        logger.debug(f"Thread ending check_primary_cache {getpid()}")

    @staticmethod
    def get_lock(lock_number: int) -> bool:
        logger.debug("Attempting to get a lock")
        with ThreadPoolExecutor as tpe:
            logger.debug("Got my ThreadPoolExecutor")
            try:
                logger.debug("Requesting lock")
                for future in as_completed(tpe.map(uwsgi.lock, [lock_number], timeout=0.25)):
                    future.result(timeout=0.25)
                    logger.debug("Got lock")
                    return True
            except TimeoutError:
                logger.debug("Failed to get lock in time")
                for pod, process in tpe._processes.items():
                    process.terminate()
                    return False
