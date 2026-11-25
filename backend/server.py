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
import acceptance_store
import product_requirements
import project_planning
import planning_discovery
import planning_jobs
import work_breakdown
import requirements_discovery
import requirements_jobs
import model_provider
import provider_settings
import usage_store
import cost_store
import resource_manager
import agent_queue
import concurrency_control
import model_routing
import inference_guard
import monitoring
import transport_security

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / 'web'
DB_PATH = Path(os.environ.get('AI_COMPANY_DB', str(ROOT / 'company.sqlite')))
HOST = os.environ.get('AI_HOST', '127.0.0.1')
PORT = int(os.environ.get('AI_PORT', '8787'))
TRANSPORT = transport_security.load(os.environ)
MODEL_LANES = model_provider.load_config(os.environ)
PROVIDER = model_provider.mode(MODEL_LANES)
MODEL_A = MODEL_LANES['A'].model
MODEL_B = MODEL_LANES['B'].model
LOCK = threading.RLock()
RESOURCE_MANAGER = resource_manager.Manager()
CONCURRENCY = concurrency_control.Limiter()
BUDGET_GUARD = inference_guard.Guard()
MONITOR = monitoring.Monitor()
ROUTING = model_routing.load(os.environ,MODEL_LANES)
RESOURCE_MODEL_LOCK = threading.Lock()
RESOURCE_MODEL_LAST = 0.0
QUEUE_WAKE = threading.Event()
QUEUE_STOP = threading.Event()
QUEUE_THREADS = []
QUEUE_FAILED = threading.Event()

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
        acceptance_store.ensure_schema(c)
        provider_settings.ensure_schema(c)
        usage_store.ensure_schema(c)
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
        product_requirements.ensure_schema(c)
        project_planning.ensure_schema(c)
        agent_queue.ensure_schema(c)
        requirements_jobs.ensure_schema(c)
        planning_jobs.ensure_schema(c)
        work_breakdown.ensure_schema(c)
        model_routing.ensure_schema(c)
        monitoring.ensure_schema(c)
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
        q=agent_queue.active(c,pid,'pipeline')
        return dict(project=dict(p),tasks=tasks,artifacts=artifacts,reviews=reviews,events=events,
                    stats=dict(done=done,total=len(tasks),percent=round(done/len(tasks)*100),artifacts=len(artifacts),reviews=len(reviews),active=working['stage_id'] if working else None),running=bool(q and q['status'] in ('queued','running')),pause_requested=bool(q and q['control']=='pause'))


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
    indexed={}
    for r in result:indexed.setdefault(r['stage_id'],r['content'])
    return '\n\n'.join('['+s+'] '+indexed[s][:1200] for s in STAGE_IDS[:ix] if s in indexed)[-7500:]


def monitor_workers():
    return {'configured':CONCURRENCY.policy['workers'],'alive':sum(w.is_alive() for w in QUEUE_THREADS),'failed':QUEUE_FAILED.is_set()}

def monitor_args():
    return (db,LOCK,RESOURCE_MANAGER,CONCURRENCY,monitor_workers,BUDGET_GUARD,AGENTS,
            lambda c:provider_settings.load(c,os.environ,MODEL_LANES)[1],ROUTING['mode'])

def provider_snapshot():
    with LOCK,db() as c:return provider_settings.load(c,os.environ,MODEL_LANES)

def route_pair(base,pid,run_id,department,kind,chars,*,preview=False):
    task=model_routing.classify(department,kind,chars)
    metrics={};gpu=None
    if ROUTING['mode']=='smart' and model_provider.mode(base)!='demo':
        metrics=RESOURCE_MANAGER.measure_fn()
        if any(r['min_vram_mib'] for pool in ROUTING['registry'].values() for r in pool):
            gpu=RESOURCE_MANAGER.snapshot(include_gpu=True)['gpu']
    with LOCK,db() as c:
        lanes,decision=model_routing.select(c,ROUTING,base,task,metrics,gpu)
        if not preview:model_routing.record(c,pid,run_id,decision)
    if preview:return decision
    if lanes is None:raise model_provider.RoutingError('No eligible distinct routing pair; inspect routing history')
    return lanes

def snapshot_call(lanes,*,project_id=None,department='system',purpose='unattributed',run_id=None):
    def tracked(system,user,lane,phase,**kwargs):
        return usage_store.tracked_chat(db,LOCK,lanes[lane],system,user,project_id=project_id,
            agent_id=department+'-'+lane,purpose=phase,run_id=run_id,runtime_settings=True,resource_guard=RESOURCE_MANAGER,concurrency_guard=CONCURRENCY,budget_guard=BUDGET_GUARD,**kwargs)
    def call(system,user,lane='A',*,phase=None):
        return tracked(system,user,lane,phase or purpose)
    def structured(system,user,lane,schema):
        phase=('code_generate' if schema is coding_factory.PROPOSAL_SCHEMA else
               'code_review' if schema is coding_factory.REVIEW_SCHEMA else 'structured')
        return tracked(system,user,lane,phase,schema=schema,max_tokens=lanes[lane].max_tokens)
    call.structured=structured
    return call

def model_call(system,user,lane='A'):
    return snapshot_call(provider_snapshot()[1])(system,user,lane)

def structured_model_call(system,user,lane,schema):
    return snapshot_call(provider_snapshot()[1]).structured(system,user,lane,schema)
