"""Regression checks for portable-runtime entry points. No system task writes."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class PortableRuntimePaths(unittest.TestCase):
    def test_sync_entry_points_prefer_portable_runtime(self):
        for name in ('一键同步数据.bat', '重新登录.bat', '抓取诊断.bat'):
            with self.subTest(name=name):
                text = (ROOT/name).read_text(encoding='utf-8')
                portable = text.index('runtime\\python\\python.exe')
                development = text.index('.venv\\Scripts\\python.exe')
                self.assertLess(portable, development)

    def test_digest_entry_point_supports_portable_runtime(self):
        text = (ROOT/'立刻提醒我.bat').read_text(encoding='utf-8')
        self.assertLess(text.index('runtime\\python\\python.exe'), text.index('.venv\\Scripts\\python.exe'))

    def test_task_scripts_prefer_portable_pythonw(self):
        for name in ('register_task.ps1', 'register_digest.ps1'):
            with self.subTest(name=name):
                text = (ROOT/'sync'/name).read_text(encoding='utf-8')
                self.assertLess(text.index('runtime\\python\\pythonw.exe'), text.index('.venv\\Scripts\\pythonw.exe'))

    def test_default_onboarding_does_not_claim_tasks_already_enabled(self):
        text = (ROOT/'src/js/07-onboard.js').read_text(encoding='utf-8')
        self.assertIn('同步与提醒', text)
        self.assertIn('提醒需要单独配置', text)


if __name__ == '__main__':
    unittest.main()
