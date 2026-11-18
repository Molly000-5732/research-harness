"""Opt-in live E2E smoke. Uses DeepSeek credits; keeps its sample project."""
import argparse
import base64
import json
import time
import urllib.error
import urllib.request

opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
def call(path, body=None):
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode()
    return json.load(opener.open(urllib.request.Request('http://127.0.0.1:8001'+path, data=data, headers={'Content-Type':'application/json'}), timeout=30))
def wait(pid):
    deadline = time.monotonic()+650
    while time.monotonic()<deadline:
        p=call('/api/projects/'+pid)
        job=p['jobs'][-1]
        if job['status'] not in ['running','queued']:
            assert job['status']=='completed', job
            print('PASS',job['stage'],flush=True)
            return p
        time.sleep(3)
    raise TimeoutError('Live task did not finish')

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--project',required=True)
    args=parser.parse_args()
    pid=args.project
    p=wait(pid)
    for previous, stage in [('questions','painpoints'),('painpoints','plan'),('plan','experiment')]:
        call('/api/projects/'+pid+'/select',{'stage':previous,'itemId':p['outputs'][previous]['items'][0]['id']})
        call('/api/projects/'+pid+'/start',{'stage':stage})
        p=wait(pid)
        assert p['outputs'][stage]['engine']=='DeepSeek Harness'
    # A real deterministic arithmetic test to verify execution + analysis wiring.
    # This sample is deliberately NOT evidence for the research hypothesis.
    script="import json, statistics\na=[0.65,0.70,0.68]\nb=[0.72,0.73,0.75]\nprint('SOFTWARE PIPELINE TEST ONLY; NOT A RESEARCH EXPERIMENT')\nprint(json.dumps({'baseline_mean':statistics.mean(a),'sample_mean':statistics.mean(b),'n':3,'data_origin':'manually specified smoke test numbers'}))\n"
    call('/api/projects/'+pid+'/script',{'script':script})
    call('/api/projects/'+pid+'/run',{})
    p=wait(pid)
    assert p['experimentRuns'][-1]['exitCode']==0
    csv='purpose,baseline_mean,sample_mean,n\nsoftware_pipeline_test_only,0.6766667,0.7333333,3\n'
    call('/api/projects/'+pid+'/upload',{'kind':'results','name':'pipeline-test.csv','base64':base64.b64encode(csv.encode()).decode()})
    call('/api/projects/'+pid+'/start',{'stage':'validation'})
    p=wait(pid)
    assert len(p['outputs'])==5
    print('ALL FIVE MODEL OUTPUTS AND ACTUAL PYTHON RUN VERIFIED',pid,flush=True)
if __name__=='__main__':
    main()
