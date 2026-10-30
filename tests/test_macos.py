import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from wirebrain import macos


class MacCaptureTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.calls=[]

    def network(self,*args):
        self.calls.append(args)
        if args[0]=='-listallnetworkservices':return 'An asterisk denotes a disabled service.\nWi-Fi\nUSB Ethernet\n*Disabled\n'
        if args[0] in ('-getwebproxy','-getsecurewebproxy'):
            return 'Enabled: No\nServer: previous.proxy\nPort: 3128\nAuthenticated Proxy Enabled: 0\n'
        if args[0]=='-getautoproxyurl':return 'URL: (null)\nEnabled: No\n'
        return ''

    @patch('wirebrain.macos.network')
    def test_all_enabled_services_restore_original_settings(self,network):
        network.side_effect=self.network
        macos.set_proxy(self.tmp.name,8082)
        backup=Path(self.tmp.name)/'proxy-backup.json'
        self.assertTrue(backup.exists())
        self.assertIn(('-setsecurewebproxy','USB Ethernet','127.0.0.1','8082'),self.calls)
        with self.assertRaises(ValueError):macos.set_proxy(self.tmp.name,8082)
        macos.reset_proxy(self.tmp.name)
        self.assertFalse(backup.exists())
        self.assertIn(('-setwebproxy','Wi-Fi','previous.proxy','3128'),self.calls)
        self.assertIn(('-setwebproxystate','Wi-Fi','off'),self.calls)

    @patch('wirebrain.macos.network')
    def test_authenticated_proxy_is_not_replaced(self,network):
        network.side_effect=lambda *args:self.network(*args).replace('Authenticated Proxy Enabled: 0','Authenticated Proxy Enabled: 1')
        with self.assertRaises(ValueError):macos.set_proxy(self.tmp.name,8082)
        self.assertFalse(any(call[0].startswith('-set') for call in self.calls))

    @patch('wirebrain.macos.network')
    def test_failed_restore_keeps_recovery_file(self,network):
        network.side_effect=self.network;macos.set_proxy(self.tmp.name,8082)
        network.side_effect=ValueError('Permission denied')
        with self.assertRaises(ValueError):macos.reset_proxy(self.tmp.name)
        self.assertTrue((Path(self.tmp.name)/'proxy-backup.json').exists())
