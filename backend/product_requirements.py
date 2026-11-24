"""P6.1a: immutable human-authored requirements revisions and explicit approval."""
import hashlib
import json
import re

def ensure_schema(c):
    c.execute("""CREATE TABLE IF NOT EXISTS product_requirements(
        project_id TEXT NOT NULL REFERENCES projects(id), version INTEGER NOT NULL,
        document TEXT NOT NULL, digest TEXT NOT NULL, author TEXT NOT NULL,
        created_at TEXT NOT NULL, approved_by TEXT, approved_at TEXT,
        PRIMARY KEY(project_id,version))""")

def string(value, limit=2000):
    if not isinstance(value,str) or not value.strip() or len(value)>limit:
        raise ValueError('Required nonempty text or text limit exceeded')
    return value.strip()

def strings(value, minimum=0, maximum=30):
    if not isinstance(value,list) or not minimum<=len(value)<=maximum:
        raise ValueError('Invalid text list')
    return [string(x) for x in value]

def fields(value, keys):
    if not isinstance(value,dict) or set(value)!=set(keys):
        raise ValueError('Unexpected or missing document fields')

def validate(document):
    fields(document,('problem','goals','users','scope','out_of_scope','assumptions','open_questions','requirements','stories'))
    out={'problem':string(document['problem'])}
    for name in ('goals','users','scope','out_of_scope','assumptions','open_questions'):
        out[name]=strings(document[name],minimum=int(name in ('goals','users','scope')))
    reqs=document['requirements']
    if not isinstance(reqs,list) or not 1<=len(reqs)<=50:
        raise ValueError('Expected 1–50 requirements')
    seen=set()
    kinds=set()
    out['requirements']=[]
    for r in reqs:
        fields(r,('id','kind','description','priority','acceptance'))
        rid=r['id']
        if not isinstance(rid,str) or not re.fullmatch(r'REQ-[0-9]{1,4}',rid) or rid in seen:
            raise ValueError('Invalid or duplicate requirement ID')
        if r['kind'] not in ('functional','nonfunctional') or r['priority'] not in ('must','should','could'):
            raise ValueError('Invalid requirement kind or priority')
        seen.add(rid);kinds.add(r['kind'])
        out['requirements'].append(dict(id=rid,kind=r['kind'],description=string(r['description']),
            priority=r['priority'],acceptance=strings(r['acceptance'],1,10)))
    if kinds!={'functional','nonfunctional'}:raise ValueError('Both functional and nonfunctional requirements required')
    stories=document['stories']
    if not isinstance(stories,list) or not 1<=len(stories)<=50:
        raise ValueError('Expected 1–50 user stories')
    story_ids=set();covered=set();out['stories']=[]
    for s in stories:
        fields(s,('id','actor','goal','benefit','requirements'))
        sid=s['id']
        if not isinstance(sid,str) or not re.fullmatch(r'US-[0-9]{1,4}',sid) or sid in story_ids:
            raise ValueError('Invalid or duplicate story ID')
        refs=strings(s['requirements'],1,50)
        if len(set(refs))!=len(refs) or not set(refs)<=seen:raise ValueError('Unknown or duplicate requirement reference')
        story_ids.add(sid);covered.update(refs)
        out['stories'].append(dict(id=sid,actor=string(s['actor']),goal=string(s['goal']),
            benefit=string(s['benefit']),requirements=refs))
    if covered!=seen:raise ValueError('Each requirement must be linked to a story')
    if len(canonical(out).encode('utf-8'))>60000:raise ValueError('Document exceeds 60 KB')
    return out

def canonical(doc):
    return json.dumps(doc,ensure_ascii=False,sort_keys=True,separators=(',',':'))

def latest(c,pid):
    return c.execute('SELECT * FROM product_requirements WHERE project_id=? ORDER BY version DESC LIMIT 1',(pid,)).fetchone()

def view(c,pid):
    row=latest(c,pid)
    current=dict(row) if row else None
    if current:
        current['document']=json.loads(current['document'])
        current['source']='human'
    history=[dict(r) for r in c.execute('''SELECT version,digest,author,created_at,approved_by,approved_at
        FROM product_requirements WHERE project_id=? ORDER BY version DESC LIMIT 100''',(pid,))]
    return {'project_id':pid,'current':current,'history':history,
            'planning_ready':bool(current and current['approved_at'])}

def save(c,pid,actor,body,now):
    fields(body,('expected_version','document'))
    expected=body['expected_version']
    if type(expected) is not int or expected<0:raise ValueError('Invalid expected version')
    document=canonical(validate(body['document']))
    row=latest(c,pid)
    version=row['version'] if row else 0
    if expected!=version:raise ValueError('Stale version; reload before saving')
    digest=hashlib.sha256(document.encode('utf-8')).hexdigest()
    c.execute('INSERT INTO product_requirements(project_id,version,document,digest,author,created_at) VALUES(?,?,?,?,?,?)',
        (pid,version+1,document,digest,actor,now))
    return view(c,pid)

def approve(c,pid,actor,body,now):
    fields(body,('version','digest','confirmation'))
    row=latest(c,pid)
    if not row or type(body['version']) is not int or body['version']!=row['version'] or body['digest']!=row['digest']:
        raise ValueError('Current revision and digest required')
    if body['confirmation']!='APPROVE PRODUCT REQUIREMENTS':raise ValueError('Explicit approval required')
    if row['approved_at']:raise ValueError('Revision already approved')
    if json.loads(row['document'])['open_questions']:raise ValueError('Resolve open questions in a new revision before approval')
    c.execute('UPDATE product_requirements SET approved_by=?,approved_at=? WHERE project_id=? AND version=?',
        (actor,now,pid,row['version']))
    return view(c,pid)
