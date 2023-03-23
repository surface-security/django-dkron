from io import StringIO
from unittest import mock
from django.test import TestCase, override_settings
from django.core.management import call_command
import json
import base64

from dkron import utils


class Test(TestCase):
    @mock.patch('platform.machine')
    @mock.patch('platform.system')
    @mock.patch('requests.get')
    @override_settings(DKRON_BIN_DIR=None)
    def test_run_dkron_download(self, req_mock, sys_mock, mach_mock):
        from dkron.management.commands import run_dkron
        from io import BytesIO
        import base64

        fake_tar = base64.decodebytes(
            # tarfile with an empty file
            b'H4sICJNVO2IAA2EudGFyAEtkoD0wMDAwMzFRANHmZqZg2sAIwocBBUMTI0MzM1MjM0NDBQNDQzNjIwYFAzq4jaG0uCSxCOiUtPyCzLxE3OqAytLS8JgD9QecHgWjYBSMgkEOAKshHuMABgAA'
        )
        cmd = run_dkron.Command()

        def _check(system, machine, url):
            req_mock.reset_mock()
            sys_mock.return_value = system
            mach_mock.return_value = machine
            req_mock.return_value.__enter__.return_value = mock.MagicMock(raw=BytesIO(fake_tar))
            cmd.download_dkron()
            req_mock.assert_called_once_with(
                url,
                stream=True,
            )

        _check(
            'darwin',
            'x86_64',
            'https://github.com/distribworks/dkron/releases/download/v3.1.10/dkron_3.1.10_darwin_amd64.tar.gz',
        )
        _check(
            'windows',
            'AMD64',
            'https://github.com/distribworks/dkron/releases/download/v3.1.10/dkron_3.1.10_windows_amd64.tar.gz',
        )
        _check(
            'Linux',
            'aarch64',
            'https://github.com/distribworks/dkron/releases/download/v3.1.10/dkron_3.1.10_linux_arm64.tar.gz',
        )

    def test_utils_dkron_version_tuple(self):
        utils.dkron_binary_version.cache_clear()
        with override_settings(DKRON_VERSION='3.1.1'):
            self.assertEqual(utils.dkron_binary_version(), (3, 1, 1))

        utils.dkron_binary_version.cache_clear()
        with override_settings(DKRON_VERSION='4.1.1-fork1'):
            self.assertEqual(utils.dkron_binary_version(), (4, 1, 1))

        utils.dkron_binary_version.cache_clear()
        with override_settings(DKRON_VERSION='prefixed-4.1.2-fork1'):
            self.assertEqual(utils.dkron_binary_version(), (4, 1, 2))

        utils.dkron_binary_version.cache_clear()
        with override_settings(DKRON_VERSION='4.1-bad'):
            self.assertEqual(utils.dkron_binary_version(), utils.UNKNOWN_DKRON_VERSION)

    @mock.patch('dkron.management.commands.run_dkron_async_command.call_command')
    def test_run_async_command(self, cc_mock):
        out = StringIO()
        args = base64.b64encode(json.dumps({'kwargs': {'command': 'wtv'}}).encode()).decode()
        call_command('run_dkron_async_command', 'shell', args, stdout=out)
        cc_mock.assert_called_once_with('shell', command='wtv', stdout=out, stderr=None)
