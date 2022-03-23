from django.shortcuts import reverse
from django.apps import AppConfig
from django.conf import settings

APP_SETTINGS = dict(
    # dkron server URL
    URL='http://localhost:8888',
    # used to build browser-visible URLs to dkron - can be a full URL if no reverse proxy is being used
    PATH=None,
    # directory to store and execute the dkron binaries, defaults to temporary one - hardly optimal, do set one up!
    BIN_DIR=None,
    # dkron version to (download and) use
    VERSION='3.1.10',
    # can be changed in case a dkron fork is meant to be used
    DOWNLOAD_URL_TEMPLATE='https://github.com/distribworks/dkron/releases/download/v{version}/dkron_{version}_{system}_{machine}.tar.gz',
    # always `run_dkron` in server mode
    SERVER=False,
    # tags for the agent/server created by `run_dkron` - `label=` tag is not required as it is added by `DKRON_JOB_LABEL`
    TAGS=[],
    # label for the jobs managed by this app, used to make this app agent run only jobs created by this app`
    JOB_LABEL=None,
    # --join when using `run_dkron`
    JOIN=[],
    # workdir of `run_dkron`
    WORKDIR=None,
    # gossip encrypt key for `run_dkron`
    ENCRYPT=None,
    # HTTP Basic auth header value, if dkron instance is protected with it (really recommended, if instance is exposed)
    API_AUTH=None,
    # Token used by `run_dkron` for webhook calls into this app
    TOKEN=None,
    # URL called by dkron webhooks to post job status to this app - passed as `--webhook-url` to dkron, so you need to map `dkron.views.webhook` in your project urls.py and this should be full URL to that route and reachable by dkron
    WEBHOOK_URL=None,
    # string to be prefixed to each job created by this app in dkron so the same dkron cluster can be used by different apps/instances without conflicting job names (assuming unique namespaces ^^)
    NAMESPACE=None,
    # node name to be passed to dkron as `--node-name` - defaults to machine hostname
    NODE_NAME=None,
)


class DkronConfig(AppConfig):
    name = 'dkron'
    default_auto_field = 'django.db.models.AutoField'

    def ready(self):
        for k, v in APP_SETTINGS.items():
            _k = 'DKRON_%s' % k
            if hasattr(settings, _k):
                continue
            if (k, v) == ('PATH', None):
                # special one to default to reverse url
                v = reverse('dkron:proxy')
            setattr(settings, _k, v)
