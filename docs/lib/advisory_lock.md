## Database Named Locks

Django-ansible-base hosts its own specialized utility for obtaining named locks.
This follows the same contract as documented in the django-pglocks library

https://pypi.org/project/django-pglocks/

Due to a multitude of needs relevant to production use, discovered through its
use in AWX, a number of points of divergence have emerged such as:

 - the need to have it not error when running sqlite3 tests
 - stuck processes holding the lock forever (adding pg-level idle timeout)

The use for the purpose of a task would typically look like this

```python
from ansible_base.lib.utils.db import advisory_lock


def my_task():
    with advisory_lock('my_task_lock', wait=False) as held:
        if held is False:
            return
        # continue to run logic in my_task
```

This is very useful to assure that no other process _in the cluster_ connected
to the same postgres instance runs `my_task` at the same time as the process
calling it here.

The specific choice of `wait=False` and what to do when another task holds the lock,
is the choice of the programmer in the specific case.
In this case, the `return` would be okay in the situation where `my_task` is idempotent,
and there is a "fallback" schedule in case a call was missed.
The blocking/non-blocking choices are very dependent on the specific design and situation.
