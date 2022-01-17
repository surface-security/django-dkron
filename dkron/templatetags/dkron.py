from django import template
from django.conf import settings

from dkron import utils

register = template.Library()


@register.simple_tag
def dkron_path():
    return settings.DKRON_PATH


@register.simple_tag
def dkron_executions(job_name):
    return utils.job_executions(job_name)
