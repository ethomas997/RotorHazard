'''python -m unittest discover'''
import hashlib
import io
import json
import os
import sys
import unittest
import zipfile
from unittest import mock

sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))),
                             'server', 'util'))

import esp32flasher  #pylint: disable=import-error
import SerialPortInfo  #pylint: disable=import-error

PART_DATA = {
    'esp32c5/bootloader.bin': b'\x01' * 100,
    'esp32c5/partitions.bin': b'\x02' * 50,
    'esp32c5/firmware.bin': b'\x03' * 300,
}
PART_OFFSETS = {
    'esp32c5/bootloader.bin': 0x2000,
    'esp32c5/partitions.bin': 0x8000,
    'esp32c5/firmware.bin': 0x10000,
}


def make_manifest(chip_family='ESP32-C5', parts=None):
    if parts is None:
        parts = [{'path': path, 'offset': PART_OFFSETS[path], 'size': len(data),
                  'sha256': hashlib.sha256(data).hexdigest()} for path, data in PART_DATA.items()]
    return {'name': 'Widscan58', 'version': 'a9fff97', 'date': '2026-11-14T15:49:21-05:00',
            'builds': [{'chipFamily': chip_family, 'parts': parts}]}


def make_zip(manifest=None, files=None):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as zip_obj:
        if manifest is not None:
            zip_obj.writestr('manifest.json', json.dumps(manifest))
        for path, data in (PART_DATA if files is None else files).items():
            zip_obj.writestr(path, data)
    return buf.getvalue()


