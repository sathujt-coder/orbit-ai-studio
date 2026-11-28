"""Read-only deterministic defect findings from current trusted execution receipts."""
import sqlite3
import engineering_assertion_registry as registry
import acceptance_runner as runner
import project_planning as pp
import regression_quality_gate as regression

FLAGS = registry.FLAGS

def evaluate(pid, jid, state, source, cases, targets, gate):
    out = dict(schema='orbit.automated-defect-detection.v1', project_id=pid,
               job_id=jid, state='BLOCK', findings=[], receipt_digest=None,
               regression_digest=None, reason='INVALID_OR_STALE_EVIDENCE', **FLAGS)
    try:
        if (source['project_id'], source['job_id']) != (pid, jid):
            raise ValueError('Wrong scope')
        if (state['project_id'], state['job_id']) != (pid, jid):
            raise ValueError('Wrong registry scope')
        if any(state.get(k) is not False for k in FLAGS):
            raise ValueError('Unexpected authorization')
        chain = state['history']
        receipt = state['current_receipt']
        if not chain or receipt != chain[-1] or state['latest_version'] != len(chain):
            raise ValueError('Current receipt required')
        s = receipt['snapshot']
        if (s['schema'] != 'orbit.assertion-run-receipt.v1'
                or (s['project_id'], s['job_id']) != (pid, jid)
                or type(s['version']) is not int or s['version'] != len(chain)
                or receipt['digest'] != pp.digest(s)
                or s['report_digest'] != pp.digest(s['report'])
                or any(s.get(k) is not False for k in FLAGS)):
            raise ValueError('Receipt binding mismatch')
        if targets is None:
            raise ValueError('Exact targets required')
        summary = registry.validate_report(s['report'], source, cases, targets)
        expected = 'EXECUTION_RECORDED_' + summary['gate']
        if summary != s['summary'] or state['state'] != expected:
            raise ValueError('False execution verdict')
        if ((gate['project_id'], gate['job_id']) != (pid, jid)
                or not regression.mapping.digest_ok(gate)
                or any(gate.get(k) is not False for k in FLAGS)
                or gate.get('full_regression_required') is not True
                or gate.get('selective_execution_authorized') is not False
                or gate['checks']['durable_priority_receipt'] != 'PASS'
                or gate['receipts']['execution'] != receipt['digest']
                or gate['receipts']['report'] != s['report_digest']):
            raise ValueError('Current regression receipt required')
        findings = []
        kinds = {'FAIL':'ASSERTION_MISMATCH', 'ERROR':'EXECUTION_ERROR',
                 'NOT_EXECUTED':'MISSING_EXECUTION'}
        for row in s['report']['results']:
            if row['status'] == 'PASS':
                continue
            kind = kinds[row['status']]
            identity = dict(project_id=pid, job_id=jid, case_id=row['case_id'],
                            assertion_digest=row['assertion_digest'], kind=kind)
            findings.append(dict(finding_id=pp.digest(identity), **identity,
                                 reason=row['reason'], module_sha256=row['module_sha256'],
                                 receipt_digest=receipt['digest']))
        out.update(state='DETECTED' if findings else 'NO_FINDINGS',
                   findings=findings, receipt_digest=receipt['digest'],
                   regression_digest=gate['evidence_digest'], reason=None)
    except (ValueError, KeyError, TypeError, AttributeError, IndexError, PermissionError,
            sqlite3.Error, OSError, SyntaxError, RecursionError):
        pass
    out['evidence_digest'] = pp.digest(out)
    return out

def view(c, db, pid, jid):
    """Caller must provide a consistent transaction and authorized project access."""
    if not c.in_transaction:
        raise ValueError('Consistent transaction required')
    try:
        state = registry.view(c, db, pid, jid)
        source, cases, _, targets = runner.current(c, db, pid, jid)
        gate = regression.view(c, db, pid, jid)
        return evaluate(pid, jid, state, source, cases, targets, gate)
    except (ValueError, KeyError, TypeError, AttributeError, IndexError, PermissionError,
            sqlite3.Error, OSError, SyntaxError, RecursionError):
        return evaluate(pid, jid, {}, {}, [], [], {})
