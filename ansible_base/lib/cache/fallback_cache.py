import logging

try:
    import uwsgi

    _HAS_UWSGI = True
except ImportError:
    _HAS_UWSGI = False
import multiprocessing
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from django.core import cache as django_cache
from django.core.cache.backends.base import BaseCache

logger = logging.getLogger('ansible_base.cache.fallback_cache')

DEFAULT_TIMEOUT = None
PRIMARY_CACHE = 'primary'
FALLBACK_CACHE = 'fallback'

_fail_over_uwsgi_lock_number = 0
_fail_back_uwsgi_lock_number = 0

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
                if _HAS_UWSGI:
                    logger.debug("Locking with uwsgi")
                    got_lock = False
                    try:
                        uwsgi.lock(_fail_over_uwsgi_lock_number)
                        got_lock = True
                        self.fallback_cache()
                    except Exception:
                        pass
                    finally:
                        if got_lock:
                            uwsgi.unlock(_fail_over_uwsgi_lock_number)
                else:
                    logger.debug("Not running under uwsgi, locking with multiprocessing")
                    with multiprocessing.Lock():
                        self.fallback_cache()

                response = getattr(self._fallback_cache, operation)(*args, **kwargs)

        return response

    def fallback_cache(self):
        if not _temp_file.exists():
            logger.error("Primary cache unavailable, switching to fallback cache.")
        logger.debug("Adding fallback cache file indicator")
        _temp_file.touch()

    @staticmethod
    def recover_cache(primary_cache):
        if _temp_file.exists():
            logger.warning("Primary cache recovered, clearing and resuming use.")
            # Clear the primary cache
            logger.debug("Clearing primary cache from recovery")
            primary_cache.clear()
            # Clear the backup cache just incase we need to fall back again (don't want it out of sync)
            fallback_cache = django_cache.caches.create_connection(FALLBACK_CACHE)
            logger.debug("Clearing fallback cache from recovery")
            fallback_cache.clear()
            logger.debug("Removing fallback cache file indicator")
            _temp_file.unlink()

    @staticmethod
    def check_primary_cache():
        try:
            primary_cache = django_cache.caches.create_connection(PRIMARY_CACHE)
            primary_cache.get('up_test')
            logger.debug("Was able to read cache, attempting to revert to primary cache")
            if _HAS_UWSGI:
                logger.debug("Locking with uwsgi")
                got_lock = False
                try:
                    uwsgi.lock(_fail_back_uwsgi_lock_number)
                    got_lock = True
                    DABCacheWithFallback.recover_cache(primary_cache)
                except Exception:
                    pass
                finally:
                    if got_lock:
                        uwsgi.unlock(_fail_back_uwsgi_lock_number)
            else:
                logger.debug("Not running under uwsgi, locking with multiprocessing")
                with multiprocessing.Lock():
                    DABCacheWithFallback.recover_cache(primary_cache)
        except Exception:
            pass
