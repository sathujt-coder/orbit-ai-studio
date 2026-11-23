"""Safe, opt-in GitHub bridge for *documentation-only* draft pull requests.

The browser never receives a token. No merges, executable code writes, releases,
or unattended GitHub mutations are implemented here.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import sys

TOOLS = Path(__file__).resolve().parents[1] / 'tools'
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))
from github_pr import GitHubClient, GitHubError, VALID_REPO

EXPECTED_PAIRS = lambda sid: {(f'{sid}-A', f'{sid}-B'), (f'{sid}-B', f'{sid}-A')}


def safe_repo(repo: str) -> bool:
    return bool(VALID_REPO.fullmatch(repo or '')) and '..' not in repo and not repo.startswith('-')


def config():
    repo = os.getenv('ORBIT_GITHUB_REPO', 'sathujt-coder/orbit-ai-studio').strip()
    return {
        'repo': repo if safe_repo(repo) else None,
        'token_configured': bool(os.getenv('GITHUB_TOKEN')),
        'writes_enabled': os.getenv('ORBIT_GITHUB_WRITES') == '1',
        'mode': 'draft-docs-only',
    }


def reviewed_artifact(conn, project_id: str, artifact_id: str):
    """Verify actual local final artifact and two *latest* independent approvals.

    Checks do not claim the reviewers are independent model vendors or human reviewers.
    """
    artifact = conn.execute('SELECT * FROM artifacts WHERE id=? AND project_id=?',
                            (artifact_id, project_id)).fetchone()
    if not artifact:
        raise ValueError('Không tìm thấy tài liệu của dự án')
    artifact = dict(artifact)
    if artifact['kind'] != 'final':
        raise ValueError('Chỉ được gửi bản final sau khi review chéo')
    stage = artifact['stage_id']
    task = conn.execute('SELECT status FROM tasks WHERE project_id=? AND stage_id=?',
                        (project_id, stage)).fetchone()
    if not task or task['status'] not in ('done', 'approved'):
        raise ValueError('Giai đoạn chưa hoàn tất / chưa qua human approval')
    latest_final = conn.execute('SELECT id FROM artifacts WHERE project_id=? AND stage_id=? '
                                "AND kind='final' ORDER BY rowid DESC LIMIT 1", (project_id, stage)).fetchone()
    if not latest_final or latest_final['id'] != artifact_id:
        raise ValueError('Không được gửi tài liệu final cũ; hãy chọn bản mới nhất')
    run_id=artifact.get('run_id')
    if not run_id:
        raise ValueError('Tài liệu legacy chưa có run_id để chứng minh review; chạy lại giai đoạn')
    drafts = conn.execute('SELECT agent_id FROM artifacts WHERE project_id=? AND stage_id=? '
                          "AND kind='draft' AND run_id=?", (project_id,stage,run_id)).fetchall()
    if {r['agent_id'] for r in drafts} != {f'{stage}-A',f'{stage}-B'}:
        raise ValueError('Thiếu hai phương án độc lập trong cùng lượt chạy')
    reviews = conn.execute('SELECT reviewer_id,author_id,verdict,score FROM reviews '
                           'WHERE project_id=? AND stage_id=? AND run_id=? ORDER BY rowid DESC LIMIT 2',
                           (project_id, stage, run_id)).fetchall()
    if len(reviews) != 2 or {(r['reviewer_id'], r['author_id']) for r in reviews} != EXPECTED_PAIRS(stage):
        raise ValueError('Không tìm thấy đủ hai lượt review chéo A ↔ B')
    if any(r['verdict'] != 'APPROVE' or r['score'] < 80 for r in reviews):
        raise ValueError('Review chéo chưa vượt quality gate >= 80 điểm')
    if len(artifact['content'].encode('utf-8')) > 200000:
        raise ValueError('Tài liệu lớn hơn 200 KB')
    return artifact


def preview(conn, pid, aid):
    a = reviewed_artifact(conn, pid, aid)
    existing = conn.execute('SELECT status,pr_url,pr_number,branch FROM github_exports '
                            'WHERE artifact_id=?', (aid,)).fetchone()
    return {
        'artifact_id': a['id'], 'project_id': pid,
        'stage': a['stage_id'], 'path': f"docs/agent-deliverables/{a['id']}.md",
        'review': '2/2 APPROVE · mỗi điểm >=80 · stage done/approved',
        'bytes': len(a['content'].encode('utf-8')),
        'existing': dict(existing) if existing else None,
        'warning': 'Tạo nhánh và draft PR tài liệu; không merge, không chạy mã, không phát hành store.',
    }


def create_export(conn_factory, lock, pid, aid, confirmation, client_factory=GitHubClient):
    cfg = config()
    if confirmation != 'CREATE DRAFT PR':
        raise ValueError('Cần xác nhận chính xác CREATE DRAFT PR')
    if not cfg['repo']:
        raise ValueError('ORBIT_GITHUB_REPO không hợp lệ')
    if not cfg['writes_enabled']:
        raise ValueError('Chưa bật ORBIT_GITHUB_WRITES=1 trên backend')
    if not cfg['token_configured']:
        raise ValueError('Chưa đặt GITHUB_TOKEN trên backend; không nhập token vào trình duyệt')
    with lock, conn_factory() as conn:
        a = reviewed_artifact(conn, pid, aid)
        prev = conn.execute('SELECT status,pr_url FROM github_exports WHERE artifact_id=?', (aid,)).fetchone()
        if prev and prev['status'] in ('pending', 'created'):
            raise ValueError('Tài liệu đã gửi hoặc đang gửi GitHub: ' + (prev['pr_url'] or 'pending'))
        if prev:
            conn.execute('UPDATE github_exports SET status=?,error=NULL,updated_at=datetime("now") '
                         'WHERE artifact_id=?', ('pending', aid))
        else:
            conn.execute('INSERT INTO github_exports(artifact_id,project_id,repo,status,updated_at) '
                         'VALUES(?,?,?,?,datetime("now"))', (aid,pid,cfg['repo'],'pending'))
    try:
        result = client_factory(os.getenv('GITHUB_TOKEN', '')).draft_pr_for_artifact(cfg['repo'], a)
        url = str(result['url'])
        # Do not treat untrusted API response fields as a redirect target.
        required_prefix = 'https://github.com/' + cfg['repo'] + '/pull/'
        if not url.startswith(required_prefix) or not url[len(required_prefix):].isdigit():
            raise GitHubError('GitHub returned unexpected pull request URL')
        with lock, conn_factory() as conn:
            conn.execute('UPDATE github_exports SET status=?,pr_url=?,pr_number=?,branch=?,updated_at=datetime("now") '
                         'WHERE artifact_id=?', ('created',url,result['number'],result['branch'],aid))
            conn.execute('INSERT INTO events VALUES(lower(hex(randomblob(6))),?,?,?,?,?,datetime("now"))',
                         (pid,a['stage_id'],None,'success','Đã tạo GitHub draft PR #'+str(result['number'])+' cho '+a['stage_id']))
        return {'repo':cfg['repo'], 'url':url, 'number':result['number'], 'branch':result['branch'], 'status':'created'}
    except Exception as exc:
        with lock, conn_factory() as conn:
            conn.execute('UPDATE github_exports SET status=?,error=?,updated_at=datetime("now") '
                         'WHERE artifact_id=?', ('failed','GitHub export failed. See local backend logs.',aid))
        raise GitHubError('Không tạo được draft PR: ' + str(exc)) from None


def exports(conn, pid):
    return [dict(r) for r in conn.execute('SELECT artifact_id,repo,status,pr_url,pr_number,branch,updated_at '
                                         'FROM github_exports WHERE project_id=? ORDER BY updated_at DESC LIMIT 50',
                                         (pid,)).fetchall()]
