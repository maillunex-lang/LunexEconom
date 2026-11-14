import tempfile
import unittest
from pathlib import Path
from deploy import check_web

class DeployChecks(unittest.TestCase):
    def test_missing_markers_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)
            for name in ("index.html","style.css","app.js"):
                (p/name).write_text("x",encoding="utf-8")
            with self.assertRaises(ValueError):
                check_web(p)

if __name__=="__main__":
    unittest.main()
