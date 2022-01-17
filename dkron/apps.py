from django.apps import AppConfig
from django.conf import settings

APP_SETTINGS = dict(
    URL=None,
    PATH=None,
    BIN_DIR=None,
    VERSION='3.1.8',
    DOWNLOAD_URL_TEMPLATE='https://github.com/distribworks/dkron/releases/download/v{version}/dkron_{version}_{system}_amd64.tar.gz',
    WEB_PORT=None,
    SERVER=False,
    TAGS=[],
    # to ping jobs to agents with specific `label:XXX` - it should be part of `TAGS` or no agents will pick up the jobs...
    JOB_LABEL=None,
    JOIN=[],
    WORKDIR=None,
    ENCRYPT=None,
    API_AUTH=None,
    TOKEN=None,
    WEBHOOK_URL=None,
)


class DkronConfig(AppConfig):
    name = 'dkron'

    def ready(self):
        for k, v in APP_SETTINGS.items():
            _k = 'DKRON_%s' % k
            if not hasattr(settings, _k):
                setattr(settings, _k, v)
