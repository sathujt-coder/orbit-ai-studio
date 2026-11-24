# ORBIT AI — Autonomous Software Studio (MVP 0.5)

**Công ty phần mềm AI ảo với văn phòng 3D, 12 phòng ban / 24 agent, review chéo A ↔ B, workflow trạng thái, human approval, chat agent và kho tài liệu.**

> **Phạm vi chính xác:** Bản này là MVP điều phối đa agent **có thể chạy**. Chế độ `demo` mô phỏng đầu ra, không thực hiện nghiên cứu hay viết/deploy phần mềm thật. Kết nối Ollama/API giúp agent tạo đầu ra AI thật (tài liệu, đặc tả, đánh giá) và v0.5 hỗ trợ **xác minh mã Python/JavaScript trong Docker qua CLI sau phê duyệt**; tuy nhiên vẫn chưa chạy Flutter build, kiểm thử ứng dụng thật hoặc tự xuất bản App Store / Google Play. Các tích hợp production nằm trong `docs/PRODUCTION_ROADMAP.md`.

## 1. Chạy ngay (không yêu cầu npm, Docker hoặc API key)

Yêu cầu: Python **3.10+** và trình duyệt hiện đại (Chrome/Edge/Firefox/Safari).

```bash
cd ai-studio-company
python3 backend/server.py
```

Mở: **http://127.0.0.1:8787**. Phiên bản có P3.6 yêu cầu đăng nhập. Sau khi khởi động lần đầu, tạo người dùng với `python tools/create_auth_user.py --user admin`. Dự án cũ cần cấp quyền rõ ràng bằng `python tools/manage_auth_membership.py --user admin --project <project-id> --role owner`; xem ID qua `python tools/manage_auth_membership.py --list-projects`. Không tự cấp quyền vào dữ liệu cũ. Chỉ chạy localhost.

Hoặc trên macOS/Linux:

```bash
chmod +x start.sh
./start.sh
```

Ứng dụng tự tạo database `company.sqlite` và một dự án mẫu về ứng dụng lưu tri thức. WebGL dựng mô hình 3D thật; nếu WebGL không khả dụng, ứng dụng tự vẽ mô hình 3D bằng phép chiếu trên Canvas2D, vẫn xoay và zoom được.

## 2. Các thao tác đang hoạt động

1. **Dự án mới:** nhập tên, mô tả ý tưởng và nền tảng.
2. **Văn phòng 3D:** kéo chuột để xoay, lăn chuột để zoom, click nhãn/phòng ban để chọn.
3. **Chạy 1 bước** hoặc **Chạy quy trình**: backend xử lý từng giai đoạn trên worker thread; trình duyệt tự cập nhật trạng thái.
4. **Hai agent mỗi phòng:** agent A và B *đều* tạo phương án **độc lập**, không xem bản của nhau ở vòng tạo nháp.
5. **Review chéo:** A đánh giá B, B đánh giá A; cần cả hai `APPROVE` và điểm từ 80/100. Nếu không đạt, giai đoạn chuyển `needs_revision` và dừng để người quản lý xem lại/chạy lại.
6. **Tổng hợp:** tạo artifact `final` sau khi cả hai chấp thuận.
7. **Human approval:** Security, DevOps và Marketing không tự vượt gate; nhấp **Phê duyệt giai đoạn** sau khi kiểm tra tài liệu. Phê duyệt ở đây là **phê duyệt kế hoạch**, không phải bấm phát hành thật.
8. **Kho tài liệu:** xem bản nháp độc lập và tài liệu hợp nhất, copy nội dung, lọc theo phòng ban.
9. **Trao đổi:** chọn agent A/B, nhấp **Trao đổi với agent** và gửi câu hỏi. Chat được lưu riêng theo agent và dự án.
10. **Lịch sử:** event log, reviews, artifacts, timestamps lưu trong SQLite. Có thể chạy nhiều dự án.

## 3. 12 phòng ban

