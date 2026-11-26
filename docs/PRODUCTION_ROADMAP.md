# ORBIT AI — Roadmap từ MVP đến công ty phần mềm AI vận hành thực

## Ranh giới giữa công cụ mô phỏng và tác nhân thi hành

MVP hiện vận hành engine điều phối real LLM và lưu tài liệu khi cấu hình Ollama/OpenAI-compatible. Các agent chưa tự chạy test, tự tạo/push mã nguồn, chạy flutter build, ký binary, gửi Store hay mua quảng cáo. Review AI không thay thế kiểm toán độc lập. Một bản được model đánh dấu `APPROVE` **không phải** bằng chứng rằng sản phẩm không có bug hay đã đạt security review.

## 1. Mức độ 1 — Engineering workspace thực

Thêm project workspace có repo Git riêng, phân quyền tools theo role, container sandbox cách ly, timeout, giới hạn CPU/RAM/network, kiểm duyệt shell command, output size quota, prompt injection defense cho tài liệu không tin cậy. Agent DEV-A tạo branch + PR; DEV-B clone PR base riêng, chạy static analysis + tests, gửi review bằng GitHub API. Quy tắc: chỉ merge sau test green + review + ký duyệt owner.

Thiết kế state: `idea → discovery → prd → specification → design → technical_design → work_items → coding → pr_review → ci → qa → qc → security → staging → human_release_approval → store_submission → store_review → live → acquisition → iterate`.

## 2. Mức độ 2 — Kết hợp thực thi và phản biện đa lớp

- `Create`: A và B tạo hai phương án trên context snapshot độc lập.
- `Critique`: A review B, B review A, không self-review.
- `Evidence`: linter, build, tests, SAST, dependency audits, browser/device test, screenshots, perf thresholds, traces. Kết quả tự động có độ tin cậy cao hơn LLM tự chấm.
- `Rework`: nếu fail, tạo defect và vòng sửa, retry tối đa (ví dụ 3) trước khi escalate.
- `Human approval`: yêu cầu người có thẩm quyền duyệt chi phí/PR merge/secrets/deploy/Store/ads.

Giới hạn và cảnh báo: token budget/project, SLA bước, rate limit, max retries, cancellation, phân loại dữ liệu nhạy cảm, audit log bất biến.

## 3. Mức độ 3 — Mobile release thực

**Android / Flutter**: Gradle + `flutter test`, `flutter build appbundle`, signing trong CI secrets, upload AAB tới Google Play Developer Publishing API/Play Console (có credential, app, policies, track, review theo quy định). Phải kiểm tra target API và chính sách hiện hành trước khi submit.

**iOS**: runner macOS + Xcode, provisioning, signing, archive/build, upload bằng Xcode/Transporter, App Store Connect API cho quản lý build/TestFlight/review. Không gắn API key hay private certificate vào LLM context.

Release sẽ luôn đi qua hai lớp phê duyệt: `technical signoff` và `owner confirm`; phản hồi từ Store là một trạng thái bất đồng bộ có thể được theo dõi bằng worker riêng.

## 4. Mức độ 4 — Product growth thực

Kết nối Analytics, Crashlytics/Sentry, attribution, review monitoring, ASO keyword research, CRM/email automation, content calendar, A/B experiments. Agent Marketing-A đề xuất giả thuyết + creative; B đánh giá brand safety, bằng chứng và rủi ro; campaign chỉ được phát sau budget gate, không tự chi tiền.

KPI gợi ý: Activation, D1/D7/D30 retention, crash-free sessions, conversion, paid CAC, organic acquisition, lead-to-user conversion, churn, LTV. Feedback loop sang PO/BA: bằng chứng người dùng → backlog → release tiếp theo.

## 5. Mức độ 5 — SaaS nhiều công ty / nhiều người

- Frontend: React + react-three-fiber/Three.js nếu cần scale giao diện.
- Backend: FastAPI/NestJS, PostgreSQL, Redis, Temporal/queue, workers.
- Workflow: versioned graph, resumable jobs, typed approvals, tool registry, model routing, cost reporting.
- Authn/authz: SSO + RBAC, tenant isolation, encrypted secrets, audit trails.
- Observability: OpenTelemetry, traces per job/agent, cost analytics, human intervention dashboard.
- Validation: deterministic CI, scorecards, benchmark tasks, canary releases.

**Đề xuất thứ tự nâng cấp:** GitHub PR + sandbox + CI thực → QA/QC tự động → security → Flutter build → Store workflows → Growth loop. Không nên mở auto-release hay auto-spend khi bộ kiểm soát chất lượng chưa có bằng chứng thực thi.


## P6.2j.1 — Development sequencing and production boundary
The [Planning readiness checkpoint](PROJECT_PLANNING.md#p62j1--system-completion--model-readiness-separation) records historical System PASS, Model BLOCK and Production BLOCK separately. P6.3 and later workflow development may proceed after system acceptance without model optimization. This is not permission to merge a draft, execute rejected planning candidates, adopt automatically, deploy or release. All existing technical and owner sign-off requirements, real AI acceptance and model qualification remain mandatory for applicable production readiness. Revalidate evidence against the intended release candidate and configured models.

## SG.7 — Studio readiness boundary
See [Studio Generator final acceptance](STUDIO_GENERATOR.md#sg7--final-studio-acceptance-pending-current-ci) and [historical evidence](studio-readiness-baseline.json). Current SG.7 System PASS permits P6.3 development only under P6.2j.1. No draft merge, production release, automatic adoption or execution authorization. Real AI and model qualification, actual bound sandbox execution, dependency completion and applicable release gates remain separate; synthetic QA fixture evidence is not production verification.

## P6.3 — Engineering Execution & Dependency Orchestration (development only)
SG.7 baseline b9f6cf6, CI 45740316572, artifact 15081340751: System PASS 418 Python, 22 general Browser/JS, 3 planning Chromium, 11 jobs. Model/release gates unchanged.

| Phase | Scope |
|---|---|
| P6.3a | Versioned engineering execution contract, graph binding, explicit approval |
| P6.3b | Dependency completion evidence |
| P6.3c | Dependency-aware queue |
| P6.3d | Bound retry and recovery |
| P6.3e | Isolated project Git workspace |
| P6.3f | Tech Lead candidate selection binding |
| P6.3g | Real sandbox workflow integration |
| P6.3h | GitHub draft PR integration |
| P6.3i | Engineering quality and defect tracking |
| P6.3j | Engineering workflow acceptance |

P6.3a adds an advisory immutable application contract and approve-role confirmation, bound to current adopted WBS, exact package binding, adopted graph and independently checked topology. Only dependency-free implementation roots are structurally eligible; dependent/verify packages remain blocked. No new execution path, no requirement on existing SG.6 coding submission, no queue or model changes. Confirmation is API-only; Studio exposes read-only projection. Subsequent phases must explicitly integrate contracts before enabling new execution paths. No production or merge authorization.
