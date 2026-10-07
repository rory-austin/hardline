import fcntl
import functools
import inspect
import os
from contextlib import contextmanager

from hardline.runtime import STATE


@contextmanager
def lock(name):
    STATE.mkdir(exist_ok=True)
    fd = os.open(STATE / (name + ".lock"), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError(
                "Another " + name + " operation is running; retry later"
            ) from None
        yield
    finally:
        os.close(fd)


def serialized(fn):
    if inspect.iscoroutinefunction(fn):

        @functools.wraps(fn)
        async def wrapped(*args, **kwargs):
            with lock("lifecycle"):
                return await fn(*args, **kwargs)
    else:

        @functools.wraps(fn)
        def wrapped(*args, **kwargs):
            with lock("lifecycle"):
                return fn(*args, **kwargs)

    return wrapped
