#!/usr/bin/env python3
"""AI Studio Company: dependency-free local orchestration API + 3D web UI."""
from __future__ import annotations
import json, os, re, sqlite3, threading, time, uuid, urllib.request, urllib.error, traceback, sys
from datetime import datetime, timezone
from pathlib import Path
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
sys.path.insert(0, str(Path(__file__).resolve().parent))
import github_bridge
import coding_factory
import verification_factory
import auth_store
import auth_http
import auth_policy

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / 'web'
DB_PATH = Path(os.environ.get('AI_COMPANY_DB', str(ROOT / 'company.sqlite')))
HOST = os.environ.get('AI_HOST', '127.0.0.1')
PORT = int(os.environ.get('AI_PORT', '8787'))
PROVIDER = os.environ.get('AI_PROVIDER', 'demo').strip().lower()
BASE_URL = os.environ.get('AI_BASE_URL', 'http://127.0.0.1:11434/v1').rstrip('/')
API_KEY = os.environ.get('AI_API_KEY', '')
MODEL_A = os.environ.get('AI_MODEL_A', os.environ.get('AI_MODEL', 'qwen3:8b'))
MODEL_B = os.environ.get('AI_MODEL_B', MODEL_A)
REQUEST_TIMEOUT = int(os.environ.get('AI_TIMEOUT', '150'))
LOCK = threading.RLock()
RUNNING: dict[str, dict] = {}

STAGES = [
    dict(id='po', name='Product Owner', short='PO', team='Sản phẩm', deliverable='Product vision & roadmap', description='Định hình vấn đề, mục tiêu, KPI và phạm vi MVP', icon='◎', color='#54d6fa', approval=False),
    dict(id='research', name='Research', short='RSH', team='Nghiên cứu', deliverable='Market & competitor research', description='Khảo sát thị trường, người dùng và đối thủ', icon='◈', color='#a98cff', approval=False),
    dict(id='ba', name='Business Analyst', short='BA', team='Phân tích', deliverable='User stories & acceptance criteria', description='Use case, chức năng, luồng nghiệp vụ, tiêu chí chấp nhận', icon='▤', color='#71c8ff', approval=False),
    dict(id='pm', name='Project Manager', short='PM', team='Điều phối', deliverable='Delivery plan & risk register', description='Milestone, nguồn lực, phụ thuộc, ngân sách, rủi ro', icon='◷', color='#ffb96c', approval=False),
    dict(id='design', name='UX / UI Design', short='UX', team='Thiết kế', deliverable='UX flows & design specification', description='User journey, wireframe, design system, accessibility', icon='◇', color='#f39be8', approval=False),
    dict(id='techlead', name='Tech Lead', short='TL', team='Kiến trúc', deliverable='Architecture & ADR', description='Kiến trúc hệ thống, công nghệ, API, dữ liệu', icon='⌘', color='#75edcf', approval=False),
    dict(id='dev', name='Development', short='DEV', team='Kỹ thuật', deliverable='Implementation plan & code specification', description='Phương án triển khai, thiết kế module, mã mẫu', icon='⌨', color='#65b8ff', approval=False),
    dict(id='qa', name='Quality Assurance', short='QA', team='Quy trình chất lượng', deliverable='Test strategy & quality process', description='Chiến lược kiểm thử, tiêu chuẩn chất lượng', icon='✓', color='#e1d27d', approval=False),
    dict(id='qc', name='Quality Control', short='QC', team='Kiểm thử', deliverable='Test cases & defect report', description='Kịch bản test, kiểm soát lỗi, đánh giá release', icon='⊞', color='#faac88', approval=False),
    dict(id='security', name='Security', short='SEC', team='An toàn', deliverable='Threat model & security review', description='Threat model, phân quyền, dữ liệu, đánh giá rủi ro', icon='⬡', color='#fd8797', approval=True),
    dict(id='devops', name='DevOps / Release', short='OPS', team='Phát hành', deliverable='Web CI/CD & deployment checklist', description='Build, CI/CD, giám sát, hồ sơ phát hành', icon='↗', color='#83ddb9', approval=True),
    dict(id='marketing', name='Growth Marketing', short='MKT', team='Tăng trưởng', deliverable='Web launch & growth playbook', description='SEO, onboarding, chiến dịch, kênh thu hút và đo retention', icon='✦', color='#ecb7ff', approval=True),
]
STAGE_IDS = [s['id'] for s in STAGES]
STAGE_BY_ID = {s['id']: s for s in STAGES}
AGENTS = [dict(id=f'{s["id"]}-{k}', dept=s['id'], name=f'{s["short"]}-{k}', title=('Agent sáng tạo' if k == 'A' else 'Agent phản biện'), lane=k, model=MODEL_A if k == 'A' else MODEL_B) for s in STAGES for k in ('A', 'B')]


