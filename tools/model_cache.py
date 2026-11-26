#!/usr/bin/env python3
"""Verify Ollama registry manifests and all referenced content-addressed blobs.

A cache is not a trust root: hashes verify consistency, not publisher identity.
Only the preparation phase may call ollama pull; verification never writes.
"""
import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path

DEFAULT_MODELS = ("qwen2.5-coder:3b", "qwen2.5:3b")
COMPONENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")
DIGEST = re.compile(r"sha256:([0-9a-f]{64})\Z")


class UnsafeStore(ValueError):
    pass


class InvalidModel(ValueError):
    pass


def checked(path, directory=False):
    """Reject links and nonregular objects, including ancestor components."""
    for parent in reversed(path.parents):
        try:
            mode = parent.lstat().st_mode
        except FileNotFoundError:
            continue
        if not stat.S_ISDIR(mode):
            raise UnsafeStore(f"unsafe directory: {parent}")
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return False
    if not (stat.S_ISDIR(mode) if directory else stat.S_ISREG(mode)):
        raise UnsafeStore(f"unsafe cache entry: {path}")
    return True


def check_store(root):
    if not checked(root, directory=True):
        return
    def fail(exc):
        raise exc
    for directory, dirs, files in os.walk(root, followlinks=False, onerror=fail):
        for name in dirs:
            checked(Path(directory) / name, directory=True)
        for name in files:
            path = Path(directory) / name
            checked(path)
            if path.lstat().st_nlink != 1:
                raise UnsafeStore(f"unexpected hard link: {path}")


def manifest_path(root, model):
    name, separator, tag = model.partition(":")
    components = name.split("/")
    if len(components) == 1:
        components.insert(0, "library")
    tag = tag if separator else "latest"
    if len(components) != 2 or not all(COMPONENT.fullmatch(x) for x in (*components, tag)):
        raise ValueError("only registry.ollama.ai model names with safe namespace/tag are supported")
    return root / "manifests" / "registry.ollama.ai" / components[0] / components[1] / tag


def hash_file(path):
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
            size += len(block)
    return digest.hexdigest(), size


def inspect_model(root, model, *, repair=False, memo=None):
    """Return evidence or raise. Repair removes only invalid target manifest/blobs."""
    if memo is None:
        memo = {}
    manifest = manifest_path(root, model)
    if not checked(manifest):
        raise InvalidModel("missing manifest")
    try:
        if manifest.stat().st_size > 1024 * 1024:
            raise InvalidModel("oversized manifest")
        raw = manifest.read_bytes()
        try:
            data = json.loads(raw)
        except (ValueError, UnicodeError) as exc:
            raise InvalidModel("malformed manifest") from exc
        if not isinstance(data, dict) or data.get("schemaVersion") != 2:
            raise InvalidModel("invalid manifest schema")
        layers = data.get("layers")
        if not isinstance(layers, list) or not layers:
            raise InvalidModel("missing layers")
        entries = [data.get("config"), *layers]
        verified = {}
        problems = []
        for entry in entries:
            if not isinstance(entry, dict):
                raise InvalidModel("invalid descriptor")
            digest = entry.get("digest")
            size = entry.get("size")
            if not isinstance(digest, str) or not DIGEST.fullmatch(digest) or type(size) is not int or size < 0:
                raise InvalidModel("invalid blob descriptor")
            blob = root / "blobs" / digest.replace(":", "-")
            if not checked(blob):
                problems.append("missing blob " + digest)
                continue
            if digest not in memo:
                memo[digest] = hash_file(blob)
            actual, actual_size = memo[digest]
            if actual != digest[7:]:
                problems.append("corrupt blob " + digest)
                if repair:
                    blob.unlink()
                    memo.pop(digest, None)
            elif actual_size != size:
                problems.append("descriptor size mismatch " + digest)
            else:
                verified[digest] = size
        if problems:
            raise InvalidModel("; ".join(problems))
        return {"model": model, "manifest_sha256": hashlib.sha256(raw).hexdigest(),
                "blobs": [{"digest": d, "size": n} for d, n in sorted(verified.items())]}
    except InvalidModel:
        if repair:
            manifest.unlink()
        raise


def verify(root, models):
    root = root.absolute()
    check_store(root)
    memo = {}
    return [inspect_model(root, model, memo=memo) for model in models]


def ensure(root, models, pull):
    root = root.absolute()
    check_store(root)
    # Validate all names before making changes.
    for model in models:
        manifest_path(root, model)
    downloaded = []
    memo = {}
    for model in models:
        try:
            inspect_model(root, model, memo=memo)
            print(f"MODEL CACHE HIT: {model}", flush=True)
            continue
        except InvalidModel as exc:
            print(f"MODEL CACHE MISS/INVALID: {model}: {exc}", flush=True)
        try:
            inspect_model(root, model, repair=True)
        except InvalidModel:
            pass
        pull(model)
        downloaded.append(model)
        # If a previously unreferenced corrupt blob was reused by Ollama,
        # remove only the identified invalid files and try once more.
        check_store(root)
        try:
            inspect_model(root, model, repair=True)
        except InvalidModel:
            pull(model)
            check_store(root)
            inspect_model(root, model)
        memo.clear()
    return verify(root, models), downloaded


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("verify", "ensure"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--models", nargs="+", default=DEFAULT_MODELS)
    parser.add_argument("--docker-container")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    report = {"schema": "orbit.model-cache.v1", "gate": "BLOCK",
              "downloaded_models": [], "models": []}
    try:
        if args.mode == "verify":
            report["models"] = verify(args.root, args.models)
            for model in args.models:
                print(f"MODEL CACHE HIT (SHA-256 verified): {model}", flush=True)
        else:
            prefix = ["docker", "exec", args.docker_container, "ollama"] if args.docker_container else ["ollama"]
            report["models"], report["downloaded_models"] = ensure(
                args.root, args.models, lambda model: subprocess.run([*prefix, "pull", model], check=True))
        report["gate"] = "PASS"
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        report["error"] = str(exc)
        report["repairable"] = isinstance(exc, InvalidModel)
        print(f"MODEL CACHE BLOCK: {exc}", file=sys.stderr)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return 0 if report["gate"] == "PASS" else (2 if report.get("repairable") else 3)


if __name__ == "__main__":
    raise SystemExit(main())
