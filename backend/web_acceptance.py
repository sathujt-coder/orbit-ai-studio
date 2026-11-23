"""ORBIT v0.6: deterministic Web acceptance gate.

Evidence is recorded by humans/CI integrations, never inferred from AI reviews.
A complete checklist is NOT acceptance until an explicit named human signs off.
"""
from __future__ import annotations
from datetime import datetime, timezone
import hashlib
import json
import re

REQUIREMENTS = (
    "scope_approved",
    "web_frontend_backend",
    "independent_review",
    "unit_integration_e2e",
    "security_review",
    "accessibility_responsive",
    "staging_uat",
    "backup_restore",
    "monitoring_rollback",
    "production_smoke",
)
REF_PATTERN = re.compile(r"^(https://[^\s]{8,1024}|[A-Za-z0-9][A-Za-z0-9._:/#-]{7,255})$")
ACTOR_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9 ._@-]{2,99}$")
HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def evidence_digest(records):
    return hashlib.sha256(canonical(records).encode("utf-8")).hexdigest()


def new_register(project_id):
    if not isinstance(project_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{3,80}", project_id):
        raise ValueError("Invalid project ID")
    return {"schema": "orbit.web.acceptance.v1", "project_id": project_id,
            "evidence": {}, "signoff": None}


def record(register, requirement, *, reference, reviewer, passed):
    if requirement not in REQUIREMENTS:
        raise ValueError("Unknown Web acceptance requirement")
    if not isinstance(reference, str) or not REF_PATTERN.fullmatch(reference):
        raise ValueError("Concrete evidence reference required")
    if not isinstance(reviewer, str) or not ACTOR_PATTERN.fullmatch(reviewer):
        raise ValueError("Named reviewer required")
    if type(passed) is not bool:
        raise ValueError("Passed must be a boolean, not a truthy value")
    _check_register(register)
    updated = json.loads(canonical(register))
    updated["evidence"][requirement] = {
        "reference": reference, "reviewer": reviewer, "passed": passed,
        "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    # Any change invalidates an earlier signoff.
    updated["signoff"] = None
    return updated


def _check_register(register):
    if not isinstance(register, dict) or register.get("schema") != "orbit.web.acceptance.v1":
        raise ValueError("Unsupported register")
    project_id = register.get("project_id")
    if not isinstance(project_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{3,80}", project_id):
        raise ValueError("Invalid project ID")
    entries = register.get("evidence")
    if not isinstance(entries, dict) or set(entries) - set(REQUIREMENTS):
        raise ValueError("Invalid evidence")
    for key, entry in entries.items():
        if (not isinstance(entry, dict) or type(entry.get("passed")) is not bool
                or not isinstance(entry.get("reference"), str)
                or not REF_PATTERN.fullmatch(entry["reference"])
                or not isinstance(entry.get("reviewer"), str)
                or not ACTOR_PATTERN.fullmatch(entry["reviewer"])
                or not isinstance(entry.get("recorded_at"), str)):
            raise ValueError("Invalid evidence record: " + key)
    if register.get("signoff") is not None:
        s = register["signoff"]
        if (not isinstance(s, dict) or not isinstance(s.get("owner"), str)
                or not ACTOR_PATTERN.fullmatch(s["owner"])
                or not isinstance(s.get("approved_at"), str)
                or not isinstance(s.get("digest"), str)
                or not HASH_PATTERN.fullmatch(s["digest"])):
            raise ValueError("Invalid signoff")


def evaluate(register):
    _check_register(register)
    records = register["evidence"]
    missing = [key for key in REQUIREMENTS if key not in records]
    failed = [key for key in REQUIREMENTS if key in records and records[key]["passed"] is not True]
    complete = not missing and not failed
    signature = register.get("signoff")
    signed = bool(complete and signature and signature["digest"] == evidence_digest(records))
    return {"project_id": register["project_id"], "complete": complete,
            "accepted": signed, "missing": missing, "failed": failed,
            "mobile_unlocked": signed, "signoff_owner": signature["owner"] if signed else None,
            "notice": "Evidence references are assertions, not independent proof. Human review required."}


def signoff(register, *, owner, confirmation):
    state = evaluate(register)
    if not state["complete"]:
        raise PermissionError("All Web acceptance gates must pass before signoff")
    if not isinstance(owner, str) or not ACTOR_PATTERN.fullmatch(owner):
        raise ValueError("Named human owner required")
    expected = "ACCEPT WEB " + register["project_id"]
    if confirmation != expected:
        raise PermissionError("Explicit human confirmation required: " + expected)
    updated = json.loads(canonical(register))
    updated["signoff"] = {
        "owner": owner,
        "approved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "digest": evidence_digest(updated["evidence"]),
    }
    return updated
