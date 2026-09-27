import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from developer_tools import publish_update as publisher


class PublishUpdateTests(unittest.TestCase):
    def test_release_is_published_only_after_both_assets_upload(self):
        with tempfile.TemporaryDirectory() as folder:
            installer = Path(folder) / 'SanitaryShopPOS-Setup.exe'
            installer.write_bytes(b'installer' * 200)
            (installer.parent / 'release-build.json').write_text(json.dumps({
                'version': publisher.APP_VERSION,
                'sha256': hashlib.sha256(installer.read_bytes()).hexdigest(),
                'manifest_url': publisher.UPDATE_MANIFEST_URL,
            }))
            events = []
            api = Mock()
            def request(method, path, document=None, asset=None):
                events.append((method, path, document))
                if path == '/user':
                    return {'login': 'zuhairzeb'}
                if path.endswith('/releases?per_page=100'):
                    return []
                if method == 'GET':
                    return {'private': False}
                if asset:
                    return {'size': Path(asset).stat().st_size, 'state': 'uploaded'}
                if method == 'POST':
                    return {'id': 1, 'upload_url': 'https://uploads.github.com/test{?name}', 'assets': []}
                return {'html_url': 'https://github.com/test/releases/v1'}
            api.request.side_effect = request
            def prepare(installer, url, output, notes, private_key):
                output.write_text('{}')
                return {'sha256': 'hash'}
            with patch.object(publisher, 'prepare_update', side_effect=prepare):
                publisher.publish(api, installer, ['Update'], Path('private.key'))
            self.assertTrue(events[3][2]['draft'])
            self.assertIn('SanitaryShopPOS-Setup.exe', events[4][1])
            self.assertIn('update.json', events[5][1])
            self.assertEqual(events[-1][0], 'PATCH')
            self.assertFalse(events[-1][2]['draft'])
            events.clear()
            def fail_upload(method, path, document=None, asset=None):
                if asset:
                    raise OSError('Upload failed')
                return request(method, path, document, asset)
            api.request.side_effect = fail_upload
            with patch.object(publisher, 'prepare_update', side_effect=prepare):
                with self.assertRaises(OSError):
                    publisher.publish(api, installer, ['Update'], Path('private.key'))
            self.assertFalse(any(method == 'PATCH' for method, _, _ in events))

    def test_stale_installer_is_rejected_before_repository_changes(self):
        with tempfile.TemporaryDirectory() as folder:
            installer = Path(folder) / 'setup.exe'
            installer.write_bytes(b'old' * 1000)
            (installer.parent / 'release-build.json').write_text('{}')
            api = Mock()
            api.request.return_value = {'login': 'zuhairzeb'}
            with self.assertRaisesRegex(ValueError, 'does not match'):
                publisher.publish(api, installer, [], Path('private.key'))
            api.request.assert_called_once_with('GET', '/user')