model_call.structured=structured_model_call


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


def run_stage(pid, sid, lanes=None):
    lanes=provider_snapshot()[1] if lanes is None else lanes
    run_id=uid()
    with LOCK,db() as c:
        project=dict(c.execute('SELECT * FROM projects WHERE id=?',(pid,)).fetchone())
    context=get_preceding(pid,sid)
    lanes=route_pair(lanes,pid,run_id,sid,'stage',len(project['idea'])+len(context))
    mode=model_provider.mode(lanes)
    llm=snapshot_call(lanes,project_id=pid,department=sid,run_id=run_id,purpose='stage')
    s=STAGE_BY_ID[sid]
    set_status(pid,sid,'drafting',f'{s["name"]}: A và B bắt đầu nghiên cứu độc lập.')
    drafts={}
    for lane in ('A','B'):
        aid=f'{sid}-{lane}'
        if mode=='demo':
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
            draft=llm(system,user,lane,phase='stage_draft')
        drafts[lane]=draft
        save_artifact(pid,sid,aid,'draft',draft,run_id)
        set_status(pid,sid,'drafting',f'{aid} hoàn thành bản đề xuất độc lập.',aid)
    set_status(pid,sid,'reviewing',f'{s["name"]}: hai agent review chéo, không tự chấm bài của mình.')
    votes=[]
    for reviewer,author in (('A','B'),('B','A')):
        if mode=='demo':
            time.sleep(.3)
            verdict,score,feedback='APPROVE',(89 if reviewer=='A' else 92),f'Đã rà soát phương án {author}: cần kiểm chứng giả định và thêm số liệu thực tế trước khi production.'
        else:
            raw=llm('Bạn là chuyên gia audit chất lượng. Chỉ trả JSON hợp lệ; không dùng markdown code fence.',review_prompt(sid,author,reviewer,drafts[author]),reviewer,phase='stage_review')
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
    if mode=='demo':
        final=(f'# {s["deliverable"]} · Bản hợp nhất\n\n'
               f'> DEMO: ví dụ minh họa workflow, chưa phải deliverable được AI nghiên cứu/triển khai thật.\n\n'
               f'## Phương án A\n{drafts["A"][:3500]}\n\n## Góc nhìn độc lập B\n{drafts["B"][:2700]}\n\n'
               '## Kết luận review chéo\n- Hai agent đã review bản nháp của nhau.\n- Cần xác minh bằng chứng, chạy test thực, và phê duyệt trước khi xuất bản.\n')
    else:
        user=(f'Gộp hai phương án {s["name"]} thành một deliverable chất lượng để chuyển cho team sau. '
              'Giữ các quyết định có căn cứ, nêu rõ các điểm chưa xác minh, acceptance criteria và next steps. '
              'Không tuyên bố đã thực thi code, test hay phát hành nếu chưa thực hiện.\n\n'
              f'A:\n{drafts["A"][:9000]}\n\nB:\n{drafts["B"][:9000]}')
        final=llm('Bạn tổng hợp deliverable đã được review chéo. Trả về Markdown rõ ràng.',user,'A',phase='stage_synthesis')
    save_artifact(pid,sid,f'{sid}-A','final',final,run_id)
    if s['approval']:
        set_status(pid,sid,'awaiting_approval',f'{s["name"]} hoàn tất review; đang đợi chủ dự án phê duyệt.','','warning')
        return 'awaiting_approval'
    set_status(pid,sid,'done',f'{s["name"]} hoàn thành và chuyển tiếp giai đoạn.','','success')
    return 'done'


def enqueue_pipeline(pid,actor,mode,priority=5,dependency_id=None,retry_of=None):
    if mode not in ('next','all'):raise ValueError('mode phải là next/all')
    with LOCK,db() as c:
        existing=agent_queue.active(c,pid,'pipeline')
        if existing:
            if existing['status']=='waiting_approval' and not dependency_id and retry_of is None:
                if mode!=existing['mode']:raise ValueError('Resume original pipeline mode from Task Queue or cancel it')
                agent_queue.control(c,pid,existing['id'],actor,'resume',int(time.time()),now())
                identifier=existing['id']
            else:raise ValueError('Project pipeline already queued; use Task Queue controls')
        else:
            stage=agent_queue.next_stage(c,pid)
            if stage is None or stage['status']!='queued':raise ValueError('No eligible stage; resolve quality or approval gate first')
            revision,lanes=provider_settings.load(c,os.environ,MODEL_LANES)
            identifier=agent_queue.enqueue(c,pid,'pipeline',actor,revision,lanes,mode=mode,priority=priority,dependency_id=dependency_id,retry_of=retry_of,routing=ROUTING['fingerprint'])
    QUEUE_WAKE.set()
    return identifier

def enqueue_coding(pid,actor,spec,priority=5,dependency_id=None,retry_of=None):
    with LOCK:
        revision,lanes=provider_snapshot()
        task={}
        def insert(c,jid):
            task['id']=agent_queue.enqueue(c,pid,'coding',actor,revision,lanes,coding_job_id=jid,priority=priority,dependency_id=dependency_id,retry_of=retry_of,routing=ROUTING['fingerprint'])
        jid=coding_factory.begin(db,LOCK,pid,spec,uid,now,log,None,enqueue=insert)
    QUEUE_WAKE.set()
    return {'job_id':jid,'queue_id':task['id'],'mode':model_provider.mode(lanes),'provider_revision':revision,'status':'queued'}

