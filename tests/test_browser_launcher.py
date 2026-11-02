"""The trusted launcher cleans up only its own browser invocation."""

import os
import signal
import subprocess
import sys
import time

import pytest

from local_agent.environments import browser_launcher


def test_help_does_not_start_browser(monkeypatch, capsys):
    monkeypatch.setattr(sys, 'argv', ['harness-browser', '--help'])
    monkeypatch.setattr(os, 'fork', lambda: pytest.fail('help must not fork'))
    assert browser_launcher.main() == 0
    assert 'terminate + await' in capsys.readouterr().out


@pytest.mark.parametrize('sig', [signal.SIGTERM, signal.SIGKILL])
def test_browser_group_cleaned_even_when_launcher_killed(tmp_path, sig):
    marker = tmp_path / 'pids'
    browser_code = '''import os,subprocess,sys,time
child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'])
open(sys.argv[1],'w').write(str(os.getpid())+' '+str(child.pid))
time.sleep(60)
'''
    driver = "import sys;from local_agent.environments.browser_launcher import launch;sys.exit(launch(['-c',sys.argv[1],sys.argv[2]],binary=sys.executable))"
    launcher = subprocess.Popen([sys.executable, '-c', driver, browser_code, str(marker)])
    pids = []
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if marker.exists() and len(marker.read_text().split()) == 2:
                pids = list(map(int, marker.read_text().split()))
                break
            time.sleep(.02)
        assert pids, 'browser did not start'
        launcher.send_signal(sig)
        launcher.wait(timeout=10)

        def alive(pid):
            try:
                return open('/proc/' + str(pid) + '/stat').read().split()[2] != 'Z'
            except (FileNotFoundError, ProcessLookupError):
                return False

        deadline = time.monotonic() + 5
        while any(alive(pid) for pid in pids) and time.monotonic() < deadline:
            time.sleep(.02)
        assert not any(alive(pid) for pid in pids)
    finally:
        if launcher.poll() is None:
            launcher.kill()
            launcher.wait(timeout=10)
        if pids:
            browser_launcher.kill_group(pids[0])
