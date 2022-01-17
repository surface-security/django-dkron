from django import http
from django.conf import settings
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

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

    o = models.Job.objects.filter(name=lines[1]).first()

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
