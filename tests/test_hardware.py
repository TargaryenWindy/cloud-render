import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import hardware
import windows_gpu


class HardwareTest(unittest.TestCase):
    def test_amd_and_nvidia_windows(self):
        inventory = {(0, 9): dict(name='RX 7600', vendor=0x1002, total=8<<30, used=None, load=None),
                     (0, 8): dict(name='RTX', vendor=0x10de, total=12<<30, used=None, load=None)}
        adapter = 'luid_0x00000000_0x00000009_phys_0'
        engines = [('pid_1_'+adapter+'_eng_3_engtype_Compute', 30),
                   ('pid_2_'+adapter+'_eng_3_engtype_Compute', 20),
                   ('pid_1_'+adapter+'_eng_0_engtype_3D', 10)]
        with patch.object(windows_gpu,'adapters',return_value=inventory), patch.object(windows_gpu,'counters',return_value=(engines,[(adapter,2<<30)])):
            self.assertEqual(windows_gpu.sample(skip_nvidia=True),
                             [dict(name='RX 7600', total=8<<30, used=2<<30, load=50)])

    def test_linux_amd_without_busy_counter(self):
        with tempfile.TemporaryDirectory() as temp:
            device = Path(temp)/'card0'/'device'
            device.mkdir(parents=True)
            (device/'vendor').write_text('0x1002')
            (device/'mem_info_vram_used').write_text('0')
            self.assertEqual(hardware.linux_cards(Path(temp)),
                             [dict(name='AMD card0', total=None, used=0, load=None)])
