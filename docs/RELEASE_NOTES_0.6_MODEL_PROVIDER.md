# P4.1: dual real-provider routing

Both lanes use the same production transport as the agent workflow. Configure common AI_PROVIDER, AI_BASE_URL, AI_MODEL and AI_API_KEY or independent AI_PROVIDER_A/B, AI_BASE_URL_A/B, AI_MODEL_A/B, AI_API_KEY_A/B, AI_TIMEOUT_A/B. API bases must end in /v1, HTTPS except loopback HTTP. No URL credentials, query or redirects; shared key inherited only by the same base URL. Credentials are server-side; bootstrap exposes only provider/model labels, not keys/URLs. No implicit provider probe, fallback to demo, or retry. Distinct model IDs are required for P4 operator preflight; two IDs alone do not prove independent models behind a router.

Local Ollama or a configured OpenAI-compatible gateway (including a compatible router) can be used. Set secrets through local shell/secret manager, never commit them. For different endpoints, explicitly set the respective lane keys. With both model IDs and provider configured, run:
    
    python tools/probe_models.py
    python tools/probe_models.py --execute --confirm 'PROBE REAL MODELS'

The first command makes no calls; the second sends two short neutral prompts, potentially incurring API charges. A valid response proves connectivity only. The probe reports whether each model returned the expected token. No raw model text or secrets in the report. No model calls run in standard CI; tests use two actual local HTTP fixture endpoints and test routing, key separation, redirect refusal and invalid configuration. Real inference remains unverified until operator executes against configured models.

For P4.2 use tools/run_real_models.py on an existing project, then sandbox, Tech Lead selection, and dry-run verified publication. See RELEASE_NOTES_0.6_OPERATIONS.md. Local-only; no production deployment or mobile.