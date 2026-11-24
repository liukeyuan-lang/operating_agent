"""Shared cross-process JSON write lock."""
import os
import time
from contextlib import contextmanager

@contextmanager
def file_lock(path):
    """OS releases this small lock on process exit, including after a crash."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(str(path)+".lock", "a+b") as lock:
        lock.seek(0,2)
        if lock.tell() == 0:
            lock.write(b"0")
            lock.flush()
        acquired = False
        for _ in range(20):
            try:
                lock.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
                else:
                    import fcntl
                    fcntl.flock(lock.fileno(),fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except OSError:
                time.sleep(.05)
        if not acquired:
            raise ValueError("记录正在保存，请稍后重试")
        try:
            yield
        finally:
            lock.seek(0)
            if os.name == "nt":
                msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1)
            else:
                fcntl.flock(lock.fileno(),fcntl.LOCK_UN)

