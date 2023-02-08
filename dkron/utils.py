from collections import defaultdict
import logging
import time
from typing import Iterator, Literal, Optional, Union
import requests
from functools import lru_cache

from django.conf import settings
from django.core.management import call_command
from django.utils import timezone

from dkron import models

logger = logging.getLogger(__name__)


class DkronException(Exception):
    def __init__(self, code, message) -> None:
        self.code = code
        self.message = message

    def __str__(self) -> str:
        return self.message


@lru_cache
def dkron_url():
    return (settings.DKRON_URL or '').rstrip('/') + '/'


@lru_cache
def api_url():
    return f'{dkron_url()}v1/'


@lru_cache
def namespace():
    if not settings.DKRON_NAMESPACE:
        return ''
    return settings.DKRON_NAMESPACE.rstrip('_')


@lru_cache
def namespace_prefix():
    k = namespace()
    if not k:
        return ''
    return f'{k}_'


def add_namespace(job_name):
    if not job_name:
        return ''
    if not namespace_prefix():
        return job_name
    return f'{namespace_prefix()}{job_name}'


def trim_namespace(job_name):
    if not job_name:
        return ''
    k = namespace_prefix()
    if not k:
        return job_name
    if job_name.startswith(k):
        return job_name[len(k) :]
    return ''


def _set_auth(kwargs) -> None:
    if not settings.DKRON_API_AUTH:
        return
    if 'headers' not in kwargs:
        kwargs['headers'] = {}
    kwargs['headers']['Authorization'] = f'Basic {settings.DKRON_API_AUTH}'


def _get(path, *a, **b) -> requests.Response:
    _set_auth(b)
    return requests.get(f'{api_url()}{path}', *a, **b)


def _post(path, *a, **b) -> requests.Response:
    _set_auth(b)
    return requests.post(f'{api_url()}{path}', *a, **b)


def _delete(path, *a, **b) -> requests.Response:
    _set_auth(b)
    return requests.delete(f'{api_url()}{path}', *a, **b)


def sync_job(job: Union[str, models.Job], job_update: Optional[Union[bool, dict]] = False) -> None:
    """
    :param job: job name or object to be created/updated (without namespace prefix, if any)
    :param job_update: fkin weird variable that can be False for job to be replaced, None to fetch current job and
                       update it or contain a dict with the existing job, saving the request (for batch operations)
    :return:
    """
    if not isinstance(job, models.Job):
        job = models.Job.objects.get(name=job)

    parent_job = add_namespace(job.parent_name) or None
    schedule = '@manually' if parent_job else job.schedule

    job_dict = {}
    if job_update is None:
        try:
            r = _get(f'jobs/{job.namespaced_name}')
            if r.status_code == 200:
                job_dict = r.json()
        except Exception:
            # ignore but log for future analysis
            logger.exception('fetching job %s (%s) failed', job.name, job.namespaced_name)
    elif isinstance(job_update, dict):
        job_dict = job_update

    job_dict.update(
        {
            'name': job.namespaced_name,
            'schedule': schedule,
            'parent_job': parent_job,
            'executor': 'shell',
            'tags': {'label': f'{settings.DKRON_JOB_LABEL}:1'} if settings.DKRON_JOB_LABEL else {},
            'metadata': {'cron': 'auto'},
            'disabled': not job.enabled,
            'executor_config': {'shell': 'true' if job.use_shell else 'false', 'command': job.command},
            'retries': job.retries,
        }
    )
    r = _post('jobs', json=job_dict)
    if r.status_code != 201:
        raise DkronException(r.status_code, r.text)


def delete_job(job: Union[str, models.Job]) -> None:
    """
    :param job: job name or object to be deleted (without namespace prefix, if any)
    :return:
    """
    if isinstance(job, models.Job):
        job_name = job.namespaced_name
    else:
        job_name = add_namespace(job)

    r = _delete(f'jobs/{job_name}')
    if r.status_code != 200:
        raise DkronException(r.status_code, r.text)


