import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from make_manifest_keypair import generate

class KeypairTests(unittest.TestCase):
    def test_outside_repo_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            repo = root / 'repo'
            repo.mkdir()
            with self.assertRaises(ValueError):
                generate(repo / 'keys', repo)
            pub = generate(root / 'offline', repo)
            self.assertIn(b'BEGIN PUBLIC KEY', pub.read_bytes())
            self.assertEqual((pub.parent / 'lunex-manifest-private.pem').stat().st_mode & 0o777, 0o600)
            with self.assertRaises(FileExistsError):
                generate(root / 'offline', repo)
