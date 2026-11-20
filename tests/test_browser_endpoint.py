import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
import main as M


class BrowserOwnership(unittest.TestCase):
    def test_allocated_port_is_nonzero(self):
        port = M.allocate_debug_port()
        self.assertTrue(1024 <= port <= 65535)

    def test_only_expected_local_browser_endpoint_is_accepted(self):
        endpoint = 'ws://127.0.0.1:41234/devtools/browser/ab12-cd34'
        self.assertEqual(M.browser_endpoint_from_line('DevTools listening on ' + endpoint + '\n', 41234), endpoint)
        for line in ('DevTools listening on ' + endpoint.replace('41234', '41235'),
                     'DevTools listening on ' + endpoint.replace('127.0.0.1', 'example.org'),
                     'DevTools listening on ' + endpoint.replace('/browser/', '/page/'),
                     'random ' + endpoint):
            self.assertFalse(M.browser_endpoint_from_line(line, 41234))

    def test_port_collision_with_another_browser_is_rejected(self):
        expected = 'ws://127.0.0.1:41234/devtools/browser/own'
        with patch.object(M, 'cdp_json', return_value={'webSocketDebuggerUrl': expected}):
            self.assertTrue(M.browser_endpoint_matches(41234, expected))
        with patch.object(M, 'cdp_json', return_value={'webSocketDebuggerUrl': expected + '-other'}):
            self.assertFalse(M.browser_endpoint_matches(41234, expected))
        with patch.object(M, 'cdp_json', return_value=None):
            self.assertFalse(M.browser_endpoint_matches(41234, expected))

    def test_reuse_requires_owned_endpoint_not_only_open_port(self):
        api = M.Api()
        api._owns_chrome = True
        api._chrome_proc = Mock()
        api._chrome_proc.poll.return_value = None
        api._chrome_debug_ws = 'expected'
        try:
            with patch.object(M, 'CDP_PORT', 41234), patch.object(M, 'port_open', return_value=True), \
                    patch.object(M, 'browser_endpoint_matches', return_value=False), \
                    patch.object(M, 'chrome_candidates', return_value=[]):
                self.assertFalse(api.ensure_chrome())
        finally:
            api._owns_chrome = False