def _dependency_ordered():
    """
    look into dependencies graph and yield them in order
    (so parents are always created/updated before children)
    """

    # build graph
    NO_PARENT = '_'
    dep_graph = defaultdict(list)
    for job in models.Job.objects.all():
        p = job.parent_name or NO_PARENT
        dep_graph[p].append(job)

    # start with those without parent
    p = NO_PARENT
    already_processed = set()
    while True:
        if not dep_graph.get(p):
            logger.error('dep_graph should not be empty: %s', p)
            break
        for job in dep_graph[p]:
            already_processed.add(job.name)
            yield job
        del dep_graph[p]
        # find new "parent" that has already been processed
        for k in dep_graph:
            if k in already_processed:
                p = k
                break
        else:
            if dep_graph:
                logger.error('jobs left in the graph: %s', ','.join(dep_graph.keys()))
            break


def resync_jobs() -> Iterator[tuple[str, Literal["u", "d"], Optional[str]]]:
    r = _get('jobs', params={'metadata[cron]': 'auto'})
    if r.status_code != 200:
        raise DkronException(r.status_code, r.text)

    previous_jobs = {}
    for y in r.json():
        k = trim_namespace(y['name'])
        if not k:
            # wrong namespace
            continue
        if settings.DKRON_JOB_LABEL and settings.DKRON_JOB_LABEL != y.get('tags', {}).get('label', ''):
            # label for another agent, ignore as well, log warning
            logger.warning(
                'job %s (%s) matches metadata but it is missing the label - maybe namespacing required?', k, y['name']
            )
            continue
        previous_jobs[k] = y

    # just post all jobs even if they already exist
    # cheaper than checking all the differences (probably)
    current_jobs = set()
    # look into dependencies for proper creation order...
    for job in _dependency_ordered():
        current_jobs.add(job.name)
        try:
            sync_job(job, previous_jobs.get(job.name, False))
            yield job.name, 'u', None
        except DkronException as e:
            yield job.name, 'u', str(e)

    for job in set(previous_jobs) - current_jobs:
        try:
            delete_job(job)
            yield job, 'd', None
        except DkronException as e:
            yield job, 'd', str(e)


try:
    import after_response

    @after_response.enable
    def __run_async(command, *args, **kwargs) -> str:
        return call_command(command, *args, **kwargs)

except ImportError:

    def __run_async(command, *args, **kwargs):
        raise DkronException('dkron is down and after_response is not installed')


def __run_async_dkron(command, *args, **kwargs) -> tuple[str, str]:
    final_command = f'python ./manage.py {command}'

    # FIXME code very likely to NOT work in some cases :P
    if args:
        final_command += ' ' + ' '.join(map(str, args))
    if kwargs:
        for k in kwargs:
            val = kwargs[k]
            k = k.replace("_", "-")

            if isinstance(val, bool):
                if val is True:
                    final_command += f' --{k}'
            else:
                if isinstance(val, (list, tuple)):
                    for v in val:
                        final_command += f' --{k} {v}'
                else:
                    final_command += f' --{k} {val}'

    name = f'tmp_{command}_{time.time():.0f}'
    r = _post(
        'jobs',
        json={
            'name': add_namespace(name),
            'schedule': f'@at {(timezone.now() + timezone.timedelta(seconds=5)).isoformat()}',
            'executor': 'shell',
            'tags': {'label': f'{settings.DKRON_JOB_LABEL}:1'} if settings.DKRON_JOB_LABEL else {},
            'metadata': {'temp': 'true'},
            'disabled': False,
            'executor_config': {'command': final_command},
        },
        # FIXME: workaround for https://github.com/surface-security/django-dkron/issues/18
        # if dkron fixes it, restore this (either based on dkron version or ignore the bug for old version...)
        # params={'runoncreate': 'true'},
    )

    if r.status_code != 201:
        raise DkronException(r.status_code, r.text)

    return name, job_executions(name)


def job_executions(job_name):
    return f'{settings.DKRON_PATH}#/jobs/{add_namespace(job_name)}/show/executions'


def run_async(command, *args, **kwargs) -> Union[tuple[str, str], str]:
    try:
        return __run_async_dkron(command, *args, **kwargs)
    except requests.ConnectionError:
        # if dkron not available, use after_response
        return __run_async.after_response(command, *args, **kwargs)
