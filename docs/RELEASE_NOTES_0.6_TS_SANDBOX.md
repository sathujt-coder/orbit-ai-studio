# v0.6 Web sandbox — incremental TypeScript/TSX verification

The new `backend/web_typescript_sandbox.py` provides a separate, **opt-in** Docker-only adapter for TypeScript/TSX proposals. Both reviewed candidates must include `tsconfig.json` and `*.test.ts` or `*.test.tsx`; the adapter runs `tsc --noEmit` and `tsx --test` using a preloaded digest-pinned image containing both executables. Docker has no network, a read-only source mount and resource limits. The adapter never installs packages, executes generated code on the host, or publishes it.

**Current limitations:** React imports and dependency installation are intentionally blocked pending audited offline dependencies. This does **not** yet run real React builds or browser E2E of generated components. The adapter is standalone; its evidence is **not accepted by the legacy verified PR exporter**, and no actual Docker run has been performed in CI. Tests use a mock runner. Do not claim the Web Factory is end-to-end or production ready.

Next: integrate audited offline React toolchains, signed evidence and authenticated Tech Lead approval, then run real Docker tests and a real model-generated Web feature.
