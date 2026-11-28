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


MANIFEST = "application/vnd.docker.distribution.manifest.v2+json"
MANIFEST_LIST = "application/vnd.ollama.manifest.list.v2+json"
BLOB_NAME = re.compile(r"sha256-[0-9a-f]{64}\Z")


def v2_link(root, path):
    """Only exact relative named-manifest links to a direct local digest blob."""
    parts = path.relative_to(root).parts
    if (len(parts) != 5 or parts[:2] != ("manifests-v2", "ollama.com")
            or not all(COMPONENT.fullmatch(x) for x in parts[2:])):
        raise UnsafeStore(f"unexpected symlink: {path}")
    target = os.readlink(path)
    name = target.rsplit("/", 1)[-1]
    if not BLOB_NAME.fullmatch(name) or target != "../../../../blobs/" + name:
        raise UnsafeStore(f"unsafe manifest link: {path}")
    blob = root / "blobs" / name
    # Never resolve through another link, including the blobs directory.
    checked(blob)
    if blob.exists() and blob.lstat().st_nlink != 1:
        raise UnsafeStore(f"unexpected hard link: {blob}")
    return blob


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
            if path.is_symlink():
                v2_link(root, path)
                continue
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


def v2_path(root, model):
    return root / "manifests-v2" / "ollama.com" / Path(*manifest_path(root, model).relative_to(root).parts[2:])


def hash_file(path):
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
            size += len(block)
    return digest.hexdigest(), size


def inspect_model(root, model, *, repair=False, memo=None):
    """Check both layouts when present, including all manifest-list children."""
    if memo is None:
        memo = {}
    legacy, modern = manifest_path(root, model), v2_path(root, model)
    names = [p for p in (modern, legacy) if os.path.lexists(p)]
    if not names:
        raise InvalidModel("missing manifest")
    verified, manifests, problems = {}, [], []
    active = set()

    def blob(digest, size=None, manifest=False):
        if not isinstance(digest, str) or not DIGEST.fullmatch(digest):
            raise InvalidModel("invalid blob digest")
        path = root / "blobs" / digest.replace(":", "-")
        if not checked(path):
            raise InvalidModel("missing blob " + digest)
        if path.lstat().st_nlink != 1:
            raise UnsafeStore("hardlinked blob")
        if digest not in memo:
            memo[digest] = hash_file(path)
        actual, actual_size = memo[digest]
        if actual != digest[7:]:
            if repair:
                path.unlink()
                memo.pop(digest, None)
            raise InvalidModel("corrupt blob " + digest)
        if size is not None and actual_size != size:
            raise InvalidModel("descriptor size mismatch " + digest)
        verified[digest] = actual_size
        if manifest:
            if actual_size > 1024 * 1024:
                raise InvalidModel("oversized manifest blob")
            return path.read_bytes()

    def descriptor(entry, *, size_required=True):
        if not isinstance(entry, dict):
            raise InvalidModel("invalid descriptor")
        size = entry.get("size")
        if (size_required or "size" in entry) and (type(size) is not int or size < 0):
            raise InvalidModel("invalid blob descriptor size")
        return entry.get("digest"), size

    def parse(raw, depth=0):
        if depth > 8 or len(raw) > 1024 * 1024:
            raise InvalidModel("manifest recursion or size limit")
        key = hashlib.sha256(raw).hexdigest()
        if key in active:
            raise InvalidModel("manifest reference cycle")
        active.add(key)
        try:
            try:
                data = json.loads(raw)
            except (ValueError, UnicodeError) as exc:
                raise InvalidModel("malformed manifest") from exc
            if not isinstance(data, dict) or data.get("schemaVersion") != 2:
                raise InvalidModel("invalid manifest schema")
            walk(data, depth)
        finally:
            active.remove(key)

    def walk(data, depth):
        if depth > 8:
            raise InvalidModel("manifest recursion limit")
        media = data.get("mediaType")
        if media == MANIFEST_LIST:
            children = data.get("manifests")
            if not isinstance(children, list) or not 1 <= len(children) <= 64:
                raise InvalidModel("invalid manifest list")
            for child in children:
                if not isinstance(child, dict) or child.get("mediaType") != MANIFEST:
                    raise InvalidModel("invalid child manifest")
                if "digest" in child:
                    if child.get("config") or child.get("layers"):
                        raise InvalidModel("ambiguous manifest reference")
                    digest, size = descriptor(child, size_required=False)
                    parse(blob(digest, size, manifest=True), depth + 1)
                else:
                    if child.get("schemaVersion") != 2:
                        raise InvalidModel("invalid inline child manifest")
                    walk(child, depth + 1)
            return
        if media not in (None, MANIFEST):
            raise InvalidModel("unsupported manifest media type")
        layers = data.get("layers")
        if not isinstance(layers, list) or not layers:
            raise InvalidModel("missing layers")
        errors = []
        for entry in [data.get("config"), *layers]:
            try:
                digest, size = descriptor(entry)
                nested = entry.get("mediaType") in (MANIFEST, MANIFEST_LIST)
                raw = blob(digest, size, manifest=nested)
                if nested:
                    parse(raw, depth + 1)
            except InvalidModel as exc:
                errors.append(str(exc))
        if errors:
            raise InvalidModel("; ".join(errors))

    for name in names:
        try:
            if name.is_symlink():
                target = v2_link(root, name)
                digest = "sha256:" + target.name[7:]
                raw = blob(digest, manifest=True)
            else:
                if not checked(name) or name.stat().st_size > 1024 * 1024:
                    raise InvalidModel("missing or oversized manifest")
                raw = name.read_bytes()
            parse(raw)
            manifests.append({"layout": "v2" if name == modern else "legacy",
                "kind": "symlink" if name.is_symlink() else "file",
                "sha256": hashlib.sha256(raw).hexdigest(),
                **({"link_target": os.readlink(name)} if name.is_symlink() else {})})
        except InvalidModel as exc:
            problems.append(str(exc))
    if problems:
        if repair:
            for name in names:
                name.unlink()
        raise InvalidModel("; ".join(problems))
    return {"model": model, "manifest_sha256": manifests[0]["sha256"],
            "manifests": manifests,
            "blobs": [{"digest": d, "size": n} for d, n in sorted(verified.items())]}


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
