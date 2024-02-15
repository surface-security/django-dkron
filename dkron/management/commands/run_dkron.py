import tempfile
import os
import requests
import shutil
import tarfile
from pathlib import Path
from django.conf import settings

from logbasecommand.base import LogBaseCommand
from dkron import utils


class Command(LogBaseCommand):
    help = 'Run dkron agent'

    def add_arguments(self, parser):
        parser.add_argument('-s', '--server', action='store_true', help='Run in server mode')
        parser.add_argument('-p', '--http-addr', type=int, default=8888, help='Port used by the web UI')
        parser.add_argument(
            '-j', '--join', action='append', help='Initial agent(s) to join with (can be used multiple times)'
        )
        parser.add_argument(
            '-e', '--encrypt', type=str, help='Key for encrypting network traffic. Must be a base64-encoded 16-byte key'
        )
        parser.add_argument(
            '--node-name',
            type=str,
            default=settings.DKRON_NODE_NAME,
            help='Key for encrypting network traffic. Must be a base64-encoded 16-byte key',
        )

    def download_dkron(self):
        if settings.DKRON_BIN_DIR is None:
            bin_dir = Path(tempfile.mkdtemp())
        else:
            bin_dir = Path(settings.DKRON_BIN_DIR) / settings.DKRON_VERSION

        dl_url, system, _ = utils.dkron_binary_download_url()
        exe_path = bin_dir / ('dkron.exe' if system == 'windows' else 'dkron')

        # check if download is required
        if not exe_path.is_file():
            os.makedirs(bin_dir, exist_ok=True)
            tarball = f'{exe_path}.tar.gz'
            self.log(f'Downloading {dl_url}')
            with requests.get(dl_url, stream=True) as r:
                r.raise_for_status()
                with open(tarball, 'wb') as f:
                    shutil.copyfileobj(r.raw, f)
            tf = tarfile.open(tarball)
            tf.extractall(path=bin_dir)
            os.unlink(tarball)

        return str(exe_path), str(bin_dir)

    def handle(self, *_, **options):
        exe_path, bin_dir = self.download_dkron()

        args = [exe_path, 'agent']

        if options['server'] or settings.DKRON_SERVER:
            args.extend(
                [
                    '--server',
                    '--http-addr',
                    f':{options["http_addr"]}',
                    '--bootstrap-expect',
                    '1',
                    '--data-dir',
                    bin_dir,
                ]
            )
        if options['encrypt'] or settings.DKRON_ENCRYPT:
            args.extend(['--encrypt', options['encrypt'] or settings.DKRON_ENCRYPT])
        if options['node_name']:
            args.extend(['--node-name', options['node_name']])
        for tag in settings.DKRON_TAGS or []:
            args.extend(['--tag', tag])
        # make sure the LABEL tag is included
        if settings.DKRON_JOB_LABEL:
            args.extend(['--tag', f'label={settings.DKRON_JOB_LABEL}'])
        for j in options['join'] or settings.DKRON_JOIN or []:
            args.extend(['--join', j])
        if settings.DKRON_WORKDIR:
            os.chdir(settings.DKRON_WORKDIR)
        if settings.DKRON_PRE_WEBHOOK_URL and settings.DKRON_TOKEN and settings.DKRON_SENTRY_CRON_URL:
            flag_name = '--pre-webhook-url' if utils.dkron_binary_version() < (3, 2, 0) else '--pre-webhook-endpoint'
            args.extend(
                [
                    flag_name,
                    settings.DKRON_PRE_WEBHOOK_URL,
                    '--pre-webhook-payload',
                    f'{settings.DKRON_TOKEN}\n{{{{ .JobName }}}}',
                ]
            )
        if settings.DKRON_WEBHOOK_URL and settings.DKRON_TOKEN:
            flag_name = '--webhook-url' if utils.dkron_binary_version() < (3, 2, 0) else '--webhook-endpoint'
            args.extend(
                [
                    flag_name,
                    settings.DKRON_WEBHOOK_URL,
                    '--webhook-payload',
                    f'{settings.DKRON_TOKEN}\n{{{{ .JobName }}}}\n{{{{ .Success }}}}',
                ]
            )
        os.execv(exe_path, args)
