from dkron import utils
from logbasecommand.base import LogBaseCommand


class Command(LogBaseCommand):
    help = 'Re-sync dkron jobs'

    def handle(self, *args, **options):
        for job, action, result in utils.resync_jobs():
            if action == 'u':
                if result is None:
                    self.stdout.write('Job %s updated\n' % job)
                else:
                    self.stderr.write('Job %s failed\n' % job)
                    self.stderr.write('%s\n' % result)
            elif action == 'd':
                if result is None:
                    self.stdout.write('Job %s delete\n' % job)
                else:
                    self.stderr.write('Job %s failed\n' % job)
                    self.stderr.write('%s\n' % result)
