"""The sample data the Godot smoke tests use must equal what the server really serves (regenerate the file when the catalogue changes)."""
import json
import os
import unittest

import goods_catalog


class ClientSampleTests(unittest.TestCase):
    def test_goods_catalog_sample_is_current(self):
        path = os.path.join(os.path.dirname(__file__), "..", "client", "tests", "goods_catalog_sample.json")
        with open(path, encoding="utf-8") as f:
            sample = json.load(f)
        self.assertEqual(sample, json.loads(json.dumps(goods_catalog.public_view())),
                         "client/tests/goods_catalog_sample.json is stale: regenerate it from goods_catalog.public_view()")


if __name__ == "__main__":
    unittest.main()