| Thứ tự | Phòng ban | Deliverable |
|---|---|---|
| 1 | Product Owner (PO) | Vision, mục tiêu, roadmap, phạm vi MVP |
| 2 | Research | Market, competitor, giả thuyết người dùng |
| 3 | Business Analyst (BA) | User stories, acceptance criteria |
| 4 | Project Manager (PM) | Kế hoạch sprint, nguồn lực, risk register |
| 5 | UX / UI Design | UX flow, wireframe, design specification |
| 6 | Tech Lead | Architecture, API, ADR |
| 7 | Development | Kế hoạch triển khai, đặc tả module/code |
| 8 | Quality Assurance (QA) | Test strategy, quy trình chất lượng |
| 9 | Quality Control (QC) | Test cases, bug triage, release criteria |
| 10 | Security **[Human gate]** | Threat model, security review |
| 11 | DevOps / Release **[Human gate]** | CI/CD và checklist Store |
| 12 | Growth Marketing **[Human gate]** | ASO, launch & retention kế hoạch |

Mỗi phòng có `-A` (Creator) và `-B` (Reviewer), nhưng **cả hai** đều đưa ra bản đề xuất riêng ở vòng 1 rồi đổi vai trò ở vòng 2. `AI_MODEL_A` và `AI_MODEL_B` cho phép dùng hai model khác nhau để giảm thiên lệch chung.

## 4. Kết nối AI thật — Ollama chạy local

