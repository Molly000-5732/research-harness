"""Explicit live plan -> design -> model code -> training -> analysis acceptance."""
import json
import time
import urllib.request
op=urllib.request.build_opener(urllib.request.ProxyHandler({}))
def call(path,body=None):
    data=None if body is None else json.dumps(body,ensure_ascii=False).encode()
    return json.load(op.open(urllib.request.Request('http://127.0.0.1:8001'+path,data=data,headers={'Content-Type':'application/json'})))
def wait(pid):
    end=time.monotonic()+650
    while time.monotonic()<end:
        p=call('/api/projects/'+pid);j=p['jobs'][-1]
        if j['status']!='running':
            assert j['status']=='completed',j
            print('PASS',j['stage'],flush=True)
            return p
        time.sleep(3)
    raise TimeoutError('task timeout')
import os
p=call('/api/projects/'+os.environ['BENCHMARK_PROJECT']) if os.environ.get('BENCHMARK_PROJECT') else call('/api/examples/digits',{})
pid=p['id'];print('PROJECT',pid,flush=True)
call('/api/projects/'+pid+'/start',{'stage':'plan'});p=wait(pid)
assert p['outputs']['plan']['schemaVersion']=='research-plan-v2'
call('/api/projects/'+pid+'/select',{'stage':'plan','itemId':p['outputs']['plan']['items'][0]['id']})
call('/api/projects/'+pid+'/start',{'stage':'experiment'});p=wait(pid)
call('/api/projects/'+pid+'/auto-run',{});p=wait(pid)
r=p['experimentRuns'][-1]
assert len(r['result']['runs'])==9
for filename in ['models.py','evaluate.py','protocol.json','result.json','report.md','execution.log','environment.json','metrics.csv','attempts.json','manifest.json']:
    response=op.open('http://127.0.0.1:8001/api/projects/'+pid+'/artifacts/'+r['id']+'/'+filename)
    assert response.status==200
    assert response.read()
print('PASS artifact downloads',flush=True)
call('/api/projects/'+pid+'/start',{'stage':'validation'});p=wait(pid)
print('LIVE BENCHMARK COMPLETE',pid,flush=True)
for row in r['result']['aggregates']:print(row['method'],round(row['noisyAccuracy']['mean']*100,4),flush=True)