def enqueue_requirements(pid,actor,priority=5,dependency_id=None,retry_of=None,scope_contract=None):
    with LOCK,db() as c:
        revision,lanes=provider_settings.load(c,os.environ,MODEL_LANES)
        identifier=requirements_jobs.enqueue(c,pid,actor,revision,lanes,now(),priority=priority,
            dependency_id=dependency_id,retry_of=retry_of,routing=ROUTING['fingerprint'],scope_contract=scope_contract)
    QUEUE_WAKE.set()
    return {'queue_id':identifier,'status':'queued'}

def run_requirements(pid,identifier,lanes):
    with LOCK,db() as c:snapshot=requirements_jobs.input_for(c,pid,identifier)
    idea=snapshot['idea']
    contract=json.loads(snapshot['scope_contract']) if snapshot['scope_contract'] else None
    lanes=model_provider.require_distinct_real(route_pair(lanes,pid,identifier,'po','requirements',len(idea)))
    def call(lane,phase,system,user,schema):
        with LOCK,db() as c:
            row=agent_queue.get(c,pid,identifier)
            if row['status']!='running' or not agent_queue.permitted(c,row['actor'],pid):
                raise PermissionError('Discovery no longer authorized')
        try:
            return usage_store.tracked_chat(db,LOCK,lanes[lane],system,user,project_id=pid,
                agent_id=({'research':'research','ba':'ba'}.get(phase.split('_',1)[0],'po'))+'-'+lane,purpose=phase,run_id=identifier,runtime_settings=True,
                max_tokens=min(768 if phase.startswith(('research_','ba_')) else 2048,lanes[lane].max_tokens),schema=schema,
                resource_guard=RESOURCE_MANAGER,concurrency_guard=CONCURRENCY,budget_guard=BUDGET_GUARD)
        except model_provider.ProviderError as error:
            # OutputError is eligible for existing bounded document repair. Other failures are
            # never replayed; expose only a fixed class and trusted phase, not provider payloads.
            if isinstance(error,model_provider.OutputError):raise
            raise RuntimeError('requirements_provider_failure:'+phase+':'+type(error).__name__) from error
    evidence=requirements_discovery.collaborate(call,idea,scope_contract=contract)
    # Evidence and terminal queue state commit atomically. Crash before this transaction is
    # uncertain execution; startup recovery will never automatically replay it.
    with LOCK,db() as c:
        result=requirements_jobs.persist(c,pid,identifier,evidence,lanes,now())
        agent_queue.boundary(c,agent_queue.get(c,pid,identifier),result,int(time.time()),now())

def enqueue_planning(pid,actor,body,priority=5,dependency_id=None,retry_of=None):
    required={'requirements_version','requirements_digest','confirmation'}
    if not required<=set(body) or set(body)-required-{'scope_contract'}:raise ValueError('Invalid planning request fields')
    if body['confirmation']!='RUN AI PLANNING':raise ValueError('Explicit RUN AI PLANNING required')
    with LOCK,db() as c:
        revision,lanes=provider_settings.load(c,os.environ,MODEL_LANES)
        identifier=planning_jobs.enqueue(c,pid,actor,revision,lanes,now(),version=body['requirements_version'],
            digest=body['requirements_digest'],priority=priority,dependency_id=dependency_id,retry_of=retry_of,routing=ROUTING['fingerprint'],scope_contract=body.get('scope_contract'))
    QUEUE_WAKE.set()
    return {'queue_id':identifier,'status':'queued'}

def run_planning(pid,identifier,lanes):
    with LOCK,db() as c:source=planning_jobs.checked_input(c,pid,identifier)
    packet=planning_discovery.packet(source)
    lanes=model_provider.require_distinct_real(route_pair(lanes,pid,identifier,'pm','planning',len(product_requirements.canonical(packet))))
    def call(lane,phase,system,user,schema):
        with LOCK,db() as c:planning_jobs.checked_input(c,pid,identifier)
        return usage_store.tracked_chat(db,LOCK,lanes[lane],system,user,project_id=pid,agent_id='pm-'+lane,
            purpose=phase,run_id=identifier,runtime_settings=True,max_tokens=min(2048,lanes[lane].max_tokens),
            schema=schema,resource_guard=RESOURCE_MANAGER,concurrency_guard=CONCURRENCY,budget_guard=BUDGET_GUARD)
    evidence=planning_discovery.discover(call,source)
    with LOCK,db() as c:
        result=planning_jobs.persist(c,pid,identifier,evidence,lanes,now())
        agent_queue.boundary(c,agent_queue.get(c,pid,identifier),result,int(time.time()),now())

