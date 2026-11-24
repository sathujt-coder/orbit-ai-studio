# Web readiness gates
P2: read-only quality dashboard exposes latest evidence, lane checks, selection readiness and draft PR status. No authenticated selection or production approval.
P3: before staging require authenticated sessions, project-scoped roles, CSRF protection, audit trail, secret handling, and authorization tests. Existing localhost host/origin check is not authentication.
P4: configure two real model endpoints locally, generate independent proposals and reviews, verify trusted image, persist evidence, select and dry-run export. Never put credentials in GitHub source.
P5: require staging URL, owner UAT, security review, backup/restore, monitoring and rollback, production smoke and explicit Web signoff. Do not start mobile before signoff.
