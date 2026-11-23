"""Quick release preflight for the ORBIT AI Studio source tree."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = (
    "backend/server.py",
    "backend/coding_factory.py",
    "backend/github_bridge.py",
    "web/app.js",
    "web/world3d.js",
    "web/index.html",
    "tests/test_coding_factory.py",
    ".github/workflows/orbit-ci.yml",
)
missing = [path for path in REQUIRED if not (ROOT / path).is_file()]
if missing:
    print("Missing source files:", *missing, sep="\n - ", file=sys.stderr)
    raise SystemExit(1)
print("ORBIT source preflight: required files present")
