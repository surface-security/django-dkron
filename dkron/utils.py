import logging
import time
from typing import Iterator, Literal, Optional, Union

import requests
from django.conf import settings
from django.core.management import call_command

from dkron import models

logger = logging.getLogger(__name__)


class DkronException(Exception):
    def __init__(self, code, message) -> None:
        self.code = code
        self.message = message

    def __str__(self) -> str:
        return self.message


def _lazy_url() -> str:
    _u = getattr(_lazy_url, '_cache', None)
    if _u is None:
        if settings.DKRON_URL.endswith('/'):
            _u = f'{settings.DKRON_URL}v1/'
        else:
            _u = f'{settings.DKRON_URL}/v1/'
        setattr(_lazy_url, '_cache', _u)
    return _u


def _set_auth(kwargs) -> None:
    if not settings.DKRON_API_AUTH:
        return
    if 'headers' not in kwargs:
        kwargs['headers'] = {}
    kwargs['headers']['Authorization'] = f'Basic {settings.DKRON_API_AUTH}'


def _get(path, *a, **b) -> requests.Response:
    _set_auth(b)
    return requests.get(f'{_lazy_url()}{path}', *a, **b)


def _post(path, *a, **b) -> requests.Response:
    _set_auth(b)
    return requests.post(f'{_lazy_url()}{path}', *a, **b)


def _delete(path, *a, **b) -> requests.Response:
    _set_auth(b)
    return requests.delete(f'{_lazy_url()}{path}', *a, **b)


def sync_job(job, job_update=False) -> None:
    """

    :param job: job name or object to be created/updated
    :param job_update: fkin weird variable that can be False for job to be replaced, None to fetch current job and
                       update it or contain a dict with the existing job, saving the request (for batch operations)
    :return:
    """
    if not isinstance(job, models.Job):
        job = models.Job.objects.get(name=job)
    if job.schedule.startswith('@parent '):
        schedule = '@manually'
        parent_job = job.schedule[8:]
    else:
        schedule = job.schedule
        parent_job = None

    job_dict = {}
    if job_update is None:
        try:
            r = _get(f'jobs/{job.name}')
            if r.status_code == 200:
                job_dict = r.json()
        except Exception:
            # ignore but log for future analysis
            logger.exception('fetching job %s failed', job.name)
    elif isinstance(job_update, dict):
        job_dict = job_update

    job_dict.update(
        {
            'name': job.name,
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


def delete_job(job) -> None:
    if isinstance(job, models.Job):
        job = job.name
    r = _delete(f'jobs/{job}')
    if r.status_code != 200:
        raise DkronException(r.status_code, r.text)


def resync_jobs() -> Iterator[tuple[str, Literal["u", "d"], Optional[str]]]:
    r = _get('jobs', params={'metadata[cron]': 'auto'})
    if r.status_code != 200:
        raise DkronException(r.status_code, r.text)

    previous_jobs = {y['name']: y for y in r.json()}

    # just post all jobs even if they already exist
    # cheaper than checking all the differences (probably)
    current_jobs = set()
    # look into dependencies for proper creation order...
    dep_graph = {}
    for job in models.Job.objects.all():
        if job.schedule.startswith('@parent '):
            p = job.schedule[8:]
        else:
            p = '_'
        if p not in dep_graph:
            dep_graph[p] = []
        dep_graph[p].append(job)

    p = '_'
    while True:
        if not dep_graph.get(p):
            logger.error('dep_graph should not be empty: %s', p)
            break
        for job in dep_graph[p]:
            current_jobs.add(job.name)
            try:
                sync_job(job, previous_jobs.get(job.name, False))
                yield job.name, 'u', None
            except DkronException as e:
                yield job.name, 'u', str(e)
        del dep_graph[p]
        for k in dep_graph:
            if k in current_jobs:
                p = k
                break
        else:
            if dep_graph:
                logger.error('jobs left in the graph: %s', ','.join(dep_graph.keys()))
            break

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
        raise Exception('missing after_response app')


def __run_async_dkron(command, *args, **kwargs) -> tuple[str, str]:
    final_command = f'python ./manage.py {command}'

    # FIXME code very likely to NOT work in some cases :P
    if args:
        final_command += ' ' + ' '.join(map(str, args))
    if kwargs:
        for k in kwargs:
            val = kwargs[k]

            if isinstance(val, bool):
                if val is True:
                    final_command += f' --{k}'
            else:
                if isinstance(val, (list, tuple)):
                    val = ' '.join(val)
                final_command += f' --{k.replace("_", "-")} {val}'

    name = f'tmp_{command}_{time.time():.0f}'
    r = _post(
        'jobs',
        json={
            'name': name,
            'schedule': '@manually',
            'executor': 'shell',
            'tags': {'label': f'{settings.DKRON_JOB_LABEL}:1'} if settings.DKRON_JOB_LABEL else {},
            'metadata': {'temp': 'true'},
            'disabled': False,
            'executor_config': {'command': final_command},
        },
        params={'runoncreate': 'true'},
    )

    if r.status_code != 201:
        raise DkronException(r.status_code, r.text)

    return name, job_executions(name)


def job_executions(job_name):
    return f'{settings.DKRON_PATH}#/jobs/{job_name}/show/executions'


def run_async(command, *args, **kwargs) -> Union[tuple[str, str], str]:
    try:
        return __run_async_dkron(command, *args, **kwargs)
    except requests.ConnectionError:
        # if dkron not available, use after_response
        return __run_async.after_response(command, *args, **kwargs)