def dispatch_one():
    with LOCK,db() as c:
        if QUEUE_STOP.is_set():return False
        # Stop before claiming so paused dispatch does not inflate attempts or history.
        if inference_guard.control(c)['stopped']:
            try:_,base=provider_settings.load(c,os.environ,MODEL_LANES)
            except (ValueError,PermissionError):return False
            if model_provider.mode(base)!='demo':return False
        row=agent_queue.claim(c,int(time.time()),now())
    if not row:return False
    pid,identifier=row['project_id'],row['id']
    stage=None
    try:
        with LOCK,db() as c:
            row=agent_queue.get(c,pid,identifier)
            if not agent_queue.permitted(c,row['actor'],pid):
                agent_queue.fail(c,row,'permission_revoked',int(time.time()),now());return True
            revision,lanes=provider_settings.load(c,os.environ,MODEL_LANES)
            if revision!=row['provider_revision'] or agent_queue.fingerprint(lanes,ROUTING['fingerprint'])!=row['provider_fingerprint']:
                agent_queue.fail(c,row,'provider_configuration_changed',int(time.time()),now());return True
            if row['control']:
                agent_queue.defer(c,row,int(time.time()),now());return True
            mode=model_provider.mode(lanes)
            if mode!='demo' and inference_guard.control(c)['stopped']:
                # Stop raced with a claim, but no execution has begun.
                agent_queue.change(c,row,'queued','emergency_stop',int(time.time()),attempts=max(0,row['attempts']-1),available_at=int(time.time()))
                return True
            if mode!='demo' and RESOURCE_MANAGER.policy['mode']=='enforce' and resource_manager.pressure(RESOURCE_MANAGER.measure_fn(),RESOURCE_MANAGER.policy):
                agent_queue.defer(c,row,int(time.time()),now());return True
            if row['kind']=='pipeline':
                target=agent_queue.next_stage(c,pid)
                if target is None:
                    agent_queue.change(c,row,'succeeded','pipeline_complete',int(time.time()),control='');return True
                if target['status']=='awaiting_approval':
                    agent_queue.change(c,row,'waiting_approval','stage_approval_required',int(time.time()),control='');return True
                if target['status']!='queued':
                    agent_queue.fail(c,row,'stage_not_eligible',int(time.time()),now());return True
                stage=target['stage_id']
        if row['kind']=='planning':
            run_planning(pid,identifier,lanes)
            return True
        if row['kind']=='requirements':
            run_requirements(pid,identifier,lanes)
            return True
        if row['kind']=='pipeline':
            result=run_stage(pid,stage,lanes)
        else:
            jid=row['coding_job_id']
            with LOCK,db() as c:
                spec=c.execute('SELECT spec FROM coding_jobs WHERE id=?',(jid,)).fetchone()[0]
            lanes=route_pair(lanes,pid,jid,'dev','coding',len(spec)+len(get_preceding(pid,'dev')))
            mode=model_provider.mode(lanes)
            llm=None if mode=='demo' else snapshot_call(lanes,project_id=pid,department='dev',purpose='coding',run_id=jid)
            coding_factory.work(db,LOCK,jid,pid,llm,now,log,get_preceding)
            with LOCK,db() as c:
                result=c.execute('SELECT status FROM coding_jobs WHERE id=?',(jid,)).fetchone()[0]
            if result not in ('ready','needs_revision','failed'):result='failed'
        with LOCK,db() as c:
            current=agent_queue.get(c,pid,identifier)
            agent_queue.boundary(c,current,result,int(time.time()),now(),stage)
    except Exception as error:
        # Do not log raw prompts/errors or automatically replay uncertain execution.
        with LOCK,db() as c:
            current=agent_queue.get(c,pid,identifier)
            if current['status']=='running':
                if row['kind']=='pipeline' and stage:
                    c.execute("UPDATE tasks SET status='needs_revision' WHERE project_id=? AND stage_id=? AND status IN ('drafting','reviewing','synthesizing')",(pid,stage))
                reason=('requirements_invalid_output:'+error.phase if isinstance(error,requirements_discovery.InvalidDocument) else 'execution_failed')
                if row['kind']=='requirements' and isinstance(error,RuntimeError) and str(error).startswith('requirements_provider_failure:'):
                    reason=str(error)[:160]
                agent_queue.fail(c,current,reason,int(time.time()),now())
    return True

def queue_worker():
    while not QUEUE_STOP.is_set():
        try:
            if dispatch_one():continue
        except Exception:
            # An uncertain DB commit is not safe to replay. Running rows remain for startup recovery.
            print('Queue dispatcher stopped after storage failure',file=sys.stderr,flush=True)
            QUEUE_FAILED.set();QUEUE_STOP.set();QUEUE_WAKE.set()
            return
        QUEUE_WAKE.wait(0.5);QUEUE_WAKE.clear()

