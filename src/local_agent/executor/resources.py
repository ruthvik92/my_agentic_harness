"""Read kernel counters from an inspected container without forking inside it.

This sampler runs on the Docker host. Remote daemons and controllers without
host cgroup access return unavailable evidence rather than guessed counters.
"""

import re
from pathlib import Path


class PidsMonitor:
    def __init__(self, info, *, proc_root=Path('/proc'), cgroup_root=Path('/sys/fs/cgroup')):
        self.info = info
        self.proc_root, self.root = proc_root, cgroup_root
        self.path = None
        self.unavailable = None

    def sample(self):
        try:
            if self.path is None:
                pid, cid = self.info['State'].get('Pid', 0), self.info['Id']
                if not pid:
                    return None
                if not re.fullmatch(r'[0-9a-f]{64}', cid) or type(pid) is not int or pid < 1:
                    raise ValueError('invalid inspected container identity')
                lines = (self.proc_root / str(pid) / 'cgroup').read_text().splitlines()
                relative = next(line[3:] for line in lines if line.startswith('0::'))
                parts = Path(relative).parts
                if '..' in parts or not any(p in {cid, 'docker-' + cid + '.scope'} for p in parts):
                    raise ValueError('cgroup is not bound to the inspected container')
                candidate = (self.root / relative.lstrip('/')).resolve()
                if not candidate.is_relative_to(self.root.resolve()):
                    raise ValueError('invalid cgroup path')
                self.path = candidate
            def number(name):
                value = (self.path / name).read_text().strip()
                if not re.fullmatch(r'[0-9]{1,20}', value):
                    raise ValueError('invalid numeric cgroup counter')
                return int(value)
            events = dict(line.split() for line in (self.path / 'pids.events').read_text().splitlines())
            raw_events = events['max']
            if not re.fullmatch(r'[0-9]{1,20}', raw_events):
                raise ValueError('invalid event counter')
            result = {'current': number('pids.current'), 'limit': number('pids.max'),
                      'max_events': int(raw_events), 'source': 'host_cgroup_v2'}
            try:
                result['peak'] = number('pids.peak')
            except FileNotFoundError:
                pass
            self.unavailable = None
            return result
        except (OSError, ValueError, StopIteration, KeyError):
            self.unavailable = 'Host cgroup counters unavailable for this container'
            return None


def exhausted(before, after, *, failed):
    """A historical peak/event alone is not evidence of this command failing."""
    if not after:
        return False
    full = after['current'] >= after['limit']
    new_rejection = bool(before and type(before.get('max_events')) is int
                         and type(after.get('max_events')) is int
                         and after['max_events'] > before['max_events'])
    return full or (failed and new_rejection)
