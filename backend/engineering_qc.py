"""P6.4a: deterministic, read-only QA/QC evidence consolidation.

Not an approval or a production gate. Re-evaluate existing gates, do not
execute a model, Docker, GitHub writes, or create defects.
"""
import re
import sqlite3

import studio_coding as sc
import studio_verification as qa
import engineering_candidate_selection as sel
import engineering_sandbox as sb
import engineering_quality as quality
import engineering_draft as draft
import dependency_completion as dc
import project_planning as pp

FLAGS=sb.FLAGS
CHECKS=('binding','human_qa','candidate_selection','sandbox','defects','completion','draft','cross_binding')
HEX=re.compile(r'[a-f0-9]{64}\Z')


def hex_digest(value):
    return isinstance(value,str) and bool(HEX.fullmatch(value))


def view(c,db,pid,jid):
    out=dict(schema='orbit.engineering-qc-evidence.v1',project_id=pid,job_id=jid,
             state='BLOCK',checks={k:'BLOCK' for k in CHECKS},binding=None,receipts={},
             defect_counts=None,selected=None,findings=[],remote_live_verified=False,
             scope='development_evidence_only',**FLAGS)
    try:
        b=sc.evidence(c,pid,jid)
        if not b or b['state']!='BOUND' or b['job_id']!=jid:
            raise ValueError('Current binding required')
        out['binding']={k:b[k] for k in ('adoption_version','package_id','binding_digest','spec_digest')}
        out['checks']['binding']='PASS'
        q=qa.view(c,pid,jid);s=sel.view(c,db,pid,jid);r=sb.view(c,db,pid,jid)
        f=quality.view(c,db,pid,jid);d=draft.view(c,db,pid,jid)
        m=next((x for x in dc.view(c,pid)['items'] if x['job_id']==jid),{})
        checks=out['checks'];receipts=out['receipts']
        for name,item,state in (('human_qa',q,'HUMAN_QA_PASS'),('candidate_selection',s,'SELECTED'),
                                ('sandbox',r,'PASS'),('completion',m,'COMPLETION_EVIDENCE_CONFIRMED')):
            receipt=item.get('receipt') or {}
            if item.get('state')==state and hex_digest(receipt.get('digest')):
                checks[name]='PASS';receipts[name]=receipt['digest']
        counts=f.get('counts')
        if (isinstance(counts,dict) and set(counts)=={'OPEN','READY_FOR_RETEST','CLOSED'}
            and all(type(v) is int and v>=0 for v in counts.values())):
            out['defect_counts']=dict(counts)
            if (f.get('state')=='QUALITY_EVIDENCE_PASS' and not counts['OPEN']
                and not counts['READY_FOR_RETEST'] and hex_digest(f.get('source_digest'))):
                checks['defects']='PASS'
                receipts['quality_source']=f['source_digest']
                receipts['defect_history']=pp.digest(f['defects'])
        dr=d.get('receipt') or {}
        if (d.get('state')=='CREATED_DRAFT' and dr.get('status')=='CREATED_DRAFT'
            and (dr.get('remote') or {}).get('draft') is True
            and hex_digest(d.get('plan_digest')) and d['plan_digest']==dr.get('plan_digest')):
            checks['draft']='PASS';receipts['draft_plan']=d['plan_digest']
            receipts['draft_result']=pp.digest(dr)
        if all(checks[k]=='PASS' for k in CHECKS if k!='cross_binding'):
            qr,sr,rr,mr=(x['receipt'] for x in (q,s,r,m))
            src=q['source'];qs=f['source'];lane=sr['selected']
            candidates=src['candidates']
            criteria=qr['criteria'];expected={x['id'] for x in src['acceptance']}
            if (lane in ('A','B') and set(candidates)==set(rr['lanes'])==set(rr['git'])=={'A','B'}
                and expected and len(criteria)==len(expected) and {x['id'] for x in criteria}==expected
                and all(x['verdict']=='PASS' for x in criteria)
                and all(src[k]==out['binding'][k] for k in out['binding'])
                and src['project_id']==pid and src['job_id']==jid
                and qs['binding']==out['binding'] and qs['project_id']==pid and qs['job_id']==jid
                and s['source']['bound_evidence']==src
                and rr['selection_digest']==sr['digest'] and rr['selected']==lane
                and mr['selected']==lane and mr['selected_digest']==sr['selected_digest']==candidates[lane]['digest']
                and m['source']['qa_digest']==qr['digest']
                and qs['qa']['receipt_digest']==qr['digest'] and qs['qa']['source_digest']==q['source_digest']
                and qs['sandbox']['receipt_digest']==rr['digest'] and qs['sandbox']['source_digest']==r['source_digest']
                and all(rr['git'][k]['source_sha256']==rr['lanes'][k]['sha256']==candidates[k]['digest']
                        and rr['lanes'][k]['status']=='passed' and type(rr['lanes'][k]['test_count']) is int
                        and rr['lanes'][k]['test_count']>0 for k in ('A','B'))
                and all(dr.get(k) is False for k in FLAGS)):
                checks['cross_binding']='PASS';out['selected']=lane
    except (ValueError,KeyError,TypeError,AttributeError,PermissionError,sqlite3.Error,OSError):
        # Do not expose exceptions, source contents, review text or secrets.
        out.update(checks={k:'BLOCK' for k in CHECKS},binding=None,receipts={},
                   defect_counts=None,selected=None)
    out['findings']=[{'code':k.upper()+'_NOT_CURRENT','check':k} for k in CHECKS if out['checks'][k]!='PASS']
    if not out['findings']:out['state']='QA_QC_EVIDENCE_PASS'
    out['evidence_digest']=pp.digest(out)
    return out