def retry_queue(pid,identifier,actor,confirmation):
    if confirmation!='RETRY QUEUE TASK':raise ValueError('Explicit RETRY QUEUE TASK required')
    with LOCK:
        with db() as c:
            old=agent_queue.get(c,pid,identifier)
            if old['status'] not in ('dead','interrupted','cancelled'):raise ValueError('Only terminal failed/cancelled tasks can be retried')
            if not agent_queue.permitted(c,actor,pid):raise PermissionError('Project write permission required')
            dep=old['dependency_id']
            if dep and agent_queue.get(c,pid,dep)['status']!='succeeded':raise ValueError('Original dependency not successful; submit a new task')
            spec=c.execute('SELECT spec FROM coding_jobs WHERE id=?',(old['coding_job_id'],)).fetchone()[0] if old['kind']=='coding' else None
        if old['kind']=='coding':return enqueue_coding(pid,actor,spec,old['priority'],dep,identifier)
        if old['kind']=='planning':
            with db() as c:snapshot=planning_jobs.input_for(c,pid,identifier)
            return enqueue_planning(pid,actor,dict(requirements_version=snapshot['requirements_version'],
                requirements_digest=snapshot['requirements_digest'],confirmation='RUN AI PLANNING'),old['priority'],dep,identifier)
        if old['kind']=='requirements':return enqueue_requirements(pid,actor,old['priority'],dep,identifier)
        return {'queue_id':enqueue_pipeline(pid,actor,old['mode'],old['priority'],dep,identifier)}


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
    lanes=provider_snapshot()[1]
    sid=aid.rsplit('-',1)[0]
    if sid not in STAGE_BY_ID or aid not in [f'{sid}-A',f'{sid}-B']: raise ValueError('Agent không hợp lệ')
    if not message.strip(): raise ValueError('Nội dung trống')
    run_id=uid()
    with LOCK,db() as c:
        p=c.execute('SELECT * FROM projects WHERE id=?',(pid,)).fetchone()
        if not p: raise ValueError('Không tìm thấy dự án')
    context=get_preceding(pid,sid)
    lanes=route_pair(lanes,pid,run_id,sid,'chat',len(message[:2500])+len(context))
    llm=snapshot_call(lanes,project_id=pid,department=sid,purpose='agent_chat',run_id=run_id)
    with LOCK,db() as c:c.execute('INSERT INTO chat VALUES(?,?,?,?,?,?)',(uid(),pid,aid,'user',message[:2500],now()))
    if model_provider.mode(lanes)=='demo':
        reply=(f'[DEMO] Tôi là {aid}, phụ trách {STAGE_BY_ID[sid]["name"]}. '
               f'Với yêu cầu “{message[:110]}”, tôi đề xuất: (1) xác định đầu ra và tiêu chí chấp nhận; '
               '(2) tách giả định khỏi bằng chứng; (3) để agent còn lại review độc lập trước khi kết luận. '
               'Kết nối Ollama hoặc API để nhận tư vấn AI thực.')
    else:
        with LOCK,db() as c: p=dict(c.execute('SELECT * FROM projects WHERE id=?',(pid,)).fetchone())
        reply=llm(f'Bạn là {aid}, {STAGE_BY_ID[sid]["name"]}, một agent của công ty AI. '
                         'Trả lời ngắn gọn, thực tế và bằng tiếng Việt. Nếu không chắc, nói rõ giả định.',
                         f'Dự án: {p["name"]}\nBối cảnh:\n{context[:4000]}\n\nYêu cầu từ người quản lý:\n{message[:2500]}',aid[-1])
    with LOCK,db() as c: c.execute('INSERT INTO chat VALUES(?,?,?,?,?,?)',(uid(),pid,aid,'assistant',reply,now()))
    return reply


