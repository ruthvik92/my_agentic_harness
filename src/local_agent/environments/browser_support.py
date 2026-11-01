"""Stage a versioned browser runner and probe the exact image, without project imports."""

import json
import os
import uuid
from pathlib import Path

from local_agent.storage.blobs import canonical, digest, private_directory


def runner_source():
    directory = Path(__file__).parent
    lifecycle = (directory / 'browser_launcher.py').read_text()
    return ('LIFECYCLE_SOURCE = ' + repr(lifecycle) + '\n'
            + (directory / 'browser_testing.py').read_text()).encode()


def stage(agent):
    events = [e for e in agent.store.events(agent.run_id) if e.event_type == 'environment.runner']
    if events:
        source = agent.store.blobs.read(events[0].data['source_ref'])
    else:
        source = runner_source()
        agent.event('environment.runner', 'controller', {
            'source_ref': agent.store.blobs.put(source), 'hash': digest(source),
            'command': ['python', '/workspace/tools/harness_browser_test.py'],
        })
    directory = os.open(agent.path / 'tools', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    temporary = '.browser-runner-' + uuid.uuid4().hex
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600, dir_fd=directory)
        try:
            remaining = memoryview(source)
            while remaining:
                remaining = remaining[os.write(fd, remaining):]
            os.fsync(fd)
        finally:
            os.close(fd)
        # Replace the directory entry instead of following model-created symlinks/hard links.
        os.replace(temporary, 'harness_browser_test.py', src_dir_fd=directory, dst_dir_fd=directory)
        os.fsync(directory)
    finally:
        try:
            os.unlink(temporary, dir_fd=directory)
        except FileNotFoundError:
            pass
        os.close(directory)
    agent.browser_runner_source = source


async def probe_interactions(agent, runner, sandbox):
    source = getattr(agent, 'browser_runner_source', runner_source())
    key = digest(canonical({'image': sandbox['image'], 'runner': digest(source),
                            'settings': agent.config.execution.model_dump(mode='json')}))
    cache = agent.store.control / 'browser-probes'
    private_directory(cache)
    path = cache / (key[7:] + '.json')
    if path.exists():
        try:
            result = json.loads(path.read_text())
            if result.get('available') is True and result.get('runner_hash') == digest(source):
                # Produce run-owned evidence; the original cache may belong to another run.
                if result.get('report'):
                    result['evidence_ref'] = agent.store.blobs.put_json(result['report'])
                return {**result, 'cached': True}
        except (ValueError, AttributeError):
            pass  # Corrupt cache never establishes capability readiness.
    command = ['run', '--rm', '--network', 'none', '--read-only',
               '--user', f'{os.getuid()}:{os.getgid()}',
               '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
               '--pids-limit', str(agent.config.execution.container_pids_limit),
               '--memory', str(agent.config.execution.container_memory_limit) + 'm',
               '--cpus', str(agent.config.execution.container_cpu_limit),
               '--tmpfs', '/tmp:rw,nosuid,nodev,size=128m',
               '--entrypoint', 'python', sandbox['image'], '-I', '-c', source.decode(),
               '--self-test', '--timeout', '12']
    try:
        report = json.loads(await runner.run(command, timeout=20))
        ready = report.get('runner') == 'harness_browser_test' and report.get('status') == 'passed'
        result = {'available': ready, 'tested': True, 'status': report.get('status'),
                  'reason': report.get('error'), 'runner_hash': digest(source),
                  'evidence_ref': agent.store.blobs.put_json(report), 'report': report,
                  'command': ['python', '/workspace/tools/harness_browser_test.py', '--plan',
                              '/workspace/project/tests/browser-flow.json']}
    except (RuntimeError, ValueError) as exc:
        # Transient failures are reported, not cached as permanent absence.
        return {'available': False, 'tested': True, 'status': 'probe_failed',
                'reason': str(exc)[-1500:], 'runner_hash': digest(source)}
    if ready:
        from local_agent.executor.lifecycle import publish

        publish(path, result)
    return result
