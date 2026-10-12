import importlib.util
from pathlib import Path
import unittest

path = Path(__file__).resolve().parents[1]/'tools'/'audit_publication.py'
spec = importlib.util.spec_from_file_location('publication_audit', path)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


class PublicationGuardTests(unittest.TestCase):
    def test_empty_template_is_safe(self):
        self.assertTrue(audit.is_clean_payload('{"syncedAt":"","note":"","courses":[],"messages":[],"todos":[]}'))

    def test_nonempty_snapshot_is_rejected(self):
        self.assertFalse(audit.is_clean_payload('{"messages":[{"title":"private notice"}]}'))

    def test_unknown_or_invalid_payload_is_rejected(self):
        self.assertFalse(audit.is_clean_payload('{"token":""}'))
        self.assertFalse(audit.is_clean_payload('invalid json'))


if __name__ == '__main__':
    unittest.main()
