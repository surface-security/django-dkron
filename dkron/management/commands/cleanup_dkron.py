from django.utils import timezone

from logbasecommand.base import LogBaseCommand
from dkron import utils


class Command(LogBaseCommand):
    help = 'Remove old "temp" jobs'

    def add_arguments(self, parser):
        parser.add_argument('-d', '--dry', action='store_true', help='Dry (test) run only, no changes')
        parser.add_argument('-k', '--days', type=int, default=30, help='Number of days to keep')

    def handle(self, *args, **options):
        oldest = int((timezone.now() - timezone.timedelta(days=options['days'])).timestamp())
        self.log(f'Deleting temporary jobs with timestamp lower than {oldest}')
        to_del = []
        jobs = utils._get('jobs', params={'metadata[temp]': 'true'}).json()
        total = len(jobs)
        for j in jobs:
            try:
                ts = int(j['name'].split('_')[-1])
            except Exception:
                # let's see if this happens, it shouldn't...
                self.log_exception('unexpected job name %s - ignoring for now', j['name'])
            if ts < oldest:
                to_del.append(j['name'])

        self.log(f'Deleting {len(to_del)} jobs (out of {total})')
        for x in to_del:
            if options['dry']:
                self.log(f'WOULD delete: {x}')
            else:
                utils.delete_job(x)
