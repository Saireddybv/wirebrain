import tempfile
import unittest
import os
from pathlib import Path
from unittest.mock import patch

from start_wirebrain import diary_home


class LauncherTests(unittest.TestCase):
    def test_upgrade_reuses_checkout_diary_and_explicit_home_takes_precedence(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict('os.environ'):
            os.environ.pop('WIREBRAIN_HOME',None)
            root=Path(directory)
            self.assertEqual(diary_home(root),(Path.home()/'.wirebrain').resolve())
            (root/'.wirebrain').mkdir()
            (root/'.wirebrain/memory.sqlite3').touch()
            self.assertEqual(diary_home(root),(root/'.wirebrain').resolve())
            with patch.dict('os.environ',{'WIREBRAIN_HOME':str(root/'chosen')}):
                self.assertEqual(diary_home(root),(root/'chosen').resolve())
            with patch.dict('os.environ',{'WIREBRAIN_HOME':''}):
                self.assertEqual(diary_home(root),(root/'.wirebrain').resolve())
