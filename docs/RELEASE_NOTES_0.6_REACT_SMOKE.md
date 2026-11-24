# React offline smoke — v0.6
Two handwritten TSX components are bundled using esbuild and rendered with React DOM server in separate restricted Docker containers. A trusted test asserts the same heading for both implementations. CI resolves a dependency lock, audits high/critical vulnerabilities, retains the lock as an artifact, and builds using npm ci. Runtime uses an immutable local image ID, no network, read-only mounts and nonroot user.

Limitations: lock is generated per CI run, not yet committed; base image is not digest-pinned. This is server-side rendering, not browser interaction or full TypeScript checking. No generated AI code is executed by this CI job. The React smoke is separate from the existing proposal verifier and exporter. No production approval or mobile work.
