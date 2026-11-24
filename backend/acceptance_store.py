"""Persist local owner/reviewer Web evidence. References are human assertions."""
import json
import web_acceptance as wa

def ensure_schema(c):
    c.execute('CREATE TABLE IF NOT EXISTS web_acceptance_register(project_id TEXT PRIMARY KEY,register_json TEXT NOT NULL)')
def load(c,pid):
    ensure_schema(c)
    row=c.execute('SELECT register_json FROM web_acceptance_register WHERE project_id=?',(pid,)).fetchone()
    return json.loads(row[0]) if row else wa.new_register(pid)
def save(c,register):
    wa.evaluate(register)
    c.execute('INSERT INTO web_acceptance_register(project_id,register_json) VALUES(?,?) ON CONFLICT(project_id) DO UPDATE SET register_json=excluded.register_json',(register['project_id'],wa.canonical(register)))
def view(c,pid):
    reg=load(c,pid)
    return {'register':reg,'state':wa.evaluate(reg),'requirements':list(wa.REQUIREMENTS)}
def record(c,pid,actor,body):
    reg=wa.record(load(c,pid),body.get('requirement'),reference=body.get('reference'),reviewer=actor,passed=body.get('passed'))
    save(c,reg)
    return view(c,pid)
def accept(c,pid,actor,confirmation):
    reg=wa.signoff(load(c,pid),owner=actor,confirmation=confirmation)
    save(c,reg)
    return view(c,pid)
