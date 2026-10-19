import copy
import json
import os
import tempfile
import unittest
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import camera_archive as archive
from camera_model import new_camera


class ArchiveTests(unittest.TestCase):
    def test_control_port_transfers_but_discovered_metadata_does_not(self):
        self.camera['control_port'] = 25554
        self.camera['ptz'] = {'private': 'not transferred'}
        imported = archive.decode(archive.encode([self.camera]))[0]
        self.assertEqual(imported['control_port'], 25554)
        self.assertIsNone(imported['ptz'])
        old = dict(self.camera)
        old.pop('control_port')
        self.assertEqual(archive._record(old)['control_port'], 5000)
        for value in (True, 0, 65536, '25554', None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                archive.encode([dict(self.camera, control_port=value)])

    def setUp(self):
        self.camera = new_camera('거실', 'rtsp://viewer:synthetic%21@127.0.0.1:8554/onvif1')
        self.camera.update(number=7, sd_url='rtsp://viewer:synthetic%21@127.0.0.1:8554/onvif2', volume=43, muted=True)

    def test_passwordless_roundtrip_has_no_plaintext_fields_and_uses_random_nonce(self):
        first, second = archive.encode([self.camera]), archive.encode([self.camera])
        self.assertNotEqual(first, second)
        for value in ('거실', '127.0.0.1', 'viewer', 'synthetic', 'rtsp://'):
            self.assertNotIn(value.encode(), first)
        result = archive.decode(first)[0]
        for key in ('name', 'url', 'sd_url', 'enabled', 'quality'):
            self.assertEqual(result[key], self.camera[key])
        self.assertEqual(result['volume'], 100)
        self.assertFalse(result['muted'])
        self.assertNotEqual(result['id'], self.camera['id'])

    def test_export_payload_excludes_audio_fields(self):
        blob = archive.encode([self.camera])
        start = len(archive.MAGIC)
        plaintext = AESGCM(archive._FORMAT_KEY).decrypt(
            blob[start:start + 12], blob[start + 12:], archive.MAGIC)
        record = json.loads(plaintext)['cameras'][0]
        self.assertEqual(set(record), {'name', 'url', 'sd_url', 'quality', 'enabled', 'control_port'})

    def test_legacy_audio_fields_are_ignored_on_decode_and_import(self):
        for volume, muted in ((0, True), (43, True), (200, False), ('ignored', ['ignored'])):
            with self.subTest(volume=volume, muted=muted):
                record = dict(self.camera, volume=volume, muted=muted)
                nonce = os.urandom(12)
                payload = json.dumps(dict(version=1, cameras=[record])).encode()
                blob = archive.MAGIC + nonce + AESGCM(archive._FORMAT_KEY).encrypt(
                    nonce, payload, archive.MAGIC)
                decoded = archive.decode(blob)[0]
                self.assertEqual(decoded['volume'], 100)
                self.assertFalse(decoded['muted'])
                imported, _ = archive.import_candidates([record], [])
                self.assertEqual(imported[0]['volume'], 100)
                self.assertFalse(imported[0]['muted'])

    def test_invalid_truncated_modified_and_oversized_files_rejected(self):
        blob = archive.encode([self.camera])
        bad = bytearray(blob)
        bad[-1] ^= 1
        for value in (b'', b'{}', blob[:20], bytes(bad), b'x' * (archive.MAX_BYTES + 1)):
            with self.subTest(length=len(value)), self.assertRaises(ValueError):
                archive.decode(value)

    def test_encrypted_but_invalid_schema_is_rejected(self):
        invalids = [dict(version=2, cameras=[self.camera]), dict(version=1, cameras=[]),
                    dict(version=True, cameras=[self.camera]),
                    dict(version=1, cameras=[dict(self.camera, quality='invalid')]),
                    dict(version=1, cameras=[dict(self.camera, enabled='yes')]),
                    dict(version=1, cameras=[dict(self.camera, url='file:///secret')]),
                    dict(version=1, cameras=[self.camera] * (archive.MAX_CAMERAS + 1))]
        for raw in invalids:
            nonce = os.urandom(12)
            blob = archive.MAGIC + nonce + AESGCM(archive._FORMAT_KEY).encrypt(nonce, json.dumps(raw).encode(), archive.MAGIC)
            with self.assertRaises(ValueError):
                archive.decode(blob)

    def test_import_skips_duplicates_reassigns_ids_and_numbers_and_preserves_existing(self):
        existing = [self.camera]
        original = copy.deepcopy(existing)
        other = dict(self.camera, url='rtsp://viewer:other@127.0.0.2:8554/onvif1', enabled=False)
        result, duplicates = archive.import_candidates([self.camera, other, other], existing)
        self.assertEqual(duplicates, 2)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['number'], 8)
        self.assertNotEqual(result[0]['id'], self.camera['id'])
        self.assertFalse(result[0]['enabled'])
        self.assertEqual(existing, original)

    def test_locked_or_empty_export_is_rejected_and_binary_file_loads(self):
        for cameras in ([], [dict(self.camera, connection_locked=True)]):
            with self.assertRaises(ValueError):
                archive.encode(cameras)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'test.camfloat'
            path.write_bytes(archive.encode([self.camera]))
            self.assertEqual(archive.read_file(path)[0]['url'], self.camera['url'])
