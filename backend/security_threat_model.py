"""P6.5b: deterministic architecture baseline, not candidate analysis or approval."""
import security_evidence as security
pp=security.pp
FLAGS=dict(security.FLAGS,requirements_approved=False,threat_acceptance_authorized=False)
STRIDE=('SPOOFING','TAMPERING','REPUDIATION','INFORMATION_DISCLOSURE','DENIAL_OF_SERVICE','ELEVATION_OF_PRIVILEGE')
# Stable identifiers; explicit trust boundaries and mandatory verification obligations.
ASSETS=(
 ('A01','Identity, session and membership records'),
 ('A02','Project source, Git objects and candidate selection'),
 ('A03','Execution, audit and quality evidence'),
 ('A04','Provider and Git credentials'),
 ('A05','Worker, Docker and host resources'),
 ('A06','Dependencies, build images and artifacts'),
 ('A07','Deployment and release authority'),
)
BOUNDARIES=(
 ('B01','Browser to authenticated HTTP API',('A01','A02','A03','A07')),
 ('B02','API to project-scoped SQLite and Git workspace',('A01','A02','A03')),
 ('B03','Trusted runner to untrusted candidate container',('A02','A03','A04','A05')),
 ('B04','Backend to configured providers and GitHub',('A02','A04','A05','A07')),
 ('B05','Build inputs to CI and artifact consumers',('A03','A04','A05','A06','A07')),
 ('B06','Deployment proxy to backend transport',('A01','A04','A05','A07')),
)
# threat ID, STRIDE, severity, asset, boundary, risk, mandatory requirement, verification method
ROWS=(
 ('T01','SPOOFING','HIGH','A01','B01','Session impersonation','Reject missing, expired and revoked sessions; protect cookies.','DAST_SESSION'),
 ('T02','ELEVATION_OF_PRIVILEGE','CRITICAL','A02','B02','Cross-project or role escalation','Enforce current project membership and least privilege at every resource boundary.','DAST_RBAC'),
 ('T03','TAMPERING','HIGH','A07','B01','Cross-origin state mutation','Require origin and session-bound CSRF on every protected mutation.','DAST_CSRF'),
 ('T04','REPUDIATION','HIGH','A03','B02','Unaudited state transition','Bind explicit actor, outcome and immutable audit evidence to mutations.','AUDIT_INTEGRITY'),
 ('T05','TAMPERING','CRITICAL','A03','B05','Forged or stale execution and CI evidence','Verify exact source, receipt digests, run identity and fail closed on stale evidence.','EVIDENCE_INTEGRITY'),
 ('T06','ELEVATION_OF_PRIVILEGE','CRITICAL','A05','B03','Candidate escapes isolation','Enforce pinned images, nonroot, no privileges, readonly mounts and no network.','SANDBOX_RUNTIME'),
 ('T07','INFORMATION_DISCLOSURE','CRITICAL','A04','B03','Candidate accesses host secrets','Deny host credential and sensitive mount exposure; verify no secret leakage.','SECRET_ISOLATION'),
 ('T08','DENIAL_OF_SERVICE','HIGH','A05','B03','Unbounded candidate resource usage','Enforce time, CPU, memory, process and output limits.','RESOURCE_LIMITS'),
 ('T09','INFORMATION_DISCLOSURE','HIGH','A04','B04','Credentials forwarded or exposed','Use trusted endpoint allowlists and prevent credential forwarding and disclosure.','SAST_EGRESS'),
 ('T10','TAMPERING','HIGH','A06','B05','Compromised or vulnerable build inputs','Inventory dependencies and images and evaluate vulnerability evidence against policy.','DEPENDENCY_SCAN'),
 ('T11','INFORMATION_DISCLOSURE','HIGH','A02','B01','Untrusted candidate content reaches browser','Render untrusted content as data and verify CSP and injection resistance.','SAST_DAST_INJECTION'),
 ('T12','INFORMATION_DISCLOSURE','HIGH','A04','B06','Transport leaks session or credentials','Verify canonical TLS configuration, proxy trust and secure cookies.','TRANSPORT_TEST'),
 ('T13','TAMPERING','CRITICAL','A03','B03','Candidate forges observation protocol','Verify observation integrity against adversarial candidate behavior.','OBSERVATION_INTEGRITY'),
 ('T14','ELEVATION_OF_PRIVILEGE','CRITICAL','A07','B05','Unapproved merge, dispatch or release','Require explicit authorization and all applicable quality and security gates.','RELEASE_GATE_TEST'),
 ('T15','INFORMATION_DISCLOSURE','CRITICAL','A04','B05','Secrets persist in source or artifact history','Scan exact candidate files and applicable history and artifacts without exposing values.','SECRET_SCAN'),
 ('T16','DENIAL_OF_SERVICE','HIGH','A05','B04','Provider requests exhaust budget or workers','Enforce existing inference, queue, time and budget controls.','RESOURCE_BUDGET_TEST'),
)
def catalog():
    assets=[dict(id=k,description=v) for k,v in ASSETS]
    boundaries=[dict(id=k,description=v,assets=list(a)) for k,v,a in BOUNDARIES]
    threats=[]; requirements=[]
    for tid,stride,severity,asset,boundary,description,req,method in ROWS:
        rid='SR'+tid[1:]
        threats.append(dict(id=tid,stride=stride,severity=severity,asset=asset,boundary=boundary,
                            description=description,requirement_id=rid,risk_status='UNASSESSED'))
        requirements.append(dict(id=rid,threat_id=tid,requirement=req,verification=method,
                                 mandatory=True,verification_status='NOT_VERIFIED'))
    out=dict(version='orbit-architecture-baseline-v1',assets=assets,boundaries=boundaries,threats=threats,requirements=requirements)
    validate_catalog(out)
    return out
