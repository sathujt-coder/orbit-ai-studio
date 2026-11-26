import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from tools.model_cache import DEFAULT_MODELS, InvalidModel, UnsafeStore, ensure, manifest_path, verify


class ModelCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "models"
        self.calls = []

    def put(self, payload):
        digest = "sha256:" + hashlib.sha256(payload).hexdigest()
        path = self.root / "blobs" / digest.replace(":", "-")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        return {"digest": digest, "size": len(payload)}, path

    def populate(self, model):
        config, _ = self.put(b"config")
        layer, path = self.put(model.encode())
        manifest = manifest_path(self.root, model)
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(json.dumps({"schemaVersion": 2, "config": config, "layers": [layer]}))
        return path

    def pull(self, model):
        self.calls.append(model)
        self.populate(model)

    def test_cold_cache_then_warm_no_pull(self):
        evidence, downloads = ensure(self.root, DEFAULT_MODELS, self.pull)
        self.assertEqual(downloads, list(DEFAULT_MODELS))
        self.assertEqual(self.calls, list(DEFAULT_MODELS))
        self.assertEqual(len(evidence), 2)
        self.calls.clear()
        again, downloads = ensure(self.root, DEFAULT_MODELS, self.pull)
        self.assertEqual((again, downloads, self.calls), (evidence, [], []))

    def test_missing_blob_only_pulls_affected_model(self):
        a, b = DEFAULT_MODELS
        self.populate(a).unlink()
        self.populate(b)
        _, downloads = ensure(self.root, DEFAULT_MODELS, self.pull)
        self.assertEqual(downloads, [a])

    def test_same_length_corruption_repaired(self):
        a, b = DEFAULT_MODELS
        blob = self.populate(a)
        self.populate(b)
        blob.write_bytes(b"x" * len(a))
        with self.assertRaises(InvalidModel):
            verify(self.root, DEFAULT_MODELS)
        self.assertTrue(blob.exists())  # verify does not mutate
        _, downloads = ensure(self.root, DEFAULT_MODELS, self.pull)
        self.assertEqual(downloads, [a])
        self.assertEqual(blob.read_bytes(), a.encode())

    def test_malformed_manifest_repaired(self):
        model = DEFAULT_MODELS[0]
        self.populate(model)
        manifest_path(self.root, model).write_text("{bad")
        _, downloads = ensure(self.root, [model], self.pull)
        self.assertEqual(downloads, [model])

    def test_pull_success_without_valid_content_blocks(self):
        with self.assertRaises(InvalidModel):
            ensure(self.root, DEFAULT_MODELS, lambda model: None)

    def test_symlink_rejected_without_pull(self):
        model = DEFAULT_MODELS[0]
        blob = self.populate(model)
        target = self.root / "outside"
        target.write_bytes(blob.read_bytes())
        blob.unlink()
        blob.symlink_to(target)
        with self.assertRaises(UnsafeStore):
            ensure(self.root, [model], self.pull)
        self.assertEqual(self.calls, [])
        self.assertTrue(blob.is_symlink())

    def test_unreferenced_symlink_blocks_cold_cache_before_pull(self):
        self.root.mkdir()
        (self.root / "blobs").symlink_to(Path(self.temp.name))
        with self.assertRaises(UnsafeStore):
            ensure(self.root, DEFAULT_MODELS, self.pull)
        self.assertEqual(self.calls, [])

    def test_corrupt_unreferenced_blob_reused_once_then_repaired(self):
        model = DEFAULT_MODELS[0]
        blob = self.populate(model)
        manifest = manifest_path(self.root, model)
        raw = manifest.read_bytes()
        manifest.unlink()
        blob.write_bytes(b"corrupt")
        def pull(name):
            self.calls.append(name)
            if len(self.calls) == 1:
                manifest.write_bytes(raw)
            else:
                self.populate(name)
        _, downloads = ensure(self.root, [model], pull)
        self.assertEqual(downloads, [model])
        self.assertEqual(self.calls, [model, model])

    def test_unsafe_model_name_rejected_before_pull(self):
        with self.assertRaises(ValueError):
            ensure(self.root, [DEFAULT_MODELS[0], "../evil:tag"], self.pull)
        self.assertEqual(self.calls, [])

    def test_descriptor_size_mismatch_keeps_valid_blob(self):
        model = DEFAULT_MODELS[0]
        blob = self.populate(model)
        manifest = manifest_path(self.root, model)
        data = json.loads(manifest.read_text())
        data["layers"][0]["size"] += 1
        manifest.write_text(json.dumps(data))
        def pull(name):
            self.assertTrue(blob.exists())
            self.pull(name)
        _, downloads = ensure(self.root, [model], pull)
        self.assertEqual(downloads, [model])


if __name__ == "__main__":
    unittest.main()
