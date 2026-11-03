import tempfile
import unittest
from pathlib import Path

from wirebrain.desktop_trust import forget, remember


class EnrollmentTests(unittest.TestCase):
    def test_uninstall_removes_only_new_trust_and_unchanged_generated_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            certs = home/"certificates"
            certs.mkdir()
            prior = certs/"mitmproxy-dhparam.pem"
            prior.write_bytes(b"preexisting file")
            key = certs/"mitmproxy-ca.pem"
            key.write_bytes(b"fixture")
            remember(home,b"desktop root",{prior.name})
            roots = [b"other root",b"desktop root"]
            forget(home,lambda:roots,roots.remove)
            self.assertEqual(roots,[b"other root"])
            self.assertTrue(prior.exists())
            self.assertFalse(key.exists())
            forget(home,lambda:roots,roots.remove)
            self.assertEqual(roots,[b"other root"])

    def test_uninstall_without_enrollment_does_not_inspect_other_roots(self):
        with tempfile.TemporaryDirectory() as tmp:
            forget(Path(tmp),lambda:self.fail("uninstall read unrelated roots"),self.fail)
