import requests

from django import http
from django.shortcuts import reverse
from django.conf import settings
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import permission_required

from notifications.utils import notify
from dkron import models, utils


def auth(request):
    # great thing User object is already filled in because Cookies were shared anyway (assuming ProxyPass in nginx)
    # cannot use decorator though because of redirect... fail response needs to be 401 or 403
    # use 401 so nginx redirects to login
    if not request.user.is_authenticated:
        return http.HttpResponse(status=401)
    # and 403 to display access forbidden
    if not request.user.has_perm('dkron.can_use_dashboard'):
        return http.HttpResponseForbidden()
    return http.HttpResponse()


@csrf_exempt
def webhook(request):
    if settings.DKRON_TOKEN is None:
        return http.HttpResponseNotFound()

    if request.method != 'POST':
        return http.HttpResponseBadRequest()

    lines = request.body.decode().splitlines()
    if len(lines) != 3:
        return http.HttpResponseBadRequest()

    if lines[0] != settings.DKRON_TOKEN:
        return http.HttpResponseForbidden()

    job_name = utils.trim_namespace(lines[1])
    if not job_name:
        return http.HttpResponseNotFound()

    o = models.Job.objects.filter(name=job_name).first()
    if o is None:
        return http.HttpResponseNotFound()

    o.last_run_success = lines[2] == 'true'
    o.last_run_date = timezone.now()
    o.save()
    if not o.last_run_success and o.notify_on_error:
        notify(
            'dkron_failed_job',
            f''':red-pipeline: dkron job *{o.name}* <{request.build_absolute_uri(
                utils.job_executions(o.name)
            )}|failed>''',
        )
    return http.HttpResponse()


@permission_required('dkron.can_use_dashboard')
@csrf_exempt
def proxy(request, path=None):
    """
    reverse proxy implementation based on https://github.com/mjumbewu/django-proxy/blob/master/proxy/views.py
    this is a simplified implementation that "just works" for Dkron but is definitely missing cases for reverse proxying other backends
    re-use in other projects at your own discretion :)

    refer to `dkron authentication` section in docs #FIXME
    """
    headers = {
        k: v
        for k, v in request.headers.items()
        # content-length is not used by requests and might get duplicated (due to casing), just remove it
        # also, dkron does not use cookies, simply drop the whole header to avoid sending django app session over
        if k.lower() not in ('content-length', 'cookie')
    }
    url = utils.dkron_url() + (path or '')

    if settings.DKRON_API_AUTH:
        headers['Authorization'] = f'Basic {settings.DKRON_API_AUTH}'

    response = requests.request(
        request.method,
        url,
        allow_redirects=False,
        headers=headers,
        params=request.GET.copy(),
        data=request.body,
    )

    proxy_response = http.HttpResponse(response.content, status=response.status_code)

    excluded_headers = set(
        [
            # Hop-by-hop headers
            # ------------------
            # Certain response headers should NOT be just tunneled through.  These
            # are they.  For more info, see:
            # http://www.w3.org/Protocols/rfc2616/rfc2616-sec13.html#sec13.5.1
            'connection',
            'keep-alive',
            'proxy-authenticate',
            'proxy-authorization',
            'te',
            'trailers',
            'transfer-encoding',
            'upgrade',
            # Although content-encoding is not listed among the hop-by-hop headers,
            # it can cause trouble as well.  Just let the server set the value as
            # it should be.
            'content-encoding',
            # Since the remote server may or may not have sent the content in the
            # same encoding as Django will, let Django worry about what the length
            # should be.
            'content-length',
        ]
    )
    for key, value in response.headers.items():
        if key.lower() in excluded_headers:
            continue
        elif key.lower() == 'location':
            proxy_response[key] = _fix_location_header(path, value)
        else:
            proxy_response[key] = value

    return proxy_response


def _fix_location_header(path, location):
    base = reverse('dkron:proxy')
    if location.startswith(utils.dkron_url()):
        return base + location[len(utils.dkron_url()) :]
    elif location.startswith('/'):
        return base + location[1:]
    else:
        # this is not meant to cover redirects to "outside" dkron
        # so everything else is caught here
        return base + (path or '') + location
