# django-dkron

[![build-status-image]][build-status]
[![coverage-status-image]][codecov]
[![pypi-version]][pypi]

**Manage and run jobs in Dkron from your django project**

* Command to launch dkron agent `run_dkron`
* django-admin integration for managing dkron jobs
* notifications ([django-notification-sender](https://github.com/surface-security/django-notification-sender)) on failed jobs
* reverse proxy for dkron dashboard to leverage django authenticated user permissions
* `run_async` utility method to launch long running tasks (in a one-time temporary dkron job)

![image](https://user-images.githubusercontent.com/63779195/152008384-51dd34d5-f0f8-4e68-ab3a-32d92f2aeb43.png)

## Setup

Add `dkron` to `INSTALLED_APPS` in your `settings.py`.

The following app settings are available for customization (from [dkron/apps.py](dkron/apps.py))

| Name | Default | Description |
| ---- | -----   | -------     |
| DKRON_URL | `http://localhost:8888` | dkron server URL |
| DKRON_PATH |  | used to build browser-visible URLs to dkron - can be a full URL if no reverse proxy is being used |
| DKRON_BIN_DIR | | directory to store and execute the dkron binaries, defaults to temporary one - hardly optimal, do set one up! |
| DKRON_VERSION | `3.1.10` | dkron version to (download and) use |
| DKRON_DOWNLOAD_URL_TEMPLATE | `https://github.com/distribworks/dkron/releases/download/v{version}/dkron_{version}_{system}_{machine}.tar.gz` | can be changed in case a dkron fork is meant to be used |
| DKRON_SERVER | `False` | always `run_dkron` in server mode |
| DKRON_TAGS | `[]` | tags for the agent/server created by `run_dkron` - `label=` tag is not required as it is added by `DKRON_JOB_LABEL` |
| DKRON_JOB_LABEL | | label for the jobs managed by this app, used to make this app agent run only jobs created by this app |
| DKRON_JOIN | `[]` | --join when using `run_dkron` |
| DKRON_WORKDIR |  | workdir of `run_dkron` |
| DKRON_ENCRYPT |  | gossip encrypt key for `run_dkron` |
| DKRON_API_AUTH |  | HTTP Basic auth header value, if dkron instance is protected with it (really recommended, if instance is exposed) |
| DKRON_TOKEN |  | Token used by `run_dkron` for webhook calls into this app |
| DKRON_WEBHOOK_URL |  | URL called by dkron webhooks to post job status to this app - passed as `--webhook-url` to dkron, so you need to map `dkron.views.webhook` in your project urls.py and this should be full URL to that route and reachable by dkron|
| DKRON_NAMESPACE | | string to be prefixed to each job created by this app in dkron so the same dkron cluster can be used by different apps/instances without conflicting job names (assuming unique namespaces ^^) |

Besides starting the django app (with `./manage.py runserver`, `gunicorn` or similar) also start dkron agent with `./manage.py run_dkron`:

```
$ ./manage.py run_dkron -h
usage: manage.py run_dkron [-h] [-s] [-p HTTP_ADDR] [-j JOIN] [-e ENCRYPT] [--version] [-v {0,1,2,3}] [--settings SETTINGS] [--pythonpath PYTHONPATH] [--traceback] [--no-color] [--force-color]
                           [--skip-checks]

Run dkron agent

optional arguments:
  -h, --help            show this help message and exit
  -s, --server          Run in server mode
  -p HTTP_ADDR, --http-addr HTTP_ADDR
                        Port used by the web UI
  -j JOIN, --join JOIN  Initial agent(s) to join with (can be used multiple times)
  -e ENCRYPT, --encrypt ENCRYPT
                        Key for encrypting network traffic. Must be a base64-encoded 16-byte key
  --version             show program's version number and exit
  -v {0,1,2,3}, --verbosity {0,1,2,3}
                        Verbosity level; 0=minimal output, 1=normal output, 2=verbose output, 3=very verbose output
  --settings SETTINGS   The Python path to a settings module, e.g. "myproject.settings.main". If this isn't provided, the DJANGO_SETTINGS_MODULE environment variable will be used.
  --pythonpath PYTHONPATH
                        A directory to add to the Python path, e.g. "/home/djangoprojects/myproject".
  --traceback           Raise on CommandError exceptions
  --no-color            Don't colorize the command output.
  --force-color         Force colorization of the command output.
  --skip-checks         Skip system checks.
```

## Background tasks

Besides managing the scheduled jobs in django-admin, this app also has the [run_async](https://github.com/surface-security/django-dkron/blob/8df5dbdbd1392b07dcedd4c7bc402cb948f64fc7/dkron/utils.py#L219) utility method to run one-time temporary jobs.

```python
from dkron.utils import run_async
job_name, job_link = utils.run_async('some_management_command', 'arg1', kwarg='value', enable=True)
```

This will return the `job_name` (`tmp_some_management_command_1` in example) created in Dkron and `job_link` (`/dkron/proxy/ui/#/jobs/tmp_somecommand_1/show/executions` in example) as the direct link to the job executions in Dkron UI (this uses the setting `DKRON_PATH` to build the link).

If dkron is not running, `run_async` falls back to [after-response](https://github.com/defrex/django-after-response) to simplify the dev setup of your project.

## Authentication

Dkron does not have authorization (nor authentication). The [Pro](https://dkron.io/products/pro/) version does (and you should definitely get it if you're using it in a paid product/service :)) but this app provides a way to authenticate seamlessly to the Dkron dashboard from your project, by proxying access.

There are two options: native django (default) and using nginx (or similar)

### django

This is the simplest way to implement it. Do not set `DKRON_PATH` setting, as it will default to this but do set `DKRON_URL` properly so the app can access dkron instance.

This is will use [dkron.views.proxy](https://github.com/surface-security/django-dkron/blob/8df5dbdbd1392b07dcedd4c7bc402cb948f64fc7/dkron/views.py#L61) to forward any requests to `/dkron/_/` to Dkron URL, but not before requiring a valid django session with the permission `dkron.can_use_dashboard` (or superuser).

This does make every user access to Dkron UI to go through the full django project stack (and `MIDDLEWARE`s). If that's an issue (shouldn't be...), the old approach (using `nginx` with `proxy_pass` and `auth_request`) might interest you.

### nginx

This was the original setup to leverage django sessions to access Dkron UI.

`nginx` might already be part of your production stack for caching and serving static files, so it's just adding an extra location to it.

```
http {
  ...
  upstream dkronserver {
    server DKRON_SERVER_IP:DKRON_SERVER_PORT fail_timeout=0;
  }
  upstream appserver {
    server DJANGO_SERVER_IP:DJANGO_SERVER_PORT fail_timeout=0;
  }

  # IMPORTANT: cache nginx auth requests!
  proxy_cache_path /var/cache/nginx/auth_cache levels=1:2 keys_zone=auth_cache:1m max_size=100m inactive=60m;
  ...
  server {
    ...
    # path for django static files
    location /static/ {
      ...
    }

    location = /dkronauth {
      internal;
      # point to django app on `/dkron/auth`, this will validate the existing django session
      proxy_pass              appserver/dkron/auth/;
      proxy_cache             auth_cache;
      proxy_cache_key         "$host$request_uri $cookie_sessionid";
      proxy_pass_request_body off;
      proxy_set_header        Content-Length "";
      proxy_set_header        X-Original-URI $request_uri;
      proxy_set_header        Host $host;
      proxy_cache_valid       403 30s;
      proxy_cache_valid       200 5m;
    }

    location /dkron/ui/ {
      error_page 401 @dkronerror401;
      error_page 403 /403.html;
      error_page 404 /404.html;
      error_page 500 502 503 504 /500.html;
      auth_request     /dkronauth;
      auth_request_set $auth_status $upstream_status;
      proxy_pass http://dkronserver/;
      proxy_set_header Host $host;
      # if dkron is behind an nginx with basic auth required, uncomment to inject authorization header
      # proxy_set_header Authorization "Basic XXXXXX";
      proxy_redirect / $real_scheme://$host/dkron/ui/;
    }

    location @dkronerror401 {
      # force relative redirect - https://stackoverflow.com/a/39462409
	    return 302 " /login?next=$request_uri";
    }

    location / {
      ...
      proxy_pass $appserver;
    }
    ...
```

## ToDo

* Make notifications dependency optional?
* Document reverse proxy usage (for authentication) or create the JWT/oauth app (and recommend it from here).
* document WEBHOOK configuration (add to `urls.py`) as done in testapp.
* how to set DKRON_TOKEN.
* find any `FIXME`/`TODO` in code

[build-status-image]: https://github.com/surface-security/django-dkron/actions/workflows/test.yml/badge.svg
[build-status]: https://github.com/surface-security/django-dkron/actions/workflows/test.yml
[coverage-status-image]: https://img.shields.io/codecov/c/github/surface-security/django-dkron/main.svg
[codecov]: https://codecov.io/github/surface-security/django-dkron?branch=main
[pypi-version]: https://img.shields.io/pypi/v/django-dkron.svg
[pypi]: https://pypi.org/project/django-dkron/
