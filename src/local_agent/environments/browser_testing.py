"""Dependency-free, bounded CDP browser interactions in the existing offline sandbox.

The host stages this module with its trusted lifecycle source. Project plans are
untrusted browser tests, never host commands or installation recipes.
"""

import argparse
import fcntl
import json
import os
import select
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

if 'LIFECYCLE_SOURCE' in globals():
    _lifecycle = {'__name__': 'harness_browser_lifecycle'}
    exec(compile(globals()['LIFECYCLE_SOURCE'], '<trusted-browser-lifecycle>', 'exec'), _lifecycle)
    browser_session = _lifecycle['browser_session']
else:
    from local_agent.environments.browser_launcher import browser_session

WRAPPER = '''import os,sys
r,w=int(sys.argv[1]),int(sys.argv[2])
os.dup2(r,3);os.dup2(w,4)
for fd in (r,w):
 if fd not in (3,4):os.close(fd)
os.execv(sys.argv[3],sys.argv[3:])
'''


class BrowserFailure(RuntimeError):
    def __init__(self, kind, message):
        self.kind = kind
        super().__init__(message)


class Browser:
    def __init__(self, timeout=30):
        self.deadline = time.monotonic() + timeout
        self.sequence, self.buffer, self.session = 0, b'', None
        self.owner, self.context, self.process = None, None, None
        self.read_fd = self.write_fd = None

    def __enter__(self):
        binary = shutil.which('chromium-headless-shell') or shutil.which('chromium')
        if not binary:
            raise BrowserFailure('missing_executable', 'Interactive browser requires Chromium; request prepare_environment with capabilities=["browser_interaction"].')
        self.owner = tempfile.TemporaryDirectory(prefix='harness-browser-test-')
        self.profile = Path(self.owner.name)
        r, w = os.pipe()
        out, incoming = os.pipe()
        # Duplication targets 3/4 must not overwrite either source descriptor.
        browser_r = fcntl.fcntl(r, fcntl.F_DUPFD_CLOEXEC, 10)
        browser_w = fcntl.fcntl(incoming, fcntl.F_DUPFD_CLOEXEC, 10)
        os.close(r)
        os.close(incoming)
        self.read_fd, self.write_fd = out, w
        self.log = (self.profile / 'browser.log').open('wb')
        args = ['-I', '-c', WRAPPER, str(browser_r), str(browser_w), binary,
                '--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu',
                '--renderer-process-limit=1', '--num-raster-threads=1',
                '--user-data-dir=' + str(self.profile / 'profile'),
                '--remote-debugging-pipe', 'about:blank']
        self.context = browser_session(args, binary=sys.executable,
                                       pass_fds=(browser_r, browser_w),
                                       stdout=subprocess.DEVNULL, stderr=self.log)
        try:
            self.process = self.context.__enter__()
            self.version = self.call('Browser.getVersion')
            target = self.call('Target.createTarget', {'url': 'about:blank'})['targetId']
            self.session = self.call('Target.attachToTarget', {'targetId': target, 'flatten': True})['sessionId']
            self.call('Page.enable')
        except BaseException:
            self.__exit__(*sys.exc_info())
            raise
        finally:
            os.close(browser_r)
            os.close(browser_w)
        return self

    def __exit__(self, *_):
        if self.context and self.process:
            self.context.__exit__(None, None, None)
        for fd in (self.read_fd, self.write_fd):
            if fd is not None:
                os.close(fd)
        if self.owner:
            self.log.close()
            self.owner.cleanup()

    def call(self, method, params=None):
        self.sequence += 1
        msg = {'id': self.sequence, 'method': method, 'params': params or {}}
        if self.session:
            msg['sessionId'] = self.session
        pending = memoryview(json.dumps(msg).encode() + b'\0')
        os.set_blocking(self.write_fd, False)
        while pending:
            remaining = self.deadline - time.monotonic()
            if remaining <= 0 or not select.select([], [self.write_fd], [], max(0, remaining))[1]:
                raise BrowserFailure('timeout', 'Browser request deadline reached')
            try:
                written = os.write(self.write_fd, pending)
            except BlockingIOError:
                continue
            except BrokenPipeError:
                raise BrowserFailure('browser_exited', 'Browser debugging pipe closed') from None
            pending = pending[written:]
        while True:
            while b'\0' in self.buffer:
                raw, self.buffer = self.buffer.split(b'\0', 1)
                value = json.loads(raw)
                if value.get('id') == self.sequence:
                    if 'error' in value:
                        raise BrowserFailure('protocol_error', str(value['error'])[:1000])
                    return value.get('result', {})
            remaining = self.deadline - time.monotonic()
            if remaining <= 0:
                raise BrowserFailure('timeout', 'Browser command deadline reached')
            if not select.select([self.read_fd], [], [], remaining)[0]:
                raise BrowserFailure('timeout', 'Browser response deadline reached')
            chunk = os.read(self.read_fd, 65536)
            if not chunk:
                raise BrowserFailure('browser_exited', 'Browser debugging pipe closed')
            self.buffer += chunk
            if len(self.buffer) > 4 * 1024 * 1024:
                raise BrowserFailure('output_limit', 'Browser response exceeds 4 MiB')

    def evaluate(self, expression):
        result = self.call('Runtime.evaluate', {'expression': expression, 'returnByValue': True,
                                              'awaitPromise': True})
        if result.get('exceptionDetails'):
            raise BrowserFailure('test_failure', 'AssertionError: browser expression threw: '
                                 + str(result['exceptionDetails'])[:1000])
        return result.get('result', {}).get('value')

    def wait(self, expression):
        while not self.evaluate(expression):
            remaining = self.deadline - time.monotonic()
            if remaining <= 0:
                raise BrowserFailure('timeout', 'Wait condition was not satisfied')
            time.sleep(min(.05, remaining))

    def element(self, selector):
        return 'document.querySelector(' + json.dumps(selector) + ')'

    def step(self, item):
        action = item['action']
        if action == 'navigate':
            self.call('Page.navigate', {'url': item['url']})
            self.wait('location.href === ' + json.dumps(item['url']) + ' && document.readyState === "complete"')
        elif action == 'reload':
            previous = self.call('Page.getFrameTree')['frameTree']['frame'].get('loaderId')
            self.call('Page.reload', {'ignoreCache': True})
            while self.call('Page.getFrameTree')['frameTree']['frame'].get('loaderId') == previous:
                if time.monotonic() >= self.deadline:
                    raise BrowserFailure('timeout', 'Reload did not create a new document')
                time.sleep(.01)
            self.wait('document.readyState === "complete"')
        elif action == 'init':
            self.call('Page.addScriptToEvaluateOnNewDocument', {'source': item['expression']})
        elif action in {'evaluate', 'wait', 'assert'}:
            if action == 'wait':
                self.wait(item['expression'])
            else:
                value = self.evaluate(item['expression'])
                if action == 'assert' and value is not True:
                    raise BrowserFailure('test_failure', 'AssertionError: ' + item.get('name', item['expression'])[:600])
        elif action in {'click', 'fill', 'press'}:
            selector = item['selector']
            element = self.element(selector)
            if action in {'click', 'fill'}:
                box = self.evaluate('(()=>{const e=' + element + ';if(!e)return null;'
                                    'const r=e.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2,w:r.width,h:r.height}})()')
                if not box or box['w'] <= 0 or box['h'] <= 0:
                    raise BrowserFailure('test_failure', 'AssertionError: selector is absent or not visible: ' + selector)
                for kind in ('mousePressed', 'mouseReleased'):
                    self.call('Input.dispatchMouseEvent', {'type': kind, 'x': box['x'], 'y': box['y'],
                                                          'button': 'left', 'clickCount': 1})
            if action == 'fill':
                self.evaluate(element + '.focus();' + element + '.select()')
                self.call('Input.insertText', {'text': item['value']})
            if action == 'press':
                self.evaluate(element + '.focus()')
                key = item['key']
                codes = {'Enter': ('Enter', 13), ' ': ('Space', 32), 'ArrowLeft': ('ArrowLeft', 37),
                         'ArrowRight': ('ArrowRight', 39), 'Escape': ('Escape', 27), 'Tab': ('Tab', 9)}
                upper = key.upper()
                fallback = (('Key' + upper, ord(upper)) if len(upper) == 1 and 'A' <= upper <= 'Z'
                            else ('Digit' + key, ord(key)) if len(key) == 1 and '0' <= key <= '9'
                            else ('Unidentified', 0))
                code, virtual = codes.get(key, fallback)
                args = {'key': key, 'code': code, 'windowsVirtualKeyCode': virtual}
                if len(key) == 1:
                    args['text'] = key
                self.call('Input.dispatchKeyEvent', {'type': 'keyDown', **args})
                self.call('Input.dispatchKeyEvent', {'type': 'keyUp', **args})
        else:
            raise ValueError('Unknown browser action: ' + action)


