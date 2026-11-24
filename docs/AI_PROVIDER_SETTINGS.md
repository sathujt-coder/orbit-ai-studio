# P4.7 — AI Provider Settings (Web)
Open /providers.html from the dashboard. The global settings API is disabled for ordinary users, including project owners. Deployment operator must explicitly designate existing accounts:
 
    export ORBIT_PROVIDER_ADMINS=orbit-admin
    export ORBIT_PROVIDER_ENDPOINTS='[{"provider":"openai-compatible","url":"https://your-approved-provider.example/v1","key_env":"ORBIT_PROVIDER_KEY_REMOTE"}]'
    # Set ORBIT_PROVIDER_KEY_REMOTE using your deployment secret manager, never commit it.

Local default endpoint is http://127.0.0.1:11434/v1. Startup AI_PROVIDER / AI_BASE_URL / lane credentials remain supported. Add other exact trusted endpoints at deployment, not from browser. URLs must pass existing HTTPS/loopback policy. Only administrator-controlled DNS names should be allowlisted; firewall/egress and DNS protections remain deployment responsibilities. Container loopback refers to the backend container, not the host. Existing private-network deployment does not automatically gain internet egress.
 
Select provider, exact URL and model per lane; demo cannot mix with real lanes and real models must have distinct IDs. Credentials are environment-only, bound to approved endpoints; no plaintext key in database or browser. Do not enter secrets in model IDs. Configuration metadata and revision persist in SQLite. Explicit confirmation, CSRF, operator allowlist, audit and revision checking protect writes. New pipeline, coding job and chat snapshot current settings; running tasks are not silently switched. Context window is Ollama-only; OpenAI-compatible providers control their own context. Structured responses keep strict temperature. Probe and listing use explicit consent, bounded requests and no project data; listing requires compatible /v1/models. Remote calls may incur charges. No automatic online fallback. No production approval or external deployment claimed.
