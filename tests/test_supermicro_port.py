# SPDX-License-Identifier: GPL-2.0-only
"""CPU-only tests; never load modules, access PCI sysfs or install boot files."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PORT = ROOT / 'ports/supermicro-h13ssl'


class SupermicroPortTests(unittest.TestCase):
    def test_bme_transaction_and_fault_injection(self):
        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory) / 'test-bme'
            subprocess.run([os.environ.get('CC', 'cc'), '-std=c11', '-Wall', '-Wextra', '-Werror',
                            '-I', str(PORT), str(PORT / 'tests/test_bme_diag.c'), '-o', str(binary)], check=True)
            r = subprocess.run([str(binary)], check=True, capture_output=True, text=True)
            result = json.loads(r.stdout)
            self.assertEqual(result, {'cases': 21, 'pass': True, 'hardware_accesses': 0})

    def test_monitor_unknown_failure_and_notification_contract(self):
        subprocess.run([sys.executable, str(ROOT / 'monitoring/test_watch.py')], check=True)

    def test_dual_card_collector_and_success_proof(self):
        assets = Path(os.environ.get('GPU_UNLOCK_ASSETS', '/usr/lib/firmware/gpu-unlock/610.43.03'))
        if not (assets / 'gsp_ga10x.bin').is_file():
            self.skipTest('Generated pinned firmware is needed for the 42 fake-PCI checks')
        with tempfile.TemporaryDirectory() as directory:
            r = subprocess.run([sys.executable, str(PORT / 'tests/test_dual.py'), directory, str(assets)],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, (r.stdout + r.stderr)[-4000:])
            self.assertEqual(json.loads(r.stdout), {'checks': 42, 'pass': True})
