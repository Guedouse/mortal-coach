import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch, Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
import main as M


class VerificationRecovery(unittest.TestCase):
    def test_failed_wait_is_resumable_and_preserves_browser(self):
        api = M.Api()
        def fail(*args, **kwargs):
            api._keep_chrome = True
            api._pending = {'tag': 'test', 'url': 'original'}
            raise M.ReportError('VERIFICATION_FAILED', 'failed')
        with patch.object(M, 'LIB_EXCLUSIVE', True), patch.object(api, '_submit', side_effect=fail), \
                patch.object(api, 'close_owned_chrome') as close:
            r = api._submit_guarded('original', 'auto', '4.1b', '')
        self.assertEqual(r['status'], 'verification_failed')
        self.assertTrue(r['resumable'])
        self.assertEqual(api._pending['url'], 'original')
        close.assert_not_called()
        self.assertFalse(api.busy)

    def test_retry_requires_pending_and_reuses_job_parameters(self):
        api = M.Api()
        self.assertFalse(api.retry_verification()['ok'])
        api._pending = {'url': 'original', 'fmt': 'log-url', 'model': '4.1c', 'seat': '2', 'tag': 'job'}
        api._owns_chrome = True
        api._chrome_proc = Mock()
        api._chrome_proc.poll.return_value = None
        with patch.object(M, 'CDP_PORT', 12345), patch.object(M, 'port_open', return_value=True), \
                patch.object(api, '_submit_guarded', return_value={'ok': True}) as run:
            api.retry_verification()
            run.assert_called_once_with('original', 'log-url', '4.1c', '2', tag='job',
                                        resume=True, reload_verification=True)
        api._owns_chrome = False

    def test_official_fallback_refuses_active_operation(self):
        api = M.Api()
        api._begin_op('analysis')
        try:
            with patch('webbrowser.open') as open_browser:
                self.assertFalse(api.open_official_review('https://tenhou.net/')['ok'])
                open_browser.assert_not_called()
        finally:
            api._end_op()

    def test_official_fallback_stops_pending_and_encodes_url(self):
        api = M.Api()
        api._pending = {'tag': 'job'}
        with patch('webbrowser.open', return_value=True) as open_browser:
            r = api.open_official_review('https://tenhou.net/0/?log=x&tw=2')
        self.assertTrue(r['ok'])
        self.assertFalse(api._pending)
        from urllib.parse import urlparse, parse_qs
        target = open_browser.call_args.args[0]
        self.assertEqual(parse_qs(urlparse(target).query)['url'], ['https://tenhou.net/0/?log=x&tw=2'])

    def test_failure_stage_not_wait(self):
        self.assertEqual(M.submit_stage_of('VERIFICATION_FAILED 600010'), 'VERIFICATION_FAILED')
        self.assertEqual(M.submit_stage_of('VERIFICATION_TIMEOUT 300'), 'AWAITING_VERIFICATION')

    def test_actual_submit_failure_output_keeps_original_job(self):
        api = M.Api()
        output = 'SCRIPT_BUILD 5\nVERIFICATION_FAILED 600010\nVERIFICATION_PENDING window_kept_open'
        with patch.object(M, 'env_problems', return_value=[]), \
                patch.object(api, 'ensure_chrome', return_value=True), \
                patch.object(api, '_run_submit_node', return_value=output), \
                patch.object(api, '_write_log'), patch.object(api, 'close_owned_chrome') as close:
            result = api._submit_guarded('https://tenhou.net/0/?log=test', 'log-url', '4.1c', '2', tag='same-job')
        self.assertEqual(result['status'], 'verification_failed')
        self.assertEqual(api._pending['tag'], 'same-job')
        self.assertEqual(api._pending['model'], '4.1c')
        self.assertEqual(api._pending['seat'], '2')
        self.assertIn('600010', result['msg'])
        close.assert_not_called()

    def test_reload_control_only_during_verification_wait(self):
        api = M.Api()
        api._node_proc = Mock()
        api._node_proc.poll.return_value = None
        for stage in ('SUBMITTING', 'SCORING', 'DOWNLOADING'):
            with patch.object(M, 'submit_state_get', return_value={'active': True, 'stage': stage}):
                self.assertFalse(api.request_verification_reload()['ok'])
        api._node_proc.stdin.write.assert_not_called()
        with patch.object(M, 'submit_state_get', return_value={'active': True, 'stage': 'AWAITING_VERIFICATION'}):
            self.assertTrue(api.request_verification_reload()['ok'])
        api._node_proc.stdin.write.assert_called_once_with('reload-verification\n')


if __name__ == '__main__':
    unittest.main()
