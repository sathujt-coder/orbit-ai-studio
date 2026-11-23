# ORBIT AI — Autonomous Software Studio

A multi-agent software development studio with a 3D office and independent cross-review.

## Repository status

This repository is being initialized. The `feat/orbit-v04-foundation` draft PR contains **GitHub Actions / project delivery scaffolding only**. The validated application v0.4 source bundle has **not yet been imported into this repository**.

See [GitHub delivery instructions](docs/GITHUB_DELIVERY.md) for the complete import procedure.

## Planned application

- 12 departments / 24 agents: PO, Research, BA, PM, Design, Tech Lead, Dev, QA, QC, Security, DevOps and Marketing.
- Two independent proposals per department and A ↔ B review.
- Human quality gates for sensitive release operations.
- 3D interactive office, project board, logs and agent conversations.
- Coding Factory that creates and reviews proposed source artifacts; sandboxed execution and automatic deployment are not yet included.

## Run the application (once the source bundle is imported)

```bash
python3 backend/server.py
```

Open http://127.0.0.1:8787.

```bash
python3 -m unittest discover -s tests -v
```

**Do not expose the local MVP server publicly.** Its API does not yet provide production-grade authentication or permission boundaries.
