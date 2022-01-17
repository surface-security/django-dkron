import tempfile
import os
import platform
import requests
import shutil
import tarfile

from django.conf import settings

from logbasecommand.base import LogBaseCommand


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

    def download_dkron(self):
        if settings.DKRON_BIN_DIR is None:
            bin_dir = tempfile.mkdtemp()
        else:
            bin_dir = os.path.join(settings.DKRON_BIN_DIR, settings.DKRON_VERSION)
        system = platform.system().lower()
        exe_path = os.path.join(bin_dir, 'dkron.exe' if system == 'windows' else 'dkron')

        # TODO: simple check if download is required, get checksum from somewhere to make sure it's correct binary?
        if not os.path.isfile(exe_path):
            os.makedirs(bin_dir, exist_ok=True)
            dl_url = settings.DKRON_DOWNLOAD_URL_TEMPLATE.format(
                version=settings.DKRON_VERSION,
                system=system,
            )
            tarball = f'{exe_path}.tar.gz'
            self.log(f'Downloading {dl_url}')
            with requests.get(dl_url, stream=True) as r:
                r.raise_for_status()
                with open(tarball, 'wb') as f:
                    shutil.copyfileobj(r.raw, f)
            tf = tarfile.open(tarball)
            tf.extractall(path=bin_dir)
            os.unlink(tarball)

        return exe_path, bin_dir

    def handle(self, *_, **options):
        # TODO: check if there's any shutdown we should care before execv()
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
        for tag in settings.DKRON_TAGS or []:
            args.extend(['--tag', tag])
        for j in options['join'] or settings.DKRON_JOIN or []:
            args.extend(['--join', j])
        if settings.DKRON_WORKDIR:
            os.chdir(settings.DKRON_WORKDIR)
        if settings.DKRON_WEBHOOK_URL and settings.DKRON_TOKEN:
            args.extend(
                [
                    '--webhook-url',
                    settings.DKRON_WEBHOOK_URL,
                    '--webhook-payload',
                    f'{settings.DKRON_TOKEN}\n{{{{ .JobName }}}}\n{{{{ .Success }}}}',
                ]
            )
        os.execv(exe_path, args)