def now(): return datetime.now(timezone.utc).isoformat(timespec='seconds')
def uid(): return uuid.uuid4().hex[:12]
class ManagedConnection:
    """Auto-commit or rollback, then close after each request/thread operation."""
    def __init__(self):
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(DB_PATH, timeout=20, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute('PRAGMA foreign_keys=ON')
        self.conn.execute('PRAGMA journal_mode=WAL')
    def __getattr__(self, attr): return getattr(self.conn,attr)
    def __enter__(self): return self.conn
    def __exit__(self, exc_type, exc_val, tb):
        try:
            if exc_type: self.conn.rollback()
            else: self.conn.commit()
        finally: self.conn.close()

def db(): return ManagedConnection()


def init_db():
    with LOCK, db() as c:
        auth_store.ensure_schema(c)
        c.executescript('''
        CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY,name TEXT NOT NULL,idea TEXT NOT NULL,platform TEXT NOT NULL,created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY,project_id TEXT NOT NULL,stage_id TEXT NOT NULL,position INTEGER NOT NULL,status TEXT NOT NULL DEFAULT 'queued',started_at TEXT,finished_at TEXT,approved_at TEXT,FOREIGN KEY(project_id) REFERENCES projects(id));
        CREATE TABLE IF NOT EXISTS artifacts(id TEXT PRIMARY KEY,project_id TEXT NOT NULL,stage_id TEXT NOT NULL,agent_id TEXT NOT NULL,kind TEXT NOT NULL,content TEXT NOT NULL,created_at TEXT NOT NULL,run_id TEXT NOT NULL DEFAULT '');
        CREATE TABLE IF NOT EXISTS reviews(id TEXT PRIMARY KEY,project_id TEXT NOT NULL,stage_id TEXT NOT NULL,reviewer_id TEXT NOT NULL,author_id TEXT NOT NULL,verdict TEXT NOT NULL,score INTEGER NOT NULL,feedback TEXT NOT NULL,created_at TEXT NOT NULL,run_id TEXT NOT NULL DEFAULT '');
        CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY,project_id TEXT,stage_id TEXT,agent_id TEXT,level TEXT NOT NULL,message TEXT NOT NULL,created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS chat(id TEXT PRIMARY KEY,project_id TEXT NOT NULL,agent_id TEXT NOT NULL,role TEXT NOT NULL,content TEXT NOT NULL,created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS coding_jobs(id TEXT PRIMARY KEY, project_id TEXT NOT NULL, spec TEXT NOT NULL, status TEXT NOT NULL, proposal_a TEXT, proposal_b TEXT, review_a TEXT, review_b TEXT, manifest TEXT, error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS idx_coding_jobs_project ON coding_jobs(project_id,status);
        CREATE TABLE IF NOT EXISTS coding_verifications(id TEXT PRIMARY KEY,job_id TEXT NOT NULL,project_id TEXT NOT NULL,verdict TEXT NOT NULL,report_json TEXT NOT NULL,created_at TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS idx_coding_verifications_job ON coding_verifications(job_id,created_at);
        CREATE TABLE IF NOT EXISTS github_exports(artifact_id TEXT PRIMARY KEY, project_id TEXT NOT NULL, repo TEXT NOT NULL, status TEXT NOT NULL, pr_url TEXT,pr_number INTEGER, branch TEXT,error TEXT, updated_at TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS idx_task_project ON tasks(project_id,position);
        CREATE INDEX IF NOT EXISTS idx_event_project ON events(project_id,created_at);
        ''')
        # Schema migration for databases created by ORBIT 0.1/0.2. Preserve history.
        for table in ('artifacts','reviews'):
            columns={row['name'] for row in c.execute(f'PRAGMA table_info({table})')}
            if 'run_id' not in columns:
                c.execute(f"ALTER TABLE {table} ADD COLUMN run_id TEXT NOT NULL DEFAULT ''")
        if c.execute('SELECT count(*) AS n FROM projects').fetchone()['n'] == 0:
            create_project('KnowledgeNest · AI Knowledge Vault', 'Ứng dụng Web lưu link/video/bài viết từ internet và mạng xã hội, tự động phân loại bằng AI, có tìm kiếm, đánh dấu và xem lại; Mobile chỉ sau nghiệm thu Web.', 'Web app', c=c)


def create_project(name, idea, platform, c=None):
    owns = c is None
    if owns: c = db()
    try:
        pid = uid()
        c.execute('INSERT INTO projects VALUES(?,?,?,?,?)', (pid, name[:100], idea[:10000], platform[:100], now()))
        for n, s in enumerate(STAGES):
            c.execute('INSERT INTO tasks(id,project_id,stage_id,position,status) VALUES(?,?,?,?,?)', (uid(),pid,s['id'],n,'queued'))
        log(c,pid,None,None,'info',f'Dự án “{name[:80]}” đã được khởi tạo với 12 phòng ban / 24 agent.')
        if owns: c.commit()
        return pid
    finally:
        if owns: c.close()


def log(c,pid,sid,aid,level,message):
    c.execute('INSERT INTO events VALUES(?,?,?,?,?,?,?)',(uid(),pid,sid,aid,level,message[:1500],now()))


def rows(c,query,params=()): return [dict(r) for r in c.execute(query,params).fetchall()]


def project_state(pid):
    with LOCK, db() as c:
        p=c.execute('SELECT * FROM projects WHERE id=?',(pid,)).fetchone()
        if not p: raise ValueError('Không tìm thấy dự án')
        tasks=rows(c,'SELECT * FROM tasks WHERE project_id=? ORDER BY position',(pid,))
        artifacts=rows(c,'SELECT id,stage_id,agent_id,kind,created_at,substr(content,1,230) AS preview FROM artifacts WHERE project_id=? ORDER BY rowid DESC LIMIT 100',(pid,))
        reviews=rows(c,'SELECT * FROM reviews WHERE project_id=? ORDER BY rowid DESC LIMIT 100',(pid,))
        events=rows(c,'SELECT * FROM events WHERE project_id=? ORDER BY rowid DESC LIMIT 70',(pid,))
        for t in tasks:
            s=STAGE_BY_ID[t['stage_id']]
            t.update({k:s[k] for k in ('name','short','team','deliverable','description','icon','color','approval')})
            t['artifact_count']=sum(1 for a in artifacts if a['stage_id']==t['stage_id'])
            t['review_count']=sum(1 for r in reviews if r['stage_id']==t['stage_id'])
        done=sum(t['status'] in ('done','approved') for t in tasks)
        working=next((t for t in tasks if t['status'] in ('drafting','reviewing','synthesizing','awaiting_approval','needs_revision')),None)
        return dict(project=dict(p),tasks=tasks,artifacts=artifacts,reviews=reviews,events=events,
                    stats=dict(done=done,total=len(tasks),percent=round(done/len(tasks)*100),artifacts=len(artifacts),reviews=len(reviews),active=working['stage_id'] if working else None),running=RUNNING.get(pid,{}).get('running',False),pause_requested=RUNNING.get(pid,{}).get('pause',False))


def list_projects():
    with LOCK, db() as c: return rows(c,'SELECT * FROM projects ORDER BY created_at DESC,rowid DESC')


def set_status(pid,sid,status,message=None,aid=None,level='info'):
    with LOCK,db() as c:
        fields={'status':status}
        if status=='drafting': fields['started_at']=now()
        if status in ('done','awaiting_approval','needs_revision'): fields['finished_at']=now()
        c.execute('UPDATE tasks SET '+','.join(f'{k}=?' for k in fields)+' WHERE project_id=? AND stage_id=?',(*fields.values(),pid,sid))
        if message: log(c,pid,sid,aid,level,message)


def save_artifact(pid,sid,aid,kind,content,run_id=""):
    with LOCK,db() as c:
        c.execute('INSERT INTO artifacts(id,project_id,stage_id,agent_id,kind,content,created_at,run_id) VALUES(?,?,?,?,?,?,?,?)',(uid(),pid,sid,aid,kind,content,now(),run_id))


def save_review(pid,sid,reviewer,author,verdict,score,feedback,run_id=""):
    with LOCK,db() as c:
        c.execute('INSERT INTO reviews(id,project_id,stage_id,reviewer_id,author_id,verdict,score,feedback,created_at,run_id) VALUES(?,?,?,?,?,?,?,?,?,?)',(uid(),pid,sid,reviewer,author,verdict,score,feedback,now(),run_id))


def get_preceding(pid, stage_id):
    ix=STAGE_IDS.index(stage_id)
    if ix == 0: return ''
    with LOCK,db() as c:
        result=rows(c,'SELECT stage_id,content FROM artifacts WHERE project_id=? AND kind=? ORDER BY rowid DESC',(pid,'final'))
    indexed={r['stage_id']:r['content'] for r in result}
    return '\n\n'.join('['+s+'] '+indexed[s][:1200] for s in STAGE_IDS[:ix] if s in indexed)[-7500:]


def clean_model_text(text):
    if not isinstance(text,str): return str(text)
    return re.sub(r'<think>[\s\S]*?</think>','',text,flags=re.I).strip()[:22000]


def model_call(system,user,lane='A'):
    if PROVIDER == 'demo':
        raise RuntimeError('Internal: demo responses generated separately')
    if PROVIDER not in ('ollama','openai-compatible'):
        raise ValueError('AI_PROVIDER phải là demo, ollama hoặc openai-compatible')
    model=MODEL_A if lane=='A' else MODEL_B
    payload=json.dumps({'model':model,'messages':[{'role':'system','content':system},{'role':'user','content':user}], 'temperature':0.45, 'stream':False},ensure_ascii=False).encode()
    headers={'Content-Type':'application/json'}
    if API_KEY: headers['Authorization']='Bearer '+API_KEY
    req=urllib.request.Request(BASE_URL+'/chat/completions',data=payload,headers=headers,method='POST')
    try:
        with urllib.request.urlopen(req,timeout=REQUEST_TIMEOUT) as r: data=json.loads(r.read(4_000_000).decode())
        return clean_model_text(data['choices'][0]['message']['content'])
    except (urllib.error.URLError,KeyError,ValueError) as ex:
        raise RuntimeError(f'AI endpoint {BASE_URL}: {ex}') from ex


DEMO_CONTENT = {
 'po': ('Vấn đề & cơ hội', 'Chân dung người dùng, JTBD, North Star Metric, phạm vi MVP, KPI 30/60/90 ngày'),
 'research': ('Bản đồ thị trường', 'Phân khúc, 5 giả thuyết cần kiểm chứng, ma trận đối thủ, phỏng vấn 10 người dùng'),
 'ba': ('Đặc tả nghiệp vụ', 'User stories theo mức ưu tiên, acceptance criteria dạng Given/When/Then, dữ liệu và ngoại lệ'),
 'pm': ('Kế hoạch delivery', 'Lộ trình 6 sprint, ma trận RACI, risk register, Definition of Done, checkpoint'),
 'design': ('Hệ thống trải nghiệm', 'Sitemap, user flow, trạng thái loading/empty/error, wireframe, accessibility WCAG'),
 'techlead': ('Architecture Decision Records', 'Sơ đồ thành phần, API contract, auth, data model, logging, ADR và trade-off'),
 'dev': ('Kế hoạch phát triển', 'Chia module, luồng pull request, hướng dẫn chạy local, review checklist, unit test mục tiêu'),
 'qa': ('Chiến lược QA', 'Quality gates, test pyramid, regression, performance, accessibility, traceability'),
 'qc': ('Kịch bản QC', 'Test cases positive/negative, bug triage P0–P3, exit criteria, release sign-off'),
 'security': ('Đánh giá bảo mật', 'Asset inventory, STRIDE, OWASP Top 10, secrets, authz, data retention, remediation'),
 'devops': ('Bản kế hoạch phát hành', 'GitHub Actions pipeline, artifact signing, môi trường staging, Play Console, App Store Connect'),
 'marketing': ('Growth & ASO', 'Thông điệp định vị, onboarding, kênh organic, 4 tuần launch, retention/cohort KPI'),
}


def demo_draft(project, sid, lane):
    title, items=DEMO_CONTENT[sid]
    angle='Ưu tiên tác động tới người dùng và mục tiêu kinh doanh' if lane=='A' else 'Ưu tiên khả năng thực thi, rủi ro và kiểm chứng độc lập'
    return (f'# {title} — Phương án {lane}\n\n**Dự án:** {project["name"]}\n**Ý tưởng:** {project["idea"]}\n'
      f'**Góc nhìn:** {angle}.\n\n## Nội dung đề xuất\n{items}.\n\n'
      f'## Đề xuất cụ thể\n1. Xác định 3 nhu cầu quan trọng nhất của người dùng và chỉ số kiểm chứng.\n'
      f'2. Thiết kế deliverable đo được cho giai đoạn {sid.upper()}; lập danh sách rủi ro, phụ thuộc.\n'
      f'3. Thêm checklist nghiệm thu và ít nhất một trường hợp thất bại/khôi phục.\n\n'
      f'## Câu hỏi cần xác minh\n- Giả thuyết lớn nhất nào chưa có bằng chứng?\n- Ai là người có quyền phê duyệt release?\n\n'
      '**Lưu ý:** Bản demo mô phỏng quy trình, không phải nghiên cứu thực tế hay mã đã triển khai.')


def review_prompt(sid, author, reviewer, draft):
    return (f'Bạn là reviewer độc lập {reviewer} của phòng {STAGE_BY_ID[sid]["name"]}. '
       'Đọc bản nháp của đồng nghiệp và tìm sai sót, thiếu bằng chứng, rủi ro và điểm không khả thi. '
       'Không mặc định đồng ý. Trả lời đúng cấu trúc JSON với verdict = APPROVE hoặc REQUEST_CHANGES, '
       'score là số từ 0 đến 100, feedback là mô tả ngắn, cụ thể và có hành động khắc phục.\n'
       f'Tác giả: {author}\nBản nháp:\n{draft[:12500]}')


def parse_review(raw):
    try:
        match=re.search(r'\{[\s\S]*\}',raw)
        obj=json.loads(match.group(0) if match else raw)
        verdict=str(obj.get('verdict','REQUEST_CHANGES')).upper()
        if verdict not in ('APPROVE','REQUEST_CHANGES'): verdict='REQUEST_CHANGES'
        return verdict,max(0,min(100,int(obj.get('score',0)))),str(obj.get('feedback','Không có nhận xét.'))[:1800]
    except (ValueError,TypeError):
        return 'REQUEST_CHANGES',0,'Không phân tích được JSON review; yêu cầu làm lại. Raw: '+raw[:500]


def run_stage(pid, sid):
    run_id=uid()
    with LOCK,db() as c:
        project=dict(c.execute('SELECT * FROM projects WHERE id=?',(pid,)).fetchone())
    s=STAGE_BY_ID[sid]
    set_status(pid,sid,'drafting',f'{s["name"]}: A và B bắt đầu nghiên cứu độc lập.')
    context=get_preceding(pid,sid)
    drafts={}
    for lane in ('A','B'):
        aid=f'{sid}-{lane}'
        if PROVIDER=='demo':
            time.sleep(.32)
            draft=demo_draft(project,sid,lane)
        else:
            system=(f'Bạn là chuyên gia {s["name"]} trong công ty AI phát triển phần mềm. '
              'Hãy làm việc độc lập, không giả định đồng nghiệp đã làm đúng. Trả lời tiếng Việt dưới dạng Markdown, '
              'có mục tiêu, deliverables, rủi ro, tiêu chí nghiệm thu và các giả định cần kiểm chứng. '
              'Không bịa dữ liệu nghiên cứu thị trường, kết quả test, bằng chứng hay triển khai thực tế.')
            user=(f'Dự án: {project["name"]}\nÝ tưởng: {project["idea"]}\nPlatform: {project["platform"]}\n'
               f'Giai đoạn: {s["name"]}\nDeliverable: {s["deliverable"]}\n'
               f'Vai trò agent: {lane}. ' + ('Thiên về tạo giải pháp và xác định scope.' if lane=='A' else 'Đề xuất phương án khác độc lập, tập trung rủi ro, tính khả thi.')
               +f'\nBối cảnh các giai đoạn trước (chỉ để tham khảo):\n{context}')
            draft=model_call(system,user,lane)
        drafts[lane]=draft
        save_artifact(pid,sid,aid,'draft',draft,run_id)
        set_status(pid,sid,'drafting',f'{aid} hoàn thành bản đề xuất độc lập.',aid)
    set_status(pid,sid,'reviewing',f'{s["name"]}: hai agent review chéo, không tự chấm bài của mình.')
    votes=[]
    for reviewer,author in (('A','B'),('B','A')):
        if PROVIDER=='demo':
            time.sleep(.3)
            verdict,score,feedback='APPROVE',(89 if reviewer=='A' else 92),f'Đã rà soát phương án {author}: cần kiểm chứng giả định và thêm số liệu thực tế trước khi production.'
        else:
            raw=model_call('Bạn là chuyên gia audit chất lượng. Chỉ trả JSON hợp lệ; không dùng markdown code fence.',review_prompt(sid,author,reviewer,drafts[author]),reviewer)
            verdict,score,feedback=parse_review(raw)
        if verdict=='APPROVE' and score<80:
            verdict='REQUEST_CHANGES'
            feedback='Quality gate yêu cầu điểm review >= 80. '+feedback
        save_review(pid,sid,f'{sid}-{reviewer}',f'{sid}-{author}',verdict,score,feedback,run_id)
        set_status(pid,sid,'reviewing',f'{sid}-{reviewer} review {sid}-{author}: {verdict} · {score}/100',f'{sid}-{reviewer}','success' if verdict=='APPROVE' else 'warning')
        votes.append(verdict)
    if not all(v=='APPROVE' for v in votes):
        set_status(pid,sid,'needs_revision','Ít nhất một reviewer yêu cầu chỉnh sửa. Xem feedback và chạy lại giai đoạn.','', 'warning')
        return 'needs_revision'
    set_status(pid,sid,'synthesizing','Tổng hợp ý kiến của hai agent thành bản cuối đã review.')
    if PROVIDER=='demo':
        final=(f'# {s["deliverable"]} · Bản hợp nhất\n\n'
               f'> DEMO: ví dụ minh họa workflow, chưa phải deliverable được AI nghiên cứu/triển khai thật.\n\n'
               f'## Phương án A\n{drafts["A"][:3500]}\n\n## Góc nhìn độc lập B\n{drafts["B"][:2700]}\n\n'
               '## Kết luận review chéo\n- Hai agent đã review bản nháp của nhau.\n- Cần xác minh bằng chứng, chạy test thực, và phê duyệt trước khi xuất bản.\n')
    else:
        user=(f'Gộp hai phương án {s["name"]} thành một deliverable chất lượng để chuyển cho team sau. '
              'Giữ các quyết định có căn cứ, nêu rõ các điểm chưa xác minh, acceptance criteria và next steps. '
              'Không tuyên bố đã thực thi code, test hay phát hành nếu chưa thực hiện.\n\n'
              f'A:\n{drafts["A"][:9000]}\n\nB:\n{drafts["B"][:9000]}')
        final=model_call('Bạn tổng hợp deliverable đã được review chéo. Trả về Markdown rõ ràng.',user,'A')
    save_artifact(pid,sid,f'{sid}-A','final',final,run_id)
    if s['approval']:
        set_status(pid,sid,'awaiting_approval',f'{s["name"]} hoàn tất review; đang đợi chủ dự án phê duyệt.','','warning')
        return 'awaiting_approval'
    set_status(pid,sid,'done',f'{s["name"]} hoàn thành và chuyển tiếp giai đoạn.','','success')
    return 'done'


def pipeline_worker(pid, mode):
    try:
        while True:
            with LOCK,db() as c:
                tasks=rows(c,'SELECT stage_id,status FROM tasks WHERE project_id=? ORDER BY position',(pid,))
            if not tasks: break
            next_task=None
            for t in tasks:
                if t['status'] in ('done','approved'): continue
                if t['status']!='queued':
                    # Always require explicit action for blockers or gates.
                    next_task=None
                    break
                next_task=t
                break
            if not next_task or RUNNING.get(pid,{}).get('pause'): break
            result=run_stage(pid,next_task['stage_id'])
            if result!='done' or mode=='next': break
    except Exception as ex:
        traceback.print_exc()
        with LOCK,db() as c:
            active=c.execute("SELECT stage_id FROM tasks WHERE project_id=? AND status IN ('drafting','reviewing','synthesizing') ORDER BY position LIMIT 1",(pid,)).fetchone()
            if active:
                c.execute("UPDATE tasks SET status='needs_revision' WHERE project_id=? AND stage_id=?",(pid,active['stage_id']))
            log(c,pid,active['stage_id'] if active else None,None,'error','Lỗi agent: '+str(ex)[:500])
    finally:
        if pid in RUNNING: RUNNING[pid]['running']=False


def run_pipeline(pid, mode):
    if mode not in ('next','all'): raise ValueError('mode phải là next/all')
    with LOCK:
        if RUNNING.get(pid,{}).get('running'): raise ValueError('Dự án này đang chạy')
        with db() as c:
            if not c.execute('SELECT 1 FROM projects WHERE id=?',(pid,)).fetchone(): raise ValueError('Không tìm thấy dự án')
        RUNNING[pid]={'running':True,'pause':False,'mode':mode}
        threading.Thread(target=pipeline_worker,args=(pid,mode),daemon=True).start()


def approve_stage(pid,sid):
    with LOCK,db() as c:
        t=c.execute('SELECT status FROM tasks WHERE project_id=? AND stage_id=?',(pid,sid)).fetchone()
        if not t or t['status']!='awaiting_approval': raise ValueError('Giai đoạn chưa ở trạng thái chờ phê duyệt')
        c.execute("UPDATE tasks SET status='approved',approved_at=? WHERE project_id=? AND stage_id=?",(now(),pid,sid))
        log(c,pid,sid,None,'success',f'{STAGE_BY_ID[sid]["name"]}: chủ dự án đã phê duyệt bước kế hoạch.')


def retry_stage(pid,sid):
    with LOCK,db() as c:
        t=c.execute('SELECT status,position FROM tasks WHERE project_id=? AND stage_id=?',(pid,sid)).fetchone()
        if not t or t['status']!='needs_revision': raise ValueError('Chỉ chạy lại giai đoạn đang cần sửa')
        c.execute("UPDATE tasks SET status='queued',started_at=NULL,finished_at=NULL WHERE project_id=? AND stage_id=?",(pid,sid))
        log(c,pid,sid,None,'info',f'{STAGE_BY_ID[sid]["name"]} đã đưa vào hàng đợi để làm lại; lịch sử cũ được giữ nguyên.')


def agent_chat(pid,aid,message):
    sid=aid.rsplit('-',1)[0]
    if sid not in STAGE_BY_ID or aid not in [f'{sid}-A',f'{sid}-B']: raise ValueError('Agent không hợp lệ')
    if not message.strip(): raise ValueError('Nội dung trống')
    with LOCK,db() as c:
        p=c.execute('SELECT * FROM projects WHERE id=?',(pid,)).fetchone()
        if not p: raise ValueError('Không tìm thấy dự án')
        c.execute('INSERT INTO chat VALUES(?,?,?,?,?,?)',(uid(),pid,aid,'user',message[:2500],now()))
    if PROVIDER=='demo':
        reply=(f'[DEMO] Tôi là {aid}, phụ trách {STAGE_BY_ID[sid]["name"]}. '
               f'Với yêu cầu “{message[:110]}”, tôi đề xuất: (1) xác định đầu ra và tiêu chí chấp nhận; '
               '(2) tách giả định khỏi bằng chứng; (3) để agent còn lại review độc lập trước khi kết luận. '
               'Kết nối Ollama hoặc API để nhận tư vấn AI thực.')
    else:
        with LOCK,db() as c: p=dict(c.execute('SELECT * FROM projects WHERE id=?',(pid,)).fetchone())
        context=get_preceding(pid,sid)
        reply=model_call(f'Bạn là {aid}, {STAGE_BY_ID[sid]["name"]}, một agent của công ty AI. '
                         'Trả lời ngắn gọn, thực tế và bằng tiếng Việt. Nếu không chắc, nói rõ giả định.',
                         f'Dự án: {p["name"]}\nBối cảnh:\n{context[:4000]}\n\nYêu cầu từ người quản lý:\n{message[:2500]}',aid[-1])
    with LOCK,db() as c: c.execute('INSERT INTO chat VALUES(?,?,?,?,?,?)',(uid(),pid,aid,'assistant',reply,now()))
    return reply


class Handler(SimpleHTTPRequestHandler):
    def __init__(self,*args,**kwargs): super().__init__(*args,directory=str(WEB),**kwargs)
    def log_message(self,format,*args): pass
    def send_json(self,status,data,headers=None):
        if getattr(self,'command','')=='POST' and getattr(self,'auth_context',None):
            actor,pid,action=self.auth_context
            with LOCK,db() as c:
                c.execute('INSERT INTO auth_audit(actor,project_id,action,outcome,created_at) VALUES(?,?,?,?,?)',(actor,pid,'http:'+action,'success' if status<400 else 'failed',int(time.time())))
            self.auth_context=None
        raw=json.dumps(data,ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Content-Length',str(len(raw)))
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        for key,value in (headers or {}).items(): self.send_header(key,value)
        self.end_headers(); self.wfile.write(raw)
    def json_body(self):
        length=int(self.headers.get('Content-Length','0'))
        if length>30000: raise ValueError('Dữ liệu quá lớn')
        return json.loads(self.rfile.read(length) or '{}')
    def request_is_local(self):
        host = self.headers.get('Host','').split(':')[0].lower()
        if host not in ('localhost','127.0.0.1','[::1]'):
            return False
        origin = self.headers.get('Origin')
        if origin:
            allowed = {f'http://127.0.0.1:{PORT}', f'http://localhost:{PORT}'}
            if origin not in allowed:
                return False
        return True
    def send_zip(self, filename, data):
        self.send_response(200)
        self.send_header('Content-Type','application/zip')
        self.send_header('Content-Length',str(len(data)))
        self.send_header('Content-Disposition', 'attachment; filename="'+filename+'"')
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.end_headers(); self.wfile.write(data)
    def do_HEAD(self):
        # No API or protected HTML via inherited static HEAD handler.
        self.send_response(405);self.end_headers()
    def visible_projects(self):
        with LOCK,db() as c:return auth_policy.visible_projects(c,self.auth_context[0])
    def guard(self,method,path,body=None):
        with LOCK,db() as c:
            status,context=auth_policy.check(c,method,path,urlparse(self.path).query,body,self.headers,PORT)
        if status!=200:
            self.send_json(status,{'error':{401:'Authentication required',403:'Access denied',404:'Endpoint không tồn tại'}[status]});return False
        self.auth_context=context
        return True
    def do_GET(self):
        if not self.request_is_local():
            self.send_json(403, {'error':'Local host/origin required'}); return
        path=urlparse(self.path).path
        try:
            if path=='/api/auth/session':
                with LOCK,db() as c: status,data,headers=auth_http.session(c,self.headers)
                self.send_json(status,data,headers);return
            if path.startswith('/api/') and not self.guard('GET',path):return
            if path in ('/','/index.html'):
                with LOCK,db() as c: status,_,_=auth_http.session(c,self.headers)
                if status!=200:
                    self.send_response(303);self.send_header('Location','/account.html');self.send_header('Cache-Control','no-store');self.end_headers();return
            if path=='/api/github/status':
                self.send_json(200, github_bridge.config()); return
            if path=='/api/bootstrap':
                self.send_json(200,dict(stages=STAGES,agents=AGENTS,projects=self.visible_projects(),provider=dict(mode=PROVIDER,modelA=MODEL_A if PROVIDER!='demo' else 'Demo mode',modelB=MODEL_B if PROVIDER!='demo' else 'Demo mode'),version='0.6.0-web-first')); return
            if path.startswith('/api/projects/') and path.endswith('/members'):
                with LOCK,db() as c: data=rows(c,'SELECT user_id,role FROM auth_memberships WHERE project_id=?', (self.auth_context[1],))
                self.send_json(200,{'members':data});return
            if path.startswith('/api/projects/') and path.endswith('/audit'):
                with LOCK,db() as c: data=rows(c,'SELECT * FROM auth_audit WHERE project_id=? ORDER BY id DESC LIMIT 100',(self.auth_context[1],))
                self.send_json(200,{'audit':data});return
            if path.startswith('/api/projects/') and path.endswith('/coding'):
                pid = path.split('/')[3]
                with LOCK,db() as c:
                    if not c.execute('SELECT 1 FROM projects WHERE id=?',(pid,)).fetchone():
                        raise ValueError('Dự án không tồn tại')
                    jobs = coding_factory.list_jobs(c,pid)
                self.send_json(200, {'jobs': jobs}); return
            if path.startswith('/api/coding/'):
                parts = path.strip('/').split('/')
                if len(parts) in (3,4) and parts[:2]==['api','coding']:
                    with LOCK,db() as c:
                        if len(parts)==4 and parts[3]=='quality':
                            from quality_dashboard import quality_summary
                            self.send_json(200,quality_summary(c,coding_factory.detail(c,parts[2])));return
                        if len(parts)==4 and parts[3]=='verifications':
                            coding_factory.detail(c,parts[2])
                            self.send_json(200,{'verifications': verification_factory.list_reports(c,parts[2])});return
                        if len(parts)==4 and parts[3]=='download':
                            data=coding_factory.export_zip(c,parts[2])
                            self.send_zip('orbit-coding-'+parts[2]+'.zip',data);return
                        if len(parts)==3:
                            self.send_json(200,coding_factory.detail(c,parts[2]));return
            if path.startswith('/api/projects/') and path.endswith('/github'):
                with LOCK,db() as c: data=github_bridge.exports(c,path.split('/')[3])
                self.send_json(200,{'exports':data});return
            if path.startswith('/api/projects/') and path.endswith('/state'):
                self.send_json(200,project_state(path.split('/')[3])); return
            if path.startswith('/api/artifacts/'):
                aid=path.split('/')[3]
                with LOCK,db() as c: a=c.execute('SELECT * FROM artifacts WHERE id=?',(aid,)).fetchone()
                if not a: raise ValueError('Không tìm thấy artifact')
                self.send_json(200,dict(a)); return
            if path=='/api/chat':
                q=parse_qs(urlparse(self.path).query);pid=q.get('project_id',[''])[0];aid=q.get('agent_id',[''])[0]
                with LOCK,db() as c: data=rows(c,'SELECT * FROM chat WHERE project_id=? AND agent_id=? ORDER BY rowid DESC LIMIT 60',(pid,aid))
                self.send_json(200,dict(messages=list(reversed(data))));return
            if path.startswith('/api/'): self.send_json(404,{'error':'Endpoint không tồn tại'}); return
            if path=='/':self.path='/index.html'
            elif path not in ('/index.html','/account.html','/auth-account.js','/auth.css','/styles.css','/world3d.js','/app.js'):
                self.send_json(404,{'error':'Not found'});return
            return super().do_GET()
        except Exception as ex: self.send_json(400,{'error':str(ex)})
    def do_POST(self):
        if (not self.request_is_local() or self.headers.get('X-ORBIT-UI') != '1'
                or not self.headers.get('Content-Type','').startswith('application/json')):
            self.send_json(403,{'error':'JSON request from ORBIT same-origin UI required'}); return
        path=urlparse(self.path).path
        try:
            body=self.json_body()
            if path in ('/api/auth/login','/api/auth/logout'):
                with LOCK,db() as c:
                    status,data,headers=auth_http.handle(c,path,self.headers,body,PORT)
                self.send_json(status,data,headers);return
            if not isinstance(body,dict):raise ValueError('Invalid body')
            if not self.guard('POST',path,body):return
            if path=='/api/coding/start':
                pid = str(body.get('project_id',''))
                spec = body.get('spec','')
                llm = None if PROVIDER=='demo' else model_call
                def runner(jid, project_id):
                    coding_factory.work(db,LOCK,jid,project_id,llm,now,log,get_preceding)
                jid = coding_factory.begin(db,LOCK,pid,spec,uid,now,log,runner)
                self.send_json(202, {'job_id':jid,'mode':PROVIDER,'status':'queued'});return
            if path=='/api/github/preview':
                with LOCK,db() as c:
                    plan=github_bridge.preview(c,str(body.get('project_id','')),str(body.get('artifact_id','')))
                self.send_json(200,plan);return
            if path=='/api/github/draft-pr':
                result=github_bridge.create_export(db,LOCK,str(body.get('project_id','')),
                           str(body.get('artifact_id','')),str(body.get('confirmation','')))
                self.send_json(201,result);return
            if path=='/api/projects':
                name=str(body.get('name','')).strip();idea=str(body.get('idea','')).strip()
                if len(name)<3 or len(idea)<10: raise ValueError('Tên tối thiểu 3 ký tự, ý tưởng tối thiểu 10 ký tự')
                platform=str(body.get('platform','Web app'))
                if platform not in ('Web app','SaaS + API'):raise ValueError('Web platform required')
                with LOCK,db() as c:
                    pid=create_project(name,idea,platform,c)
                    auth_store.grant(c,self.auth_context[0],pid,'owner')
                    auth_store.authorize(c,self.auth_context[0],pid,'manage')
                self.auth_context=(self.auth_context[0],pid,'create')
                self.send_json(201,{'project_id':pid});return
            if path.startswith('/api/projects/'):
                spl=path.strip('/').split('/')
                if len(spl)==4 and spl[0]=='api' and spl[1]=='projects':
                    pid,action=spl[2:]
                    if action=='members':
                        with LOCK,db() as c:
                            auth_policy.set_member(c,self.auth_context[0],pid,str(body.get('user','')),str(body.get('role','')))
                        self.send_json(200,{'ok':True});return
                    if action=='run': run_pipeline(pid,str(body.get('mode','next'))); self.send_json(200,{'ok':True});return
                    if action=='pause':
                        if not RUNNING.get(pid,{}).get('running'): raise ValueError('Dự án không chạy')
                        RUNNING[pid]['pause']=True
                        self.send_json(200,{'ok':True});return
            if path.startswith('/api/stages/'):
                spl=path.strip('/').split('/')
                if len(spl)==5 and spl[:2]==['api','stages']:
                    pid,sid,action=spl[2:]
                    if sid not in STAGE_BY_ID: raise ValueError('Phòng ban không hợp lệ')
                    if action=='approve':approve_stage(pid,sid);self.send_json(200,{'ok':True});return
                    if action=='retry':retry_stage(pid,sid);self.send_json(200,{'ok':True});return
            if path=='/api/chat':
                reply=agent_chat(str(body.get('project_id','')),str(body.get('agent_id','')),str(body.get('message','')))
                self.send_json(200,{'reply':reply});return
            self.send_json(404,{'error':'Endpoint không tồn tại'})
        except PermissionError:
            self.send_json(403,{'error':'Access denied'})
        except Exception as ex:
            self.send_json(400,{'error':str(ex)})


def main():
    if HOST not in ('127.0.0.1','localhost'):
        raise SystemExit('ORBIT is localhost-only until HTTPS/staging security is reviewed')
    init_db()
    srv=ThreadingHTTPServer((HOST,PORT),Handler)
    print(f'AI Studio Company → http://{HOST}:{PORT} | mode={PROVIDER} | modelA={MODEL_A} modelB={MODEL_B}',flush=True)
    try: srv.serve_forever()
    except KeyboardInterrupt: pass
    finally:srv.server_close()

if __name__=='__main__':main()