class Handler(SimpleHTTPRequestHandler):
    def __init__(self,*args,**kwargs): super().__init__(*args,directory=str(WEB),**kwargs)
    def log_message(self,format,*args): pass
    def end_headers(self):
        if TRANSPORT.secure:self.send_header('Strict-Transport-Security','max-age=300')
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('X-Frame-Options','DENY')
        self.send_header('Referrer-Policy','no-referrer')
        self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        super().end_headers()
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
        for key,value in (headers or {}).items(): self.send_header(key,value)
        self.end_headers(); self.wfile.write(raw)
    def json_body(self):
        length=int(self.headers.get('Content-Length','0'))
        if not 0<=length<=30000: raise ValueError('Dữ liệu quá lớn')
        return json.loads(self.rfile.read(length) or '{}')
    def request_is_local(self):
        return transport_security.request_allowed(TRANSPORT,self.headers,PORT,self.client_address[0])
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
            status,context=auth_policy.check(c,method,path,urlparse(self.path).query,body,self.headers,PORT,transport=TRANSPORT)
        if status!=200:
            self.send_json(status,{'error':{401:'Authentication required',403:'Access denied',404:'Endpoint không tồn tại'}[status]});return False
        self.auth_context=context
        return True
    def do_GET(self):
        if not self.request_is_local():
            self.send_json(403, {'error':'Local host/origin required'}); return
        path=urlparse(self.path).path
        try:
            if path=='/healthz':
                try:
                    with LOCK,db() as c:c.execute('SELECT 1 FROM projects LIMIT 1').fetchone()
                    if QUEUE_THREADS and (QUEUE_FAILED.is_set() or not all(w.is_alive() for w in QUEUE_THREADS)):self.send_json(503,{'status':'unavailable','reason':'queue_dispatcher_stopped'})
                    else:self.send_json(200,{'status':'ok'})
                except sqlite3.Error:self.send_json(503,{'status':'unavailable'})
                return
            if path=='/api/auth/session':
                with LOCK,db() as c: status,data,headers=auth_http.session(c,self.headers,secure=TRANSPORT.secure)
                self.send_json(status,data,headers);return
            if path.startswith('/api/') and not self.guard('GET',path):return
            if path in ('/','/index.html','/access.html','/providers.html','/usage.html','/cost.html','/resources.html','/queue.html','/routing.html','/protection.html','/monitoring.html','/requirements.html','/planning.html'):
                with LOCK,db() as c: status,session,_=auth_http.session(c,self.headers,secure=TRANSPORT.secure)
                if status!=200:
                    self.send_response(303);self.send_header('Location','/account.html');self.send_header('Cache-Control','no-store');self.end_headers();return
                if path in ('/routing.html','/protection.html','/monitoring.html') and not provider_settings.is_admin(session['user']):
                    self.send_json(403,{'error':'Operator required'});return
            if re.fullmatch(r'/api/projects/[A-Za-z0-9_-]{1,100}/planning',path):
                actor,pid,_=self.auth_context
                with LOCK,db() as c:
                    data=project_planning.view(c,pid)
                    data['discovery']=planning_jobs.latest(c,pid)
                    data['wbs']=work_breakdown.view(c,pid,data['discovery'])
                    data['can_write']=auth_store.authorize(c,actor,pid,'write')
                    data['can_approve']=auth_store.authorize(c,actor,pid,'approve')
                self.send_json(200,data);return
            if re.fullmatch(r'/api/projects/[A-Za-z0-9_-]{1,100}/requirements',path):
                actor,pid,_=self.auth_context
                with LOCK,db() as c:
                    data=product_requirements.view(c,pid)
                    data['discovery']=requirements_jobs.latest(c,pid)
                    data['idea']=c.execute('SELECT idea FROM projects WHERE id=?',(pid,)).fetchone()[0]
                    if data['current']:
                        adopted=c.execute('SELECT queue_id FROM requirement_discovery_adoptions WHERE project_id=? AND version=?',(pid,data['current']['version'])).fetchone()
                        if adopted:
                            data['current']['source']='ai_adopted'
                            data['current']['discovery_id']=adopted[0]
                    data['can_write']=auth_store.authorize(c,actor,pid,'write')
                    data['can_approve']=auth_store.authorize(c,actor,pid,'approve')
                self.send_json(200,data);return
            if path=='/api/github/status':
                self.send_json(200, github_bridge.config()); return
            if re.fullmatch(r'/api/projects/[A-Za-z0-9_-]{1,100}/queue(?:/[A-Za-z0-9_-]{1,100})?',path):
                parts=path.strip('/').split('/');pid=self.auth_context[1]
                with LOCK,db() as c:
                    if len(parts)==5:data={'events':agent_queue.history(c,pid,parts[4])}
                    else:
                        data=agent_queue.view(c,pid)
                        data['can_write']=agent_queue.permitted(c,self.auth_context[0],pid)
                        data['dispatcher_running']=bool(QUEUE_THREADS and not QUEUE_FAILED.is_set() and all(w.is_alive() for w in QUEUE_THREADS))
                        data['worker_count']=sum(w.is_alive() for w in QUEUE_THREADS)
                        data['worker_limit']=CONCURRENCY.policy['workers']
                self.send_json(200,data);return
            if path=='/api/provider/monitoring':
                data=MONITOR.view()
                with LOCK,db() as c:data['control']=inference_guard.control(c)
                self.send_json(200,data);return
            if path=='/api/provider/monitoring/history':
                q=parse_qs(urlparse(self.path).query)
                hours=int(q.get('hours',['24'])[0]);limit=int(q.get('limit',['240'])[0])
                with LOCK,db() as c:data=monitoring.history(c,int(time.time()),hours,limit)
                self.send_json(200,data);return
            if path=='/api/provider/resources':
                data=RESOURCE_MANAGER.snapshot(include_gpu=True)
                data['concurrency']=CONCURRENCY.snapshot()
                data['queue_workers']={'configured':CONCURRENCY.policy['workers'],'alive':sum(w.is_alive() for w in QUEUE_THREADS),'failed':QUEUE_FAILED.is_set()}
                self.send_json(200,data);return
            if path=='/api/provider/rates':
                with LOCK,db() as c:data=cost_store.rates_view(c,os.environ,MODEL_LANES)
                self.send_json(200,data);return
            if path=='/api/provider/cost' or (path.startswith('/api/projects/') and path.endswith('/cost')):
                days=int(parse_qs(urlparse(self.path).query).get('days',['7'])[0])
                actor,pid,_=self.auth_context
                with LOCK,db() as c:
                    data=cost_store.summary(c,pid,days,all_projects=path=='/api/provider/cost')
                    data['can_manage_budget']=bool(pid and c.execute("SELECT 1 FROM auth_memberships WHERE user_id=? AND project_id=? AND role='owner'",(actor,pid)).fetchone())
                self.send_json(200,data);return
            if path=='/api/provider/usage' or (path.startswith('/api/projects/') and path.endswith('/usage')):
                q=parse_qs(urlparse(self.path).query)
                days=int(q.get('days',['7'])[0])
                with LOCK,db() as c:data=usage_store.summary(c,self.auth_context[1],days,all_projects=path=='/api/provider/usage')
                self.send_json(200,data);return
            if path=='/api/provider/protection':
                with LOCK,db() as c:data=BUDGET_GUARD.view(c,all_projects=True)
                self.send_json(200,data);return
            if re.fullmatch(r'/api/projects/[A-Za-z0-9_-]{1,100}/protection',path):
                with LOCK,db() as c:data=BUDGET_GUARD.view(c,self.auth_context[1])
                self.send_json(200,data);return
            if path=='/api/provider/routing':
                with LOCK,db() as c:
                    data=model_routing.public(ROUTING)
                    data['history']=model_routing.history(c,all_projects=True)
                self.send_json(200,data);return
            if re.fullmatch(r'/api/projects/[A-Za-z0-9_-]{1,100}/routing',path):
                with LOCK,db() as c:data={'history':model_routing.history(c,self.auth_context[1])}
                self.send_json(200,data);return
            if path=='/api/provider/settings':
                with LOCK,db() as c:data=provider_settings.view(c,os.environ,MODEL_LANES)
                self.send_json(200,data);return
            if path=='/api/bootstrap':
                revision,lanes=provider_snapshot()
                agents=[dict(a,model=lanes[a['lane']].public()['model']) for a in AGENTS]
                self.send_json(200,dict(stages=STAGES,agents=agents,projects=self.visible_projects(),provider=dict(model_provider.public_config(lanes),revision=revision,routing_mode=ROUTING['mode']),provider_admin=provider_settings.is_admin(self.auth_context[0]),version='0.6.0-web-first')); return
            if path.startswith('/api/projects/') and path.endswith('/acceptance'):
                with LOCK,db() as c: data=acceptance_store.view(c,self.auth_context[1])
                self.send_json(200,data);return
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
            elif path not in ('/index.html','/account.html','/auth-account.js','/auth.css','/access.html','/access.js','/providers.html','/providers.js','/providers.css','/usage.html','/usage.js','/usage.css','/cost.html','/cost.js','/resources.html','/resources.js','/queue.html','/queue.js','/routing.html','/routing.js','/protection.html','/protection.js','/monitoring.html','/monitoring.js','/monitoring.css','/requirements.html','/requirements.js','/planning.html','/planning.js','/styles.css','/world3d.js','/app.js'):
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
                    status,data,headers=auth_http.handle(c,path,self.headers,body,PORT,transport=TRANSPORT)
                self.send_json(status,data,headers);return
            if not isinstance(body,dict):raise ValueError('Invalid body')
            if not self.guard('POST',path,body):return
            if re.fullmatch(r'/api/projects/[A-Za-z0-9_-]{1,100}/planning/discover',path):
                actor,pid,_=self.auth_context
                self.send_json(202,enqueue_planning(pid,actor,body));return
            if re.fullmatch(r'/api/projects/[A-Za-z0-9_-]{1,100}/planning/wbs(?:/seed)?',path):
                actor,pid,_=self.auth_context
                with LOCK,db() as c:
                    data=work_breakdown.save(c,pid,actor,body,now(),seed=path.endswith('/seed'))
                self.send_json(200,data);return
            if re.fullmatch(r'/api/projects/[A-Za-z0-9_-]{1,100}/planning(?:/(?:seed|approve))?',path):
                actor,pid,_=self.auth_context
                with LOCK,db() as c:
                    data=(project_planning.approve(c,pid,actor,body,now()) if path.endswith('/approve') else
                        project_planning.save(c,pid,actor,body,now(),seed=path.endswith('/seed')))
                self.send_json(200,data);return
            if re.fullmatch(r'/api/projects/[A-Za-z0-9_-]{1,100}/requirements/discover',path):
                actor,pid,_=self.auth_context
                if set(body)!={'confirmation','scope_contract'} or body['confirmation']!='RUN AI REQUIREMENTS':
                    raise ValueError('Explicit RUN AI REQUIREMENTS and scope contract required')
                self.send_json(202,enqueue_requirements(pid,actor,scope_contract=body['scope_contract']));return
            if re.fullmatch(r'/api/projects/[A-Za-z0-9_-]{1,100}/requirements/adopt',path):
                actor,pid,_=self.auth_context
                with LOCK,db() as c:data=requirements_jobs.adopt(c,pid,actor,body,now())
                self.send_json(200,data);return
            if re.fullmatch(r'/api/projects/[A-Za-z0-9_-]{1,100}/requirements(?:/approve)?',path):
                actor,pid,_=self.auth_context
                with LOCK,db() as c:
                    data=(product_requirements.approve(c,pid,actor,body,now()) if path.endswith('/approve') else product_requirements.save(c,pid,actor,body,now()))
                self.send_json(200,data);return
            if path=='/api/provider/protection/stop':
                with LOCK,db() as c:data=inference_guard.set_stop(c,self.auth_context[0],body,os.environ)
                QUEUE_WAKE.set();self.send_json(200,data);return
            if path=='/api/provider/routing/preview':
                if set(body)!={'department','kind','chars'}:raise ValueError('Routing preview accepts task metadata only')
                data=route_pair(provider_snapshot()[1],None,None,body['department'],body['kind'],body['chars'],preview=True)
                self.send_json(200,data);return
            if re.fullmatch(r'/api/projects/[A-Za-z0-9_-]{1,100}/queue/[A-Za-z0-9_-]{1,100}/(pause|resume|cancel|priority|retry)',path):
                actor,pid,_=self.auth_context;parts=path.strip('/').split('/');identifier,action=parts[4:]
                if action=='retry':data=retry_queue(pid,identifier,actor,body.get('confirmation'))
                else:
                    with LOCK,db() as c:row=agent_queue.control(c,pid,identifier,actor,action,int(time.time()),now(),body.get('priority'));data={'queue_id':row['id'],'status':row['status'],'control':row['control']}
                    QUEUE_WAKE.set()
                self.send_json(200,data);return
            if path=='/api/provider/resources/models':
                global RESOURCE_MODEL_LAST
                if body!={'confirmation':'READ LOCAL MODEL STATUS'}:raise ValueError('Explicit READ LOCAL MODEL STATUS required')
                if not RESOURCE_MODEL_LOCK.acquire(blocking=False):raise ValueError('Local model check already running')
                try:
                    if time.monotonic()-RESOURCE_MODEL_LAST<3:raise ValueError('Local model check rate limited')
                    RESOURCE_MODEL_LAST=time.monotonic()
                    _,lanes=provider_snapshot()
                    data={'lanes':{k:resource_manager.loaded_models(v) for k,v in lanes.items()}}
                finally:RESOURCE_MODEL_LOCK.release()
                self.send_json(200,data);return
            if path=='/api/provider/rates':
                with LOCK,db() as c:data=cost_store.save_rate(c,self.auth_context[0],body,os.environ,MODEL_LANES)
                self.send_json(200,data);return
            if path.startswith('/api/projects/') and path.endswith('/budget'):
                actor,pid,_=self.auth_context
                with LOCK,db() as c:data=cost_store.save_budget(c,pid,actor,body)
                self.send_json(200,data);return
            if path=='/api/provider/settings':
                with LOCK,db() as c:data=provider_settings.save(c,self.auth_context[0],body,os.environ,MODEL_LANES)
                self.send_json(200,data);return
            if path in ('/api/provider/probe','/api/provider/models'):
                probe_run=uid()
                def tracked_probe(lane,system,user,**kwargs):
                    return usage_store.tracked_chat(db,LOCK,lane,system,user,project_id=None,
                        agent_id='system-'+lane.lane,purpose='provider_probe',run_id=probe_run,resource_guard=RESOURCE_MANAGER,concurrency_guard=CONCURRENCY,budget_guard=BUDGET_GUARD,**kwargs)
                data=provider_settings.network_action(body,os.environ,MODEL_LANES,path.rsplit('/',1)[1],chat_fn=tracked_probe)
                self.send_json(200,data);return
            if path=='/api/coding/start':
                data=enqueue_coding(self.auth_context[1],self.auth_context[0],body.get('spec',''),body.get('priority',5),body.get('dependency_id'))
                self.send_json(202,data);return
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
                if len(spl)==5 and spl[3]=='acceptance':
                    actor,pid,_=self.auth_context
                    with LOCK,db() as c:
                        data=(acceptance_store.accept(c,pid,actor,body.get('confirmation')) if spl[4]=='signoff' else acceptance_store.record(c,pid,actor,body))
                    self.send_json(200,data);return
                if len(spl)==4 and spl[0]=='api' and spl[1]=='projects':
                    pid,action=spl[2:]
                    if action=='members':
                        with LOCK,db() as c:
                            auth_policy.set_member(c,self.auth_context[0],pid,str(body.get('user','')),str(body.get('role','')))
                        self.send_json(200,{'ok':True});return
                    if action=='run':
                        identifier=enqueue_pipeline(pid,self.auth_context[0],body.get('mode','next'),body.get('priority',5),body.get('dependency_id'))
                        self.send_json(200,{'ok':True,'queue_id':identifier});return
                    if action=='pause':
                        with LOCK,db() as c:
                            q=agent_queue.active(c,pid,'pipeline')
                            if not q:raise ValueError('Dự án không chạy')
                            agent_queue.control(c,pid,q['id'],self.auth_context[0],'pause',int(time.time()),now())
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
        except model_provider.BudgetError as ex:
            self.send_json(429,{'error':str(ex)})
        except model_provider.RoutingError as ex:
            self.send_json(503,{'error':str(ex)})
        except model_provider.ConcurrencyError as ex:
            self.send_json(429,{'error':str(ex)})
        except model_provider.ResourceError as ex:
            self.send_json(503,{'error':str(ex)})
        except PermissionError:
            self.send_json(403,{'error':'Access denied'})
        except Exception as ex:
            self.send_json(400,{'error':str(ex)})


