#!/usr/bin/env python3
"""Reject short, interrupted or incomplete soak evidence. Local evidence, not attestation."""
import json,sys
from pathlib import Path

def evaluate(report,samples):
    reasons=[]
    if report.get('schema')!='orbit.offline-stress.v1' or report.get('profile')!='soak24h' or report.get('gate')!='PASS' or report.get('duration_gate')!='PASS' or report.get('elapsed_seconds',0)<86400:
        reasons.append('actual_24h_client_gate_missing')
    if report.get('waves',0)<288 or report.get('requests')!=24*report.get('waves',0) or len(report.get('agent_counts',{}))!=24 or any(n!=report.get('waves') for n in report.get('agent_counts',{}).values()):
        reasons.append('agent_workload_incomplete')
    if not samples or any(s.get('gate')!='PASS' for s in samples) or len({s.get('container_id') for s in samples})!=1:
        reasons.append('container_gate_missing_or_failed')
    times=[s['sampled_at'] for s in samples]
    if len(times)<2 or times[-1]-times[0]<86300 or max((b-a for a,b in zip(times,times[1:])),default=999)>90 or any(b<a for a,b in zip(times,times[1:])):
        reasons.append('container_sampling_coverage_incomplete')
    if times and (times[0]>report.get('started_at',0)+90 or times[-1]<report.get('finished_at',0)-90):
        reasons.append('container_samples_not_aligned')
    return {'schema':'orbit.soak-acceptance.v1','gate':'BLOCK' if reasons else 'PASS','reasons':reasons,
            'client_elapsed_seconds':report.get('elapsed_seconds'),'container_samples':len(samples),'note':'Dedicated synthetic 24h local client soak only; not production signoff or GPU parallelism proof.'}

def main():
    root=Path(sys.argv[1])
    try:
        report=json.loads((root/'soak.json').read_text())
        samples=[json.loads(x) for x in (root/'container-samples.jsonl').read_text().splitlines()]
        data=evaluate(report,samples)
    except Exception as e:data={'schema':'orbit.soak-acceptance.v1','gate':'BLOCK','reasons':[type(e).__name__]}
    with (root/'acceptance.json').open('x',encoding='utf-8') as f:json.dump(data,f,indent=2)
    print(json.dumps(data,indent=2));return 0 if data['gate']=='PASS' else 2
if __name__=='__main__':raise SystemExit(main())