def validate(plan):
    if not isinstance(plan, dict) or set(plan) != {'version', 'steps'} or type(plan['version']) is not int or plan['version'] != 1:
        raise ValueError('Browser plan requires version=1 and steps')
    if not isinstance(plan['steps'], list) or not 1 <= len(plan['steps']) <= 100:
        raise ValueError('Browser plan requires 1..100 steps')
    fields = {'navigate': {'url'}, 'reload': set(), 'init': {'expression'},
              'evaluate': {'expression'}, 'wait': {'expression'}, 'assert': {'expression'},
              'click': {'selector'}, 'fill': {'selector', 'value'}, 'press': {'selector', 'key'}}
    for item in plan['steps']:
        if not isinstance(item, dict) or not isinstance(item.get('action'), str) or item['action'] not in fields:
            raise ValueError('Invalid browser action')
        required = fields[item['action']] | {'action'}
        if not required <= set(item) or set(item) - required - {'name'}:
            raise ValueError('Invalid browser action fields')
        if any(not isinstance(v, str) or len(v) > 16000 for k, v in item.items() if k != 'action'):
            raise ValueError('Browser action values must be bounded strings')
    return plan


def run(plan, timeout=30):
    validate(plan)
    report = {'runner': 'harness_browser_test', 'version': 1, 'status': 'passed', 'steps': []}
    try:
        with Browser(timeout) as browser:
            for index, item in enumerate(plan['steps']):
                browser.step(item)
                report['steps'].append({'index': index, 'action': item['action'], 'name': item.get('name'),
                                        'status': 'passed'})
    except BrowserFailure as exc:
        report.update(status=exc.kind, error=str(exc), failed_step=len(report['steps']))
    return report


