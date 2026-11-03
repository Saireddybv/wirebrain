"""Independent proxy recovery when the recorder exits without running finally."""
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from .capture import reset_proxy


def watch(home, session, stream):
    # Only the recorder owns the write end. EOF also arrives after a forced kill.
    while stream.read(1):
        pass
    for attempt in range(3):
        try:
            reset_proxy(home, expected_session=session)
            return
        except (OSError, ValueError):
            if attempt == 2:
                raise
            time.sleep(1)


def start(home, session):
    home = Path(home).resolve()
    ready = home / f'proxy-guard-{session}.ready'
    flags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0
    with (home / 'proxy-guard.log').open('ab') as log:
        proc = subprocess.Popen([sys.executable, '-m', 'wirebrain.proxy_guard', str(home), session],
                                stdin=subprocess.PIPE, stdout=log, stderr=log,
                                creationflags=flags, start_new_session=os.name != 'nt')
    try:
        deadline = time.monotonic() + 10
        while not ready.exists():
            if proc.poll() is not None or time.monotonic() >= deadline:
                raise ValueError('Proxy recovery could not start; system proxy was not changed. Check proxy-guard.log.')
            time.sleep(.05)
        return proc
    except BaseException:
        finish(proc)
        raise
    finally:
        ready.unlink(missing_ok=True)


def finish(proc):
    if proc.stdin:
        proc.stdin.close()
    try:
        proc.wait(timeout=8)
    except subprocess.TimeoutExpired:
        # Leave recovery alive instead of killing it while restoring the OS.
        pass


def main():
    home, session = sys.argv[1:]
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    (Path(home) / f'proxy-guard-{session}.ready').touch()
    watch(home, session, sys.stdin.buffer)


if __name__ == '__main__':
    main()
