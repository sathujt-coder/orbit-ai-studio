# v0.6 — Real Docker TypeScript smoke verification

This increment adds a GitHub Actions job that builds a TypeScript/TSX toolchain Docker image with fixed **package versions** at build time, then uses its immutable local image ID to run two independent handwritten candidate fixtures. At **runtime** the sandbox disables networking, runs as an unprivileged user, drops capabilities, uses read-only source/root filesystem, and limits CPU/memory/processes.

The job must show actual `tsc --noEmit` and `tsx --test` success for both DEV-A and DEV-B. Unlike the earlier mock tests, this exercises Docker.

**Security and completeness caveats:** The Dockerfile base image uses a mutable tag and the npm dependency tree is not locked by a committed lockfile. The local image ID is immutable after build but does not prove upstream dependency reproducibility. The CI fixtures are handwritten, **not AI-generated**, and React imports remain blocked. This is an infrastructure smoke test, not end-to-end Web Factory acceptance. Future work must pin base-image digest and transitive dependencies, support audited offline React builds, integrate TS evidence with PR exporter, and run a genuine model-backed Web job.