Cài Ollama (https://ollama.com) và tải một model chat có hỗ trợ endpoint OpenAI-compatible. Ví dụ:

```bash
ollama pull qwen3:8b
AI_PROVIDER=ollama AI_MODEL=qwen3:8b python3 backend/server.py
```

Khi Ollama chạy mặc định tại `http://127.0.0.1:11434`, backend gọi `http://127.0.0.1:11434/v1/chat/completions`.

Để dùng hai model riêng cho A và B:

```bash
AI_PROVIDER=ollama \
AI_MODEL_A=qwen3:8b \
AI_MODEL_B=gemma3:12b \
python3 backend/server.py
```

**Lưu ý:** cần tải cả hai model trước khi chạy và đủ RAM/GPU. Tốc độ tuỳ phần cứng. Không có phí API theo lượt gọi khi inference hoàn toàn local nhưng vẫn có chi phí máy/điện.

### Dùng OpenAI-compatible API khác

```bash
AI_PROVIDER=openai-compatible \
AI_BASE_URL=https://api.openai.com/v1 \
AI_API_KEY='YOUR_API_KEY' \
AI_MODEL='YOUR_AVAILABLE_MODEL' \
python3 backend/server.py
```

API key chỉ nằm ở backend (biến môi trường), không nhúng vào HTML/JavaScript. **ChatGPT Plus không bao gồm hạn mức thanh toán API riêng.**

Các biến môi trường:

| Biến | Mặc định | Mục đích |
|---|---|---|
| `AI_PROVIDER` | `demo` | `demo`, `ollama`, `openai-compatible` |
| `AI_BASE_URL` | `http://127.0.0.1:11434/v1` | Endpoint tương thích OpenAI |
| `AI_MODEL` | `qwen3:8b` | Model mặc định |
| `AI_MODEL_A` | `AI_MODEL` | Model cho agent A |
| `AI_MODEL_B` | `AI_MODEL` | Model cho agent B |
| `AI_API_KEY` | trống | Key cho API có xác thực |
| `AI_TIMEOUT` | `150` | Timeout mỗi yêu cầu AI (giây) |
| `AI_HOST` | `127.0.0.1` | Chỉ bind local (khuyến nghị) |
| `AI_PORT` | `8787` | Port máy chủ |
| `AI_COMPANY_DB` | `./company.sqlite` | Nơi lưu SQLite |

**An toàn:** Chỉ chạy tại `127.0.0.1` trong MVP; đã có xác thực và RBAC cơ bản nhưng chưa có TLS, bảo mật production, cách ly workspace hoàn chỉnh hay giám sát chi phí. Không bind public lên Internet khi chưa bổ sung các lớp bảo vệ.

### P4.1 — Cấu hình provider riêng cho hai agent

Xem [hướng dẫn cấu hình và probe](docs/RELEASE_NOTES_0.6_MODEL_PROVIDER.md). Các biến có hậu tố `_A` / `_B` cho phép chỉ định endpoint, provider, key và timeout riêng. `python tools/probe_models.py` kiểm tra cấu hình mà không gọi AI. Để thực sự kiểm tra hai model đã cấu hình, chạy `python tools/probe_models.py --execute --confirm 'PROBE REAL MODELS'`. Không đưa API key vào mã nguồn.

## 5. Kiến trúc & API

```text
Browser UI (HTML/CSS/JS)
├─ Native WebGL office (Canvas2D projected-3D fallback)
├─ 12-stage workflow board + status polling
├─ Independent agent chat + artifacts + activity log
└─ REST JSON API :8787
   ├─ Python ThreadingHTTPServer
   ├─ Project orchestrator (A draft → B draft → cross reviews → final)
   ├─ Provider adapter (demo / OpenAI-compatible)
   ├─ Human approval gates
   └─ SQLite (projects / tasks / artifacts / reviews / events / chat)
```

API gồm:

| Endpoint | Method | Công dụng |
|---|---|---|
| `/api/bootstrap` | GET | Cấu hình, danh sách nhân sự, dự án |
| `/api/projects` | POST | Khởi tạo dự án |
| `/api/projects/:id/state` | GET | Tasks, reviews, artifacts, trạng thái |
| `/api/projects/:id/run` | POST | `{ "mode": "next" \| "all" }` |
| `/api/projects/:id/pause` | POST | Yêu cầu dừng sau giai đoạn hiện tại |
| `/api/stages/:project/:stage/approve` | POST | Phê duyệt human gate |
| `/api/stages/:project/:stage/retry` | POST | Chạy lại giai đoạn không đạt |
| `/api/artifacts/:id` | GET | Nội dung document |
| `/api/chat?project_id=&agent_id=` | GET | Lịch sử chat |
| `/api/chat` | POST | `{project_id, agent_id, message}` |

Backend hiện dùng **worker thread** cho mỗi project và **SQLite local**. Với nhiều project đồng thời hoặc nhiều người dùng, nên thay bằng task queue và PostgreSQL trước khi triển khai production.

## 6. Test

```bash
python3 -m unittest discover -s tests -v
node --check web/world3d.js
node --check web/app.js
```

Tests xác nhận: đủ agent/phòng ban, hai bản độc lập, review A ↔ B, quality gate, phê duyệt, chat, chạy một giai đoạn và parse review fail-closed.

## 7. Cấu trúc

```text
ai-studio-company/
├── backend/
│   └── server.py          # REST server, database, orchestrator, LLM adapter
├── web/
│   ├── index.html         # 3D command center + modals
│   ├── styles.css         # responsive UI
│   ├── world3d.js         # Native WebGL / Canvas2D fallback
│   └── app.js             # project state, actions, chat, artifacts
├── tests/
│   └── test_workflow.py
├── docs/
│   └── PRODUCTION_ROADMAP.md
├── .gitignore
├── start.sh
└── README.md
```

### Tham khảo chính thức

- Ollama OpenAI compatibility: https://github.com/ollama/ollama/blob/main/docs/api/openai-compatibility.mdx
- Google Play Developer API: https://developer.android.com/google/play/developer-api
- Apple App Store Connect workflow: https://developer.apple.com/help/app-store-connect/get-started/app-store-connect-workflow/
- Apple upload builds: https://developer.apple.com/help/app-store-connect/manage-builds/upload-builds

## 8. GitHub Delivery dashboard (0.3)

The `docs/GITHUB_INTEGRATION.md` guide shows how to upload this project to GitHub, enable read-only GitHub Actions CI, protect `main`, and opt-in to exporting a real ORBIT agent artifact as a **draft PR** using `tools/github_pr.py`.

```bash
python3 tools/github_pr.py --repo OWNER/REPO --artifact-id ARTIFACT_ID
# Only when you intend to write to GitHub and have configured your local token:
python3 tools/github_pr.py --repo OWNER/REPO --artifact-id ARTIFACT_ID --apply
```

**Not live-connected:** Connecting GitHub to ChatGPT does not give the local app GitHub API credentials. This extension does not auto-run code agents, auto-merge or publish to stores.


## 9. v0.3 GitHub Delivery — `sathujt-coder/orbit-ai-studio`

The dashboard includes a **GitHub Delivery** section. To preview a document export, run a workflow stage with two independently generated drafts and both A↔B approvals, then select its latest `final` artifact. Preview requires no token and makes no GitHub changes.

To enable sending an optional **documentation-only draft PR**, set the following *on the local backend*, not in the browser:

```bash
export ORBIT_GITHUB_REPO=sathujt-coder/orbit-ai-studio
export ORBIT_GITHUB_WRITES=1
export GITHUB_TOKEN=...  # set privately; never commit or paste into chat
python3 backend/server.py
```

For exact publishing, access-scope, migration, safety and branch-protection instructions see [`docs/GITHUB_INTEGRATION.md`](docs/GITHUB_INTEGRATION.md). v0.3 records run IDs, review evidence, draft PR status and GitHub export history. It does **not** write runnable source, automatically merge, build Flutter, or publish to app stores.

No authenticated access to the user's remote GitHub repository is implied by this downloaded package.

## 10. v0.5 — AI Coding Factory (agent tạo code, review chéo)

Trong dashboard chọn **AI Coding Factory**. Gõ một feature/user story và chạy DEV-A + DEV-B:

- Tạo 2 đề xuất JSON có danh sách file *độc lập* (không trao bài cho nhau ở vòng viết code).
- DEV-A review code B và DEV-B review code A bằng mô hình đã chọn (hoặc bản review giả lập trong demo).
- Chỉ cho tải file ZIP `orbit-coding-*.zip` nếu đủ cả hai APPROVE và mỗi điểm >=80; kiểm tra đường dẫn/kích thước/hash mọi file.
- Lưu job, phương án, feedback, status, hashes vào SQLite, log event. Có thể xem job trên dashboard.
- **Không chạy mã được sinh**, không auto-merge, không push, không CI chứng minh. Muốn tích hợp code vào repository phải tự kiểm tra và copy từng file sau khi review thủ công.
- `AI_PROVIDER=demo` xuất **mã ví dụ có đánh dấu DEMO**. Chỉ `AI_PROVIDER=ollama` hoặc `openai-compatible` mới gọi LLM thực.
- Việc hai model đồng ý **không phải** bằng chứng code đúng, an toàn, hoặc được kiểm thử. Về sau nên thêm runner cô lập, test CI, vulnerability scanning và human approval trước PR code.
- `POST /api/coding/start` `{project_id, spec}` bắt đầu job; `GET /api/projects/:pid/coding` liệt kê, `GET /api/coding/:job` xem review, `GET /api/coding/:job/download` tải ZIP nếu PASS.

**GitHub Plugin trong ChatGPT khác với token GitHub dành cho backend ORBIT.** Không lưu token trong file repo hoặc gửi token qua chat.



## ORBIT v0.5 — Docker sandbox verification (opt-in)

Version 0.5 adds a **CLI-only**, explicit approval flow for independently executing tested Python/JavaScript coding proposals in restricted Docker containers, storing test evidence, and optionally creating a draft GitHub PR under `agent-proposals/`. It does not execute untrusted code on the host and never automatically merges/deploys. The dashboard remains read-only for execution evidence. Docker images must be digest-pinned, and Docker must be installed and configured separately. **No Docker-based execution has been performed as part of the CI unit tests.**

Read [v0.5 release notes](docs/RELEASE_NOTES_0.5.md) for prerequisites, exact opt-in commands, and security limitations.
