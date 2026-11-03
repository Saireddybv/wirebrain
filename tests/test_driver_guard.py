import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from wirebrain import driver_guard


class DriverGuardTests(unittest.TestCase):
    def test_an_unowned_or_replaced_driver_is_never_stopped(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'driver.json'
            expected = Path(tmp)/'own.sys'
            with patch.object(driver_guard,'expected_image',return_value=expected), patch.object(driver_guard,'service_image',return_value=Path(tmp)/'other.sys'), patch.object(driver_guard,'helper_active',return_value=False), patch.object(driver_guard.subprocess,'run') as run:
                driver_guard.cleanup(path)
                path.write_text(json.dumps({'image':str(expected)}))
                with self.assertRaisesRegex(ValueError,'Another WinDivert'):
                    driver_guard.cleanup(path)
                run.assert_not_called()
                self.assertTrue(path.exists())

    def test_guard_retains_ownership_if_redirector_has_not_exited(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'driver.json'
            expected = Path(tmp)/'own.sys'
            path.write_text(json.dumps({'image':str(expected)}))
            with patch.object(driver_guard,'expected_image',return_value=expected), patch.object(driver_guard,'helper_active',return_value=True), patch.object(driver_guard.time,'sleep'), patch.object(driver_guard.subprocess,'run') as run:
                with self.assertRaisesRegex(ValueError,'Redirector still active'):
                    driver_guard.cleanup(path)
                self.assertTrue(path.exists())
                run.assert_not_called()
