# Logging

django-ansible-base uses Python's logging library to emit messages as needed. If you would like to control the messages coming out of django-ansible-base you can add a logger for `ansible_base` like:

```
        'ansible_base': {
            'handlers': ['console'],
            'level': 'DEBUG',
        },
```

## Logging request IDs

django-ansible-base provides machinery (middleware and logging filters) to inject the request id into the logging format string.
The request id should come through as a header in the request, `X-Request-Id` (case-insensitive).

To enable logging of request ids, make the following changes to your application's `settings.py`:

1. Add `'ansible_base.lib.middleware.logging.LogRequestMiddleware'` to `MIDDLEWARE`. This is a middleware that simply
   adds the current request object to the thread-local state, so that the logging filter (in the following steps) can
   make use of it.

2. Configure `LOGGING`

   a. Add the logging filter to `LOGGING['filters']`

   b. Enable the filter in `LOGGING['handlers']`

   c. Make use of the `request_id` parameter in `LOGGING['formatters']`

```python
LOGGING = {
    # ...
    'filters': {
        'request_id_filter': {  # (a)
            '()': 'ansible_base.lib.logging.filters.RequestIdFilter',
        },
    },
    # ...
    'formatters': {
        'simple': {'format': '%(asctime)s %(levelname)-8s [%(request_id)s]  %(name)s %(message)s'},  # (b)
    },
    # ...
    'handlers': {
        'console': {
            '()': 'logging.StreamHandler',
            'level': 'DEBUG',
            'formatter': 'simple',
            'filters': ['request_id_filter'],  # (c)
        },
    },
```

After that, the request ID should automatically show up in logs, when the header is passed in.

## Logging Stack on Timeout

django-ansible-base provides machinery to print the stack trace when a request times out.
To do this, you will need to:

1. Set uwsgi params similar to that in `test_app/uwsgi.ini`.
2. Add `ansible_base.lib.middleware.logging.LogTracebackMiddleware` to `MIDDLEWARE` setting

You can try to test this with test_app by running the docker compose server (so it runs with uwsgi),
and then visiting http://localhost:8000/api/v1/timeout_view/ and viewing the logs.
Within those logs, you should be able to see the culprit:

```
test_app-1    |   File "/src/test_app/views.py", line 185, in timeout_view
test_app-1    |     time.sleep(60*10)  # 10 minutes
```

## Method Runtime Helper

As a general utility, sometimes you want to log if a particular method takes longer than a certain time.
This is true in almost any case where a method is doing something known to be performance-sensitive,
such as processing Ansible facts in AWX.

```python
import logging
from ansible_base.lib.logging.runtime import log_excess_runtime

logger = logging.getLogger('my_app.tasks.cleanup')

@log_excess_runtime(logger, cutoff=2.0)
def cleanup(self):
    # Do stuff that could take a long time
```

Then if the `cleaup` method takes over 2.0 seconds, you should see a log like this:

```
DEBUG    dab_runtime_logger:runtime.py:42 Running 'cleanup' took 2.30s
```

Because you are passing in your own logger, you can control everything about how those logs are handed.
If you need to customize the thresholds or log message, you can pass kwards to
the `@log_excess_runtime` call.
 - `cutoff` - time cutoff, any time greater than this causes an INFO level log
 - `debug_cutoff` - any time greater than this causes a DEBUG level log
 - `msg` - the log message with format strings in it
 - `add_log_data` - add a kwarg `log_data` to the method call as a dict that the method can attach additional log data to

The `msg` and `add_log_data` are intended to interact.
For an example, imagine that the `cleanup` method deletes files an keeps a count, `deleted_count`.
The number of deleted fields could be added to the log message with this.

```python
import logging
from ansible_base.lib.logging.runtime import log_excess_runtime

logger = logging.getLogger('my_app.tasks.cleanup')

@log_excess_runtime(logger, cutoff=2.0, msg='Cleanup took {delta:.2f}s, deleted {files_deleted}')
def cleanup(self, log_data):
    # Do stuff that could take a long time
    log_data['files_deleted'] = deleted_count
```
