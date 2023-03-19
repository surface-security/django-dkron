import json
from django.core.management import call_command
from logbasecommand.base import LogBaseCommand

import json
import base64


class Command(LogBaseCommand):
    help = 'Hidden command'

    def add_arguments(self, parser):
        parser.add_argument('command', help='Run in server mode')
        parser.add_argument('arguments', nargs='?', help='Port used by the web UI')

    def handle(self, *_, **options):
        args = []
        kwargs = {}
        if options['arguments']:
            arguments = json.loads(base64.b64decode(options['arguments']))
            args = arguments.get('args') or []
            kwargs = arguments.get('kwargs') or {}

        call_command(options['command'], *args, **kwargs, stdout=options.get('stdout'), stderr=options.get('stderr'))
