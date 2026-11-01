"""Trusted runner source executed inside the existing offline tool protocol."""

RUNNER = r'''
import hashlib,json,os,pathlib,shutil,signal,subprocess,sys
project=pathlib.Path('/workspace/project')
work=pathlib.Path('/workspace/tools/project-tests')
work.mkdir(parents=True,exist_ok=True)
plan=json.loads(sys.argv[1])
report={'plan_hash':plan['hash'],'status':'environment_blocked','setup':None,'commands':[],'network':'none'}

def execute(argv,cwd,env,timeout):
    proc=subprocess.Popen(argv,cwd=cwd,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,start_new_session=True)
    try:
        out,err=proc.communicate(timeout=timeout)
        return proc.returncode,out,err
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid,signal.SIGKILL)
        out,err=proc.communicate()
        return 124,out,err

try:
    env=dict(os.environ)
    env.update(PIP_NO_INDEX='1',PIP_DISABLE_PIP_VERSION_CHECK='1',UV_OFFLINE='1',PYTHONDONTWRITEBYTECODE='1')
    python=sys.executable
    if plan['install_project']:
        virtual=work/'venv'
        if not (virtual/'bin/python').exists():
            code,out,err=execute([python,'-m','venv','--system-site-packages',str(virtual)],project,env,120)
            if code:raise RuntimeError('Offline virtualenv preparation failed: '+err[-3000:])
        python=str(virtual/'bin/python')
        env['PATH']=str(virtual/'bin')+os.pathsep+env.get('PATH','')
        env['VIRTUAL_ENV']=str(virtual)
        install=work/'install-source'
        if install.exists():shutil.rmtree(install)
        shutil.copytree(project,install,ignore=shutil.ignore_patterns('.git','.venv','__pycache__','.pytest_cache','.ruff_cache','*.egg-info','build','dist'),symlinks=False)
        code,out,err=execute([python,'-m','pip','install','--no-index','--no-deps','--no-build-isolation','--no-cache-dir','--force-reinstall',str(install)],work,env,120)
        report['setup']={'exit_code':code,'output':(out+err)[-4000:]}
        if code:raise RuntimeError('Offline project installation failed: '+err[-3000:])
    env['PYTHONPATH']=str(project/'src')+os.pathsep+str(project)
    env['PATH']=str(pathlib.Path(python).parent)+os.pathsep+env.get('PATH','')
    if not plan['commands']:
        report['status']='no_test_plan'
    else:
        report['status']='passed'
    plugin="""import json,sys,pytest
class Counts:
 def pytest_sessionfinish(self,session,exitstatus):
  self.collected=session.testscollected
p=Counts()
code=pytest.main(json.loads(sys.argv[1]),plugins=[p])
print('LOCAL_AGENT_TEST_RESULT='+json.dumps({'collected':getattr(p,'collected',0)}))
raise SystemExit(int(code))
"""
    for check in plan['commands']:
        argv=list(check['argv'])
        is_pytest=(len(argv)>=3 and argv[0] in ('python','python3') and argv[1:3]==['-m','pytest']) or argv[0]=='pytest'
        if is_pytest:
            args=argv[3:] if argv[0]!='pytest' else argv[1:]
            actual=[python,'-c',plugin,json.dumps(args)]
        else:
            actual=[python,*argv[1:]] if argv[0] in ('python','python3') else argv
        code,out,err=execute(actual,project/check['cwd'],env,plan['timeout_seconds'])
        counts=None
        for line in reversed(out.splitlines()):
            if line.startswith('LOCAL_AGENT_TEST_RESULT='):
                counts=json.loads(line.split('=',1)[1]);break
        status='passed' if code==0 else 'test_failed'
        if code==124:status='timeout'
        elif is_pytest and (code==5 or (counts and counts['collected']==0 and code==0)):status='no_tests'
        elif is_pytest and code in (2,3,4):status='collection_error'
        if any(str(part).endswith('/harness_browser_test.py') for part in argv):
            try:
                browser=json.loads(out)
                if browser.get('runner')=='harness_browser_test' and code!=0:
                    status={'missing_executable':'environment_blocked','timeout':'timeout',
                            'invalid_plan':'collection_error','test_failure':'test_failed'}.get(browser.get('status'),'environment_blocked')
            except (ValueError,TypeError,AttributeError):
                pass
        item={**check,'exit_code':code,'status':status,'counts':counts,'output':(out+err)[-12000:]}
        report['commands'].append(item)
        if status!='passed':report['status']=status
except Exception as exc:
    report['status']='environment_blocked'
    report['error']=str(exc)[:4000]
print(json.dumps(report))
raise SystemExit(0 if report['status']=='passed' else 1)
'''


def arguments(plan):
    import json

    return {
        "argv": ["python", "-I", "-c", RUNNER, json.dumps(plan)],
        "cwd": "project",
        "timeout_seconds": 300,
    }
