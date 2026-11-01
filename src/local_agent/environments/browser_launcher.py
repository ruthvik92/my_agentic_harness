#!/usr/local/bin/python
"""Trusted headless launcher; each invocation owns one Chromium process group."""

import os
import signal
import subprocess
import sys
from contextlib import contextmanager

BINARY = '/usr/lib/chromium/chromium-headless-shell'
USAGE = '''Usage: harness-browser [Chromium headless options] URL
Examples:
  harness-browser --dump-dom file:///workspace/project/index.html
  harness-browser --user-data-dir=/tmp/unique-profile --remote-debugging-port=0 about:blank
For CDP use an isolated profile/port, wait for readiness, and terminate + await
this launcher in your client's finally block. Each invocation owns and cleans up
its browser process group, including if the launcher is killed.
--help prints this message without starting Chromium; --version prints its version.
'''


def kill_group(pid):
    try:
        os.killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


@contextmanager
def browser_session(argv, binary=BINARY, pass_fds=(), stdout=None, stderr=None):
    # Watch a parent-held pipe so even SIGKILL of the launcher cleans up Chrome.
    # The watchdog cannot retain the client's stdout/stderr pipes.
    read_fd, write_fd = os.pipe()
    try:
        watcher = os.fork()
    except BaseException:
        os.close(read_fd)
        os.close(write_fd)
        raise
    if watcher == 0:
        os.setsid()
        os.close(write_fd)
        for entry in os.listdir('/proc/self/fd'):
            fd = int(entry)
            if fd != read_fd:
                try:
                    os.close(fd)
                except OSError:
                    pass
        try:
            data = b''
            while not data.endswith(b'\n'):
                chunk = os.read(read_fd, 64)
                if not chunk:
                    os._exit(0)
                data += chunk
            pid = int(data.strip())
            while os.read(read_fd, 64):
                pass
            kill_group(pid)
        finally:
            os._exit(0)
    os.close(read_fd)
    child = None
    handlers = {}
    try:
        child = subprocess.Popen([binary, *argv], start_new_session=True, pass_fds=pass_fds,
                                 stdout=stdout, stderr=stderr)
        os.write(write_fd, (str(child.pid) + '\n').encode())
        for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
            handlers[sig] = signal.getsignal(sig)
            signal.signal(sig, lambda *_: kill_group(child.pid))
        yield child
    finally:
        if child is not None:
            kill_group(child.pid)
            child.wait()
        os.close(write_fd)
        os.waitpid(watcher, 0)
        for sig, handler in handlers.items():
            signal.signal(sig, handler)


def launch(argv, binary=BINARY):
    with browser_session(argv, binary=binary) as child:
        return child.wait()


def main():
    if '--help' in sys.argv[1:] or '-h' in sys.argv[1:]:
        print(USAGE)
        return 0
    if sys.argv[1:] == ['--version']:
        return subprocess.call([BINARY, '--version'])
    os.sched_setaffinity(0, sorted(os.sched_getaffinity(0))[:2])
    return launch(['--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu',
                   '--renderer-process-limit=1', '--num-raster-threads=1', *sys.argv[1:]])


if __name__ == '__main__':
    sys.exit(main())