class Esp32FlasherTest(unittest.TestCase):
    def test_is_fw_package_src(self):
        self.assertTrue(esp32flasher.is_fw_package_src('firmware/widscan58_esp32c5.zip'))
        self.assertTrue(esp32flasher.is_fw_package_src(' https://example.com/FW.ZIP '))
        self.assertFalse(esp32flasher.is_fw_package_src('firmware/RH_S32_BPill_node.bin'))
        self.assertFalse(esp32flasher.is_fw_package_src(''))
        self.assertFalse(esp32flasher.is_fw_package_src(None))

    def test_parse_package(self):
        package = esp32flasher.parse_package(make_zip(make_manifest()))
        self.assertEqual(package.name, 'Widscan58')
        self.assertEqual(package.version, 'a9fff97')
        self.assertEqual(package.chip_family, 'ESP32-C5')
        self.assertEqual(package.chip_arg(), 'esp32c5')
        self.assertEqual([(p[0], p[1]) for p in package.parts],
                         [(0x2000, 'esp32c5/bootloader.bin'), (0x8000, 'esp32c5/partitions.bin'),
                          (0x10000, 'esp32c5/firmware.bin')])
        self.assertEqual(package.total_size(), 450)
        self.assertIn('a9fff97', package.summary_str())

    def test_parse_package_errors(self):
        with self.assertRaisesRegex(RuntimeError, 'not a valid'):
            esp32flasher.parse_package(b'not a zip file')
        with self.assertRaisesRegex(RuntimeError, 'manifest.json'):
            esp32flasher.parse_package(make_zip(None))
        with self.assertRaisesRegex(RuntimeError, 'not found'):
            esp32flasher.parse_package(make_zip(make_manifest(), files={}))
        bad_sha = make_manifest()
        bad_sha['builds'][0]['parts'][2]['sha256'] = '0' * 64
        with self.assertRaisesRegex(RuntimeError, 'SHA-256'):
            esp32flasher.parse_package(make_zip(bad_sha))
        bad_size = make_manifest()
        bad_size['builds'][0]['parts'][0]['size'] = 1
        with self.assertRaisesRegex(RuntimeError, 'Size'):
            esp32flasher.parse_package(make_zip(bad_size))
        with self.assertRaisesRegex(RuntimeError, 'Unsupported'):
            esp32flasher.parse_package(make_zip(make_manifest(chip_family='STM32')))
        with self.assertRaisesRegex(RuntimeError, 'No parts'):
            esp32flasher.parse_package(make_zip(make_manifest(parts=[])))
        with self.assertRaisesRegex(RuntimeError, 'No matching build'):
            esp32flasher.parse_package(make_zip(make_manifest()), chip_family='ESP32-S3')

    def test_esptool_needs_install(self):
        with mock.patch.object(esp32flasher, 'get_esptool_version', return_value=None):
            self.assertTrue(esp32flasher.esptool_needs_install())
        with mock.patch.object(esp32flasher, 'get_esptool_version', return_value='4.7.0'):
            self.assertTrue(esp32flasher.esptool_needs_install())
        with mock.patch.object(esp32flasher, 'get_esptool_version', return_value='4.8.1'):
            self.assertFalse(esp32flasher.esptool_needs_install())
        with mock.patch.object(esp32flasher, 'get_esptool_version', return_value='5.7.0'):
            self.assertFalse(esp32flasher.esptool_needs_install())

    def test_installed_package_constraints(self):
        class FakeDist:
            def __init__(self, name, version):
                self.metadata = {'Name': name}
                self.version = version
        dists = [FakeDist('cffi', '1.17.1'), FakeDist('esptool', '4.0'), FakeDist('Rich_Click', '1.9.9'),
                 FakeDist('rich-click', '1.0'), FakeDist(None, '1.0')]
        with mock.patch('importlib.metadata.distributions', return_value=dists):
            self.assertEqual(esp32flasher.installed_package_constraints(),
                             ['cffi==1.17.1', 'Rich_Click==1.9.9'])

    def test_is_espressif_usb_port(self):
        class FakePortInfo:
            def __init__(self, device, vid):
                self.device = device
                self.vid = vid
        port_infos = [FakePortInfo('COM5', 0x10C4), FakePortInfo('COM10', 0x303A), FakePortInfo('COM11', None)]
        with mock.patch.object(SerialPortInfo, '_comports', return_value=port_infos), \
                mock.patch.object(SerialPortInfo, '_norm_key', side_effect=lambda p: str(p).upper()):
            self.assertTrue(SerialPortInfo.is_espressif_usb_port('com10'))
            self.assertFalse(SerialPortInfo.is_espressif_usb_port('COM5'))
            self.assertFalse(SerialPortInfo.is_espressif_usb_port('COM11'))
            self.assertFalse(SerialPortInfo.is_espressif_usb_port('COM99'))
        with mock.patch.object(SerialPortInfo, '_comports', return_value=None):
            self.assertFalse(SerialPortInfo.is_espressif_usb_port('COM10'))

    def test_is_espressif_usb_port_alias_wait(self):
        class FakePortInfo:
            def __init__(self, device, vid):
                self.device = device
                self.vid = vid
        alias = '/dev/serial/by-id/usb-Espressif_USB_JTAG_serial_debug_unit-if00'
        state = {'present': False}
        def fake_comports():
            polls = fake_comports.polls = getattr(fake_comports, 'polls', 0) + 1
            state['present'] = polls >= 3  # device comes back at the third poll
            return [FakePortInfo('/dev/ttyACM0', 0x303A)] if state['present'] else []
        def fake_norm_key(path):  # (alias resolves to the device only while it is present)
            return '/dev/ttyACM0' if (path == alias and state['present']) else path
        with mock.patch.object(SerialPortInfo, '_comports', side_effect=fake_comports), \
                mock.patch.object(SerialPortInfo, '_norm_key', side_effect=fake_norm_key), \
                mock.patch.object(SerialPortInfo.time, 'sleep'):
            self.assertTrue(SerialPortInfo.is_espressif_usb_port(alias, wait_secs=5))

    def test_port_present_wait(self):
        results = iter([False, False, True])
        with mock.patch.object(SerialPortInfo, '_port_present_now', side_effect=lambda p: next(results)), \
                mock.patch.object(SerialPortInfo.time, 'sleep'):
            self.assertTrue(SerialPortInfo.port_present('COM10', wait_secs=5))
        with mock.patch.object(SerialPortInfo, '_port_present_now', return_value=False), \
                mock.patch.object(SerialPortInfo.time, 'sleep') as sleep_mock:
            self.assertFalse(SerialPortInfo.port_present('COM10'))  # (no wait by default)
            sleep_mock.assert_not_called()

    def test_comports_with_recheck(self):
        class FakePortInfo:
            def __init__(self, device, vid):
                self.device = device
                self.vid = vid
        esp = FakePortInfo('COM10', 0x303A)
        other = FakePortInfo('COM5', 0x10C4)
        polls = iter([[esp, other], [other], [other], [esp, other]])
        with mock.patch.dict(SerialPortInfo._recent_espressif_ports, clear=True), \
                mock.patch('serial.tools.list_ports.comports', side_effect=lambda: next(polls)), \
                mock.patch.object(SerialPortInfo, '_norm_key', side_effect=lambda p: str(p).upper()), \
                mock.patch.object(SerialPortInfo.time, 'sleep'):
            self.assertEqual(len(SerialPortInfo._comports_with_recheck()), 2)  # first poll; Espressif port now seen
            # Espressif port missing at the next poll: checked again until it appears
            self.assertEqual(sorted(p.device for p in SerialPortInfo._comports_with_recheck()), ['COM10', 'COM5'])

    def test_flash_package_retry(self):
        package = esp32flasher.parse_package(make_zip(make_manifest()))
        def run_results(results):
            results = iter(results)
            def fake_run(args, output_fn):
                lines, ret_val = next(results)
                for line in lines:
                    output_fn(line)
                return ret_val
            return fake_run
        with mock.patch.object(esp32flasher, 'get_esptool_version', return_value='5.7.0'), \
                mock.patch.object(esp32flasher, 'port_present_fn', return_value=True), \
                mock.patch.object(esp32flasher.time, 'sleep'):
            # failure before writing (e.g. port gone): retried
            with mock.patch.object(esp32flasher, '_run_cmd', side_effect=run_results(
                    [(['could not open port'], 2), (['Writing at 0x2000'], 0)])) as run_mock:
                self.assertTrue(esp32flasher.flash_package('COM10', package, lambda t: None))
                self.assertEqual(run_mock.call_count, 2)
            # failure after writing started: not retried
            with mock.patch.object(esp32flasher, '_run_cmd', side_effect=run_results(
                    [(['Writing at 0x2000', 'error'], 2)])) as run_mock:
                self.assertFalse(esp32flasher.flash_package('COM10', package, lambda t: None))
                self.assertEqual(run_mock.call_count, 1)
            # failures before writing: up to the attempts limit
            with mock.patch.object(esp32flasher, '_run_cmd', side_effect=run_results(
                    [(['Failed to connect'], 2)] * esp32flasher.ESPTOOL_ATTEMPTS)) as run_mock:
                self.assertFalse(esp32flasher.flash_package('COM10', package, lambda t: None))
                self.assertEqual(run_mock.call_count, esp32flasher.ESPTOOL_ATTEMPTS)

    def test_esptool_output_filter(self):
        shown = []
        output_filter = esp32flasher.EsptoolOutputFilter(shown.append, {'/tmp/x/2_firmware.bin': 'firmware.bin'})
        for line in ['esptool v5.7.0', 'Connecting...', 'ERROR: could not open port', 'Note: This error originates']:
            output_filter(line)
        self.assertEqual(shown, [])  # (held until connected)
        self.assertFalse(output_filter.connected)
        self.assertEqual(output_filter.error_summary(), 'ERROR: could not open port')
        output_filter = esp32flasher.EsptoolOutputFilter(shown.append, {'/tmp/x/2_firmware.bin': 'firmware.bin'})
        lines = ['Connecting....', 'Connected to ESP32-C5 on COM10:', "Writing '/tmp/x/2_firmware.bin' at 0x00010000..."] + \
                ['Writing at 0x{:08x} {:.1f}% x'.format(i, pct) for i, pct in enumerate([3.6, 21.9, 25.5, 49.0, 51.0, 98.5, 100.0])] + \
                ['Wrote 693072 bytes']
        for line in lines:
            output_filter(line)
        self.assertTrue(output_filter.connected)
        self.assertTrue(output_filter.write_started)
        self.assertEqual([line for line in shown if line.startswith('Writing at')],
                         ['Writing at 0x00000000 3.6% x', 'Writing at 0x00000002 25.5% x',
                          'Writing at 0x00000004 51.0% x', 'Writing at 0x00000005 98.5% x',
                          'Writing at 0x00000006 100.0% x'])
        self.assertIn("Writing 'firmware.bin' at 0x00010000...", shown)

    def test_build_esptool_args(self):
        package = esp32flasher.parse_package(make_zip(make_manifest()))
        files = ['b.bin', 'p.bin', 'f.bin']
        self.assertEqual(esp32flasher.build_esptool_args('COM10', package, files, '5.7.0'),
                         ['--chip', 'esp32c5', '--port', 'COM10', '--before', 'default-reset',
                          '--after', 'hard-reset', 'write-flash',
                          '0x2000', 'b.bin', '0x8000', 'p.bin', '0x10000', 'f.bin'])
        self.assertEqual(esp32flasher.build_esptool_args('/dev/ttyACM0', package, files, '4.14.0'),
                         ['--chip', 'esp32c5', '--port', '/dev/ttyACM0', '--before', 'default_reset',
                          '--after', 'hard_reset', 'write_flash',
                          '0x2000', 'b.bin', '0x8000', 'p.bin', '0x10000', 'f.bin'])

    def test_run_cmd_output(self):
        lines = []
        ret_val = esp32flasher._run_cmd(  #pylint: disable=protected-access
            [sys.executable, '-c', "import sys; sys.stdout.write('one\\ntwo 10%\\rtwo 100%\\n'); sys.exit(3)"],
            lines.append)
        self.assertEqual(ret_val, 3)
        self.assertEqual(lines, ['one', 'two 100%'])


if __name__ == '__main__':
    unittest.main()
