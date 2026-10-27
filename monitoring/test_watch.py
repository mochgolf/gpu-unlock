# SPDX-License-Identifier: GPL-2.0-only
"""State classification and login behavior: no GPU, root or real system writes."""
import copy
import contextlib
import io
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from types import SimpleNamespace

spec = importlib.util.spec_from_file_location('watch', Path(__file__).with_name('gpu_unlock_watch.py'))
w = importlib.util.module_from_spec(spec)
spec.loader.exec_module(w)


class WatchTests(unittest.TestCase):
    def setUp(self):
        self.c = json.loads(Path(__file__).with_name('config.example.json').read_text())
        c = self.c
        self.f = {key: c[key] for key in ['hostname', 'kernel', 'nvidia_version',
                                          'nvidia_srcversion', 'gpu_unlock_srcversion']}
        self.f.update(boot_id='11111111-1111-1111-1111-111111111111', nvidia_loaded=True,
                      unlock_loaded=True, targets=list(c['gpus']), cmdline=c['cmdline_token'],
                      receipt={'boot_id': '11111111-1111-1111-1111-111111111111',
                               'revision': c['revision'], 'mode': 'dual-production-v1', 'early-status': 'passed'},
                      receipt_checksums_ok=True,
                      register_receipt={'mode': 'post-unlock', 'policy_pass': True,
                                        'devices': [{'bdf': b, 'registers': c['registers'].copy()} for b in c['gpus']]},
                      gpus={b: {'uuid': u, 'driver': c['nvidia_version']} for b, u in c['gpus'].items()},
                      unlock_log='\n'.join('pci ' + b + ': gpu_unlock: unlocked' for b in c['gpus']),
                      journal=c['journal_marker'] + '\nNVRM: loading NVIDIA UNIX Open Kernel Module',
                      grub={'saved_entry': c['default_entry']}, grub_uses_saved_entry=True, grub_has_entry=True,
                      boot_file_hashes={p: True for p in c['boot_file_hashes']}, collection_errors=[])

    def result(self):
        return w.evaluate(self.c, self.f)

    def test_current_success_is_quiet_on_login(self):
        r = self.result()
        self.assertEqual(r['state'], 'ok')
        self.assertEqual(w.notify_text(r), '')

    def test_old_boot_receipt_never_qualifies(self):
        self.f['receipt']['boot_id'] = '00000000-0000-0000-0000-000000000000'
        self.assertFalse(self.result()['current_boot_confirmed'])

    def test_loaded_module_without_both_success_records_is_not_success(self):
        self.f['unlock_log'] = ''
        self.assertEqual(self.result()['state'], 'unconfirmed')

    def test_each_card_register_override_must_be_present(self):
        for index in range(2):
            facts = copy.deepcopy(self.f)
            facts['register_receipt']['devices'][index]['registers']['ss0'] = 0x44023025
            self.assertFalse(w.evaluate(self.c, facts)['current_boot_confirmed'])

    def test_one_card_is_insufficient(self):
        self.f['register_receipt']['devices'].pop()
        self.assertFalse(self.result()['current_boot_confirmed'])

    def test_missing_module_warns(self):
        self.f['unlock_loaded'] = False
        self.assertIn('解锁模块未加载', w.notify_text(self.result()))

    def test_version_changes_warn(self):
        for key in ['kernel', 'nvidia_version', 'nvidia_srcversion', 'gpu_unlock_srcversion']:
            facts = {**self.f, key: 'different'}
            self.assertFalse(w.evaluate(self.c, facts)['current_boot_confirmed'])

    def test_unknown_evidence_warns_instead_of_passing(self):
        self.f['collection_errors'] = ['cannot read receipt']
        self.assertEqual(self.result()['state'], 'unconfirmed')

    def test_fallback_receipt_does_not_pass(self):
        self.f['receipt']['early-status'] = 'fallback'
        self.assertFalse(self.result()['current_boot_confirmed'])

    def test_checksum_failure_warns(self):
        self.f['receipt_checksums_ok'] = False
        self.assertFalse(self.result()['current_boot_confirmed'])

    def test_wrong_default_is_next_boot_warning_not_false_current_failure(self):
        self.f['grub']['saved_entry'] = 'gpu-unlock-a-34-original'
        r = self.result()
        self.assertTrue(r['current_boot_confirmed'])
        self.assertEqual(r['state'], 'warning')
        self.assertIn('下次', w.notify_text(r))

    def test_one_shot_safe_entry_warns(self):
        self.f['grub']['next_entry'] = 'gpu-unlock-a-34-original'
        self.assertEqual(self.result()['state'], 'warning')

    def test_boot_image_change_warns(self):
        self.f['boot_file_hashes'][next(iter(self.c['boot_file_hashes']))] = False
        self.assertEqual(self.result()['state'], 'warning')

    def test_gpu_identity_change_warns(self):
        self.f['gpus'][next(iter(self.c['gpus']))]['uuid'] = 'GPU-foreign'
        self.assertFalse(self.result()['current_boot_confirmed'])

    def test_xid_warns_but_known_profiler_query_assertion_is_not_false_unlock_failure(self):
        self.f['journal'] += '\nNVRM: nvAssertFailedNoLog: pStaticInfo->pSmIssueThrottleCtrl != NULL'
        self.assertEqual(self.result()['state'], 'ok')
        self.f['journal'] += '\nNVRM: Xid (PCI:0000:01:00): 79'
        self.assertFalse(self.result()['current_boot_confirmed'])

    def test_driver_reload_requires_reverification(self):
        self.f['journal'] += '\nNVRM: loading NVIDIA UNIX Open Kernel Module'
        self.assertFalse(self.result()['current_boot_confirmed'])

    def test_warning_has_action_without_repair(self):
        self.f['unlock_loaded'] = False
        text = w.notify_text(self.result())
        self.assertIn('WARNING', text)
        self.assertIn('gpu-unlock-status', text)
        self.assertNotIn('modprobe ', text)
        self.assertNotIn('reboot ', text)

    def test_failed_notification_returns_success_so_login_is_not_denied(self):
        self.f['unlock_loaded'] = False
        noop_signal = SimpleNamespace(SIGALRM=14, signal=lambda *_: None, alarm=lambda *_: None)
        with patch.object(w, 'CONFIG', Path(__file__).with_name('config.example.json')), \
                patch.object(w, 'trusted'), patch.object(w, 'collect', return_value=self.f), \
                patch.object(w, 'save'), patch.object(w, 'signal', noop_signal), \
                patch.object(w.os, 'geteuid', return_value=0, create=True):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = w.main(['--notify'])
            self.assertEqual(code, 0)
            self.assertIn('WARNING', output.getvalue())

    def test_failed_explicit_check_returns_nonzero_for_automation(self):
        self.f['unlock_loaded'] = False
        noop_signal = SimpleNamespace(SIGALRM=14, signal=lambda *_: None, alarm=lambda *_: None)
        with patch.object(w, 'CONFIG', Path(__file__).with_name('config.example.json')), \
                patch.object(w, 'trusted'), patch.object(w, 'collect', return_value=self.f), \
                patch.object(w, 'save'), patch.object(w, 'signal', noop_signal), \
                patch.object(w.os, 'geteuid', return_value=0, create=True):
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(w.main(['--json']), 1)


if __name__ == '__main__':
    unittest.main()