def main():
    if HOST not in ('127.0.0.1','localhost') and not (TRANSPORT.secure and os.getenv('ORBIT_ALLOW_TLS_BIND')=='1'):
        raise SystemExit('Non-loopback binding requires explicit TLS configuration and opt-in')
    tls=TRANSPORT.context() if TRANSPORT.secure else None
    os.umask(0o077)
    with agent_queue.dispatcher_lock(DB_PATH):
        init_db()
        with LOCK,db() as c:
            agent_queue.recover(c,int(time.time()),now())
            BUDGET_GUARD.recover(c)
        srv=ThreadingHTTPServer((HOST,PORT),Handler)
        if tls:srv.socket=tls.wrap_socket(srv.socket,server_side=True)
        QUEUE_THREADS.extend(threading.Thread(target=queue_worker,name='orbit-worker-'+str(i+1),daemon=True) for i in range(CONCURRENCY.policy['workers']))
        for worker in QUEUE_THREADS:worker.start()
        MONITOR.start(*monitor_args())
        print(f'AI Studio Company → {TRANSPORT.origin or ("http://"+HOST+":"+str(PORT))} | mode={PROVIDER} | modelA={MODEL_A} modelB={MODEL_B}',flush=True)
        try: srv.serve_forever()
        except KeyboardInterrupt: pass
        finally:
            QUEUE_STOP.set();QUEUE_WAKE.set();CONCURRENCY.close();srv.server_close()
            MONITOR.close()
            # Preserve exclusive dispatcher ownership until all active units exit.
            for worker in QUEUE_THREADS:worker.join()

if __name__=='__main__':main()
