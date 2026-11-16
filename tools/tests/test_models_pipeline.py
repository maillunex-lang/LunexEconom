"""Regression tests for the deterministic standard-library model pipeline."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from tools.models import generate_models as generator
from tools.models import validate_models as validator


class ModelPipelineTests(unittest.TestCase):
    def test_catalog_count_and_unique_ids(self):
        entries = generator.catalog()
        self.assertEqual(len(entries), 64)
        self.assertEqual(sum(e["family"] == "buildings" for e in entries), 42)
        self.assertEqual(sum(e["family"] == "city" for e in entries), 22)
        self.assertEqual(len({(e["family"], e["id"]) for e in entries}), 64)

    def test_validate_all_geometry_structure_and_hashes(self):
        validated = validator.validate()
        self.assertEqual(len(validated), 64)

    def test_deterministic_binary_output(self):
        manifest = json.loads((generator.DEST / "manifest.json").read_text())
        for e in generator.catalog():
            path = f'{e["family"]}/{e["id"]}.glb'
            content = generator.Model(e).build().encode()
            self.assertEqual(hashlib.sha256(content).hexdigest(),
                             manifest["models"][path]["sha256"], path)

    def test_manifests_and_model_dimensions(self):
        manifest = json.loads((generator.DEST / "manifest.json").read_text())
        self.assertEqual(len(manifest["models"]), 64)
        for e in generator.catalog():
            record = manifest["models"][f'{e["family"]}/{e["id"]}.glb']
            self.assertEqual(record["width"], e["width"])
            self.assertEqual(record["height"], e["height"])
            self.assertLessEqual(record["bytes"], 81920)
            self.assertLessEqual(record["triangles"], 400)

    def test_corrupted_model_rejected(self):
        e = generator.catalog()[0]
        rel = f'{e["family"]}/{e["id"]}.glb'
        record = json.loads((generator.DEST/"manifest.json").read_text())["models"][rel]
        budgets = json.loads(validator.BUDGETS.read_text())["render"]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.glb"
            data = bytearray(generator.Model(e).build().encode())
            data[-10] ^= 1
            path.write_bytes(data)
            with self.assertRaises(AssertionError):
                validator.validate_one(path, e, record, budgets)


if __name__ == "__main__":
    unittest.main()