def self_test(timeout=20):
    with tempfile.TemporaryDirectory(prefix='harness-browser-probe-') as directory:
        page = Path(directory) / 'page.html'
        page.write_text('<input id="name"><button id="save" onclick="localStorage.setItem(\'name\',document.querySelector(\'#name\').value)">Save</button>')
        return run({'version': 1, 'steps': [
            {'action': 'navigate', 'url': page.as_uri()},
            {'action': 'fill', 'selector': '#name', 'value': 'Ada'},
            {'action': 'press', 'selector': '#name', 'key': ' '},
            {'action': 'press', 'selector': '#name', 'key': 'L'},
            {'action': 'assert', 'expression': 'document.querySelector("#name").value === "Ada L"'},
            {'action': 'click', 'selector': '#save'},
            {'action': 'reload'},
            {'action': 'assert', 'expression': 'localStorage.getItem("name") === "Ada L"'},
        ]}, timeout)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='Plan JSON: {"version":1,"steps":[{"action":"navigate","url":"file:///workspace/project/index.html"},{"action":"assert","expression":"document.title.length > 0"}]}\nActions (required fields): navigate(url), reload(), init(expression: JS before future documents),\nevaluate(expression), wait(expression: truthy), assert(expression: strictly true),\nclick(selector), fill(selector,value), press(selector,key). Each accepts optional name.\nUse real key values, e.g. " " for Space or "Enter". Plans have 1..100 steps.\nOne deadline covers browser startup and all steps. A fresh profile isolates every invocation.\nExit 0: all assertions passed. Nonzero: inspect JSON status/error/failed_step; do not treat\nmissing tooling or a timeout as a reproduced assertion failure.')
    parser.add_argument('--self-test', action='store_true')
    parser.add_argument('--plan', type=Path)
    parser.add_argument('--timeout', type=float, default=30)
    args = parser.parse_args()
    if not 0 < args.timeout <= 240:
        parser.error('timeout must be within (0,240] seconds')
    try:
        if hasattr(os, 'sched_getaffinity'):
            os.sched_setaffinity(0, sorted(os.sched_getaffinity(0))[:2])
        if args.self_test:
            report = self_test(args.timeout)
        elif args.plan and args.plan.stat().st_size <= 1024 * 1024:
            report = run(json.loads(args.plan.read_text()), args.timeout)
        else:
            parser.error('provide --self-test or a plan file no larger than 1 MiB')
        print(json.dumps(report))
        return 0 if report['status'] == 'passed' else 1
    except (ValueError, OSError) as exc:
        print(json.dumps({'runner': 'harness_browser_test', 'version': 1,
                          'status': 'invalid_plan', 'error': str(exc)[:1000]}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