def validate_catalog(c):
    def unique(items):
        ids=[x['id'] for x in items]
        if not ids or len(ids)!=len(set(ids)):raise ValueError('Duplicate or empty inventory')
        return set(ids)
    assets=unique(c['assets']);boundaries=unique(c['boundaries']);threats=unique(c['threats']);reqs=unique(c['requirements'])
    by_boundary={x['id']:set(x['assets']) for x in c['boundaries']}
    by_req={x['id']:x for x in c['requirements']}
    if (set(x['stride'] for x in c['threats'])!=set(STRIDE) or
        {x['asset'] for x in c['threats']}!=assets or {x['boundary'] for x in c['threats']}!=boundaries or
        any(not x or not x<=assets for x in by_boundary.values()) or len(threats)!=len(reqs)):
        raise ValueError('Incomplete architecture inventory')
    for t in c['threats']:
        r=by_req[t['requirement_id']]
        if (t['asset'] not in by_boundary[t['boundary']] or t['severity'] not in ('CRITICAL','HIGH','MEDIUM','LOW')
            or t['risk_status']!='UNASSESSED' or r['threat_id']!=t['id'] or r['mandatory'] is not True
            or r['verification_status']!='NOT_VERIFIED' or not r['requirement'] or not r['verification']):
            raise ValueError('Invalid requirement traceability')
    if {x['requirement_id'] for x in c['threats']}!=reqs:raise ValueError('Orphan requirement')
def evaluate(pid,jid,evidence):
    out=dict(schema='orbit.security-threat-model.v1',project_id=pid,job_id=jid,state='BLOCK',
        scope='architecture_baseline_only',security_gate='BLOCK',source=None,catalog_digest=None,
        assets=[],boundaries=[],threats=[],requirements=[],candidate_analysis='NOT_ASSESSED',**FLAGS)
    try:
        c=catalog();out.update({k:c[k] for k in ('assets','boundaries','threats','requirements')})
        out['catalog_digest']=pp.digest(c)
        if (evidence['schema']!='orbit.security-evidence.v1' or (evidence['project_id'],evidence['job_id'])!=(pid,jid)
            or evidence['evidence_digest']!=pp.digest({k:v for k,v in evidence.items() if k!='evidence_digest'})
            or evidence['security_gate']!='BLOCK' or any(evidence.get(k) is not False for k in security.FLAGS)
            or evidence['assessments']!=dict.fromkeys(security.ASSESSMENTS,'NOT_ASSESSED')
            or set(evidence['checks'])!=set(security.CHECKS)):
            raise ValueError('Invalid security evidence')
        src=evidence['source']
        if not src:raise ValueError('Current source missing')
        keys=(*security.DIGESTS,'execution_digest','report_digest','regression_digest','retest_digest')
        if not all(security.registry.hex_digest(src[k]) for k in keys) or not security.registry.hex_digest(evidence['policy_digest']):
            raise ValueError('Incomplete source binding')
        if src['selected'] not in ('A','B') or any(type(src[k]) is not int or src[k]<1 for k in ('plan_version','execution_version')):
            raise ValueError('Invalid source versions')
        out['source']=dict(**{k:src[k] for k in keys},selected=src['selected'],
            plan_version=src['plan_version'],execution_version=src['execution_version'],
            security_evidence_digest=evidence['evidence_digest'],policy_digest=evidence['policy_digest'])
        if evidence['state']=='SECURITY_EVIDENCE_READY' and all(x=='PASS' for x in evidence['checks'].values()):
            out['state']='THREAT_MODEL_READY'
    except security.ERRORS:
        pass
    out['evidence_digest']=pp.digest(out)
    return out
def view(c,db,pid,jid):
    if not c.in_transaction:raise ValueError('Consistent transaction required')
    return evaluate(pid,jid,security.view(c,db,pid,jid))
