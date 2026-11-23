# ORBIT AI Studio — Web First, Mobile After Acceptance

## Decision
Complete a real, fully tested Web product using all 12 departments / 24 agents and independent A/B cross-review. Mobile is deferred until the Web product has passed UAT and received explicit written human acceptance.

## Release plan
### v0.6 — Web Development Factory
- Independent A/B implementation of frontend, backend, database, API, authentication and responsive UI.
- Tech Lead selects the implementation with traceable reviews and acceptance criteria.
- Extend sandbox adapters to HTML/CSS/TypeScript/TSX, web builds, lint, typecheck and test runners.
- QA unit/component, API integration, Playwright browser E2E, accessibility and security scans.
- Draft PRs with code, test evidence, review findings and human merge approval.

### v0.7 — Web QA, Staging & UAT
- Production-like staging, browser compatibility, responsive mobile-browser testing, accessibility and load tests.
- Security hardening: RBAC, authentication, rate limiting, secrets, audit, isolated execution.
- Bug triage, regression, disaster recovery and rollback drills.
- Human Product Owner / QA / Security / DevOps acceptance.

### v0.8 — Web Production & Growth
- Human-approved deployment with TLS, monitoring, backup, alerting, incident response.
- Web SEO, onboarding, analytics, retention and marketing after quality review.

### v0.9 — Mobile (blocked until Web acceptance)
- Only after written Web acceptance: Flutter discovery, UX adaptation, API reuse, Android/iOS builds and store publishing.

## Web acceptance checklist (all required)
- [ ] Requirements, user stories and acceptance criteria approved.
- [ ] Real web frontend, backend, persistence, security and permissions verified.
- [ ] Independent agent A/B reviews and Tech Lead decision documented.
- [ ] CI: lint, typecheck, unit, integration, E2E and build pass.
- [ ] No unresolved critical/high security issues.
- [ ] Accessibility, responsive and browser compatibility targets met.
- [ ] Staging UAT passed; release-blocking defects resolved.
- [ ] Backups, restore, monitoring and rollback tested.
- [ ] Production smoke tests and post-release monitoring complete.
- [ ] Explicit written human Web acceptance.

## Actual v0.5 limitations
Current v0.5 supports opt-in CLI Docker verification for Python/JavaScript only. CI uses mocked Docker tests. Web browser E2E, TypeScript/HTML verification, actual sandbox execution and production deployment are **not yet delivered**. CI green does not constitute UAT or product acceptance.
