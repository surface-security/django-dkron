from io import StringIO
import tempfile
import os
import platform

from unittest import mock
from django.apps import apps
from django.conf import settings
from django.urls import reverse
from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.contrib.auth import models as auth_models
from django.core import management
from django.test import TestCase, override_settings
from django.utils import timezone

from notifications import models as notify_models
from dkron import admin, models, utils
from dkron.apps import DkronConfig


@override_settings(DKRON_PATH='/dkron/proxy/ui/', DKRON_URL='http://dkron')
class Test(TestCase):
    def setUp(self):
        # always reset api_url cache as tests might need to use different settings
        utils.api_url.cache_clear()
        self.user = get_user_model().objects.create_user('tester', 'tester@ppb.it', 'tester')
        self.site = AdminSite()

    def _login(self):
        self.client.login(username='tester', password='tester')

    def _job_perm(self, codename):
        return auth_models.Permission.objects.get(
            content_type=auth_models.ContentType.objects.get_for_model(models.Job), codename=codename
        )

    @override_settings()
    def test_apps(self):
        del settings.DKRON_URL
        self.assertEqual(DkronConfig.name, 'dkron')
        self.assertEqual(apps.get_app_config('dkron').name, 'dkron')
        apps.get_app_config('dkron').ready()
        self.assertEqual(settings.DKRON_URL, 'http://localhost:8888')

    def test_auth(self):
        r = self.client.get(reverse('dkron:auth'))
        self.assertEqual(r.status_code, 401)

        self._login()
        r = self.client.get(reverse('dkron:auth'))
        self.assertEqual(r.status_code, 403)

        self.user.is_superuser = True
        self.user.save()
        r = self.client.get(reverse('dkron:auth'))
        self.assertEqual(r.status_code, 200)

        self.user.is_superuser = False
        self.user.is_staff = True
        self.user.save()
        r = self.client.get(reverse('dkron:auth'))
        self.assertEqual(r.status_code, 403)

        self.user.user_permissions.add(self._job_perm('can_use_dashboard'))
        r = self.client.get(reverse('dkron:auth'))
        self.assertEqual(r.status_code, 200)

    def test_resync_command(self):
        out = StringIO()
        err = StringIO()

        with mock.patch(
            'dkron.utils.resync_jobs',
            return_value=[
                ('job1', 'u', None),
                ('job2', 'd', None),
                ('job3', 'd', 'failed deletion'),
                ('job4', 'x', 'ignored, not an action'),
                ('job5', 'u', 'failed update'),
            ],
        ):
            management.call_command('resync_dkron', stdout=out, stderr=err)
            self.assertEqual(out.getvalue(), "Job job1 updated\nJob job2 delete\n")
            self.assertEqual(err.getvalue(), "Job job3 failed\nfailed deletion\nJob job5 failed\nfailed update\n")

    def test_model(self):
        j = models.Job.objects.create(name='job1')
        self.assertEqual(str(j), 'job1')

    def test_api_url(self):
        with self.settings(DKRON_URL='http://dkron'):
            utils.api_url.cache_clear()
            self.assertEqual(utils.api_url(), 'http://dkron/v1/')

        with self.settings(DKRON_URL='http://dkron/'):
            utils.api_url.cache_clear()
            self.assertEqual(utils.api_url(), 'http://dkron/v1/')

    def test_sync_job(self):
        j = models.Job.objects.create(name='job1')
        with mock.patch('requests.post') as mp:
            mp.return_value = mock.MagicMock(status_code=201)
            utils.sync_job(j)
            mp.assert_called_once_with(
                'http://dkron/v1/jobs',
                json={
                    'name': 'job1',
                    'tags': {'label': 'testapp:1'},
                    'metadata': {'cron': 'auto'},
                    'schedule': '',
                    'parent_job': None,
                    'executor_config': {'shell': 'false', 'command': ''},
                    'disabled': False,
                    'executor': 'shell',
                    'retries': 0,
                },
            )

            j.schedule = '@every 1h'
            j.command = 'echo test'
            j.enabled = False
            j.save()
            mp.reset_mock()
            utils.sync_job('job1')
            mp.assert_called_once_with(
                'http://dkron/v1/jobs',
                json={
                    'name': 'job1',
                    'tags': {'label': 'testapp:1'},
                    'metadata': {'cron': 'auto'},
                    'schedule': '@every 1h',
                    'executor_config': {'shell': 'false', 'command': 'echo test'},
                    'disabled': True,
                    'executor': 'shell',
                    'parent_job': None,
                    'retries': 0,
                },
            )

            j.use_shell = True
            j.schedule = '@parent other'
            j.save()
            mp.reset_mock()
            utils.sync_job('job1')
            mp.assert_called_once_with(
                'http://dkron/v1/jobs',
                json={
                    'name': 'job1',
                    'tags': {'label': 'testapp:1'},
                    'metadata': {'cron': 'auto'},
                    'schedule': '@manually',
                    'executor_config': {'shell': 'true', 'command': 'echo test'},
                    'disabled': True,
                    'executor': 'shell',
                    'parent_job': 'other',
                    'retries': 0,
                },
            )

            mp.reset_mock()
            mp.return_value = mock.MagicMock(status_code=500, text='Whatever')
            with self.assertRaisesMessage(utils.DkronException, '') as exc:
                utils.sync_job('job1')
            self.assertEqual(exc.exception.code, 500)
            self.assertEqual(exc.exception.message, 'Whatever')

    def test_delete_job(self):
        j = models.Job.objects.create(name='job1')
        with mock.patch('requests.delete') as mp:
            mp.return_value = mock.MagicMock(status_code=200)
            utils.delete_job(j)
            mp.assert_called_once_with('http://dkron/v1/jobs/job1')

            mp.reset_mock()
            mp.return_value = mock.MagicMock(status_code=500, text='Whatever')
            with self.assertRaisesMessage(utils.DkronException, '') as exc:
                utils.delete_job('job1')
            mp.assert_called_once_with('http://dkron/v1/jobs/job1')
            self.assertEqual(exc.exception.code, 500)
            self.assertEqual(exc.exception.message, 'Whatever')

    @mock.patch('requests.get')
    def test_resync_jobs(self, mp1):
        j1 = models.Job.objects.create(name='job1')
        j2 = models.Job.objects.create(name='job2')
        jobs = [
            {'name': 'job1', 'tags': {'label': 'testapp'}, 'metadata': {'cron': 'auto'}},
            {'name': 'job3', 'tags': {'label': 'testapp'}, 'metadata': {'cron': 'auto'}},
            {'name': 'job4', 'tags': {'label': 'testapp'}, 'metadata': {'cron': 'auto'}},
            {'name': 'job5', 'tags': {'label': 'testapp2'}, 'metadata': {'cron': 'auto'}},
            {'name': 'job6', 'tags': {}, 'metadata': {'cron': 'auto'}},
        ]
        mp1.return_value = mock.MagicMock(status_code=200, json=lambda: jobs)
        it = utils.resync_jobs()

        with mock.patch('dkron.utils.sync_job') as mp2, mock.patch('dkron.utils.delete_job') as mp3:
            el = next(it)
            mp1.assert_called_once_with('http://dkron/v1/jobs', params={'metadata[cron]': 'auto'})
            self.assertEqual(('job1', 'u', None), el)
            mp2.assert_called_once_with(j1, jobs[0])
            mp2.reset_mock()

            mp2.side_effect = utils.DkronException(666, 'looking for d/a/emon')
            el = next(it)
            self.assertEqual(('job2', 'u', 'looking for d/a/emon'), el)
            mp2.assert_called_once_with(j2, False)
            mp2.reset_mock()

            # no order in a set(), check for both
            el = next(it)
            self.assertEqual(('d', None), el[1:])
            self.assertIn(el[0], ('job3', 'job4'))
            mp3.assert_called_once_with(el[0])
            mp3.reset_mock()

            mp3.side_effect = utils.DkronException(666, 'looking for d/a/emon')
            el = next(it)
            self.assertEqual(el[1:], ('d', 'looking for d/a/emon'))
            self.assertIn(el[0], ('job3', 'job4'))
            mp3.assert_called_once_with(el[0])
            mp3.reset_mock()

            with self.assertRaises(StopIteration):
                # assert nothing left
                next(it)

    def test_admin__change_job_enabled(self):
        j1 = models.Job.objects.create(name='job1')
        ja = admin.JobAdmin(j1, self.site)

        self.assertTrue(j1.enabled)
        request = mock.MagicMock()
        with mock.patch('dkron.utils.sync_job') as mp:
            ja._change_job_enabled(request, models.Job.objects.all(), False)
            mp.assert_called_once_with(j1)
            j1.refresh_from_db()
            self.assertFalse(j1.enabled)
            request._messages.add.assert_not_called()

            mp.side_effect = utils.DkronException(666, 'looking for d/a/emon')
            ja._change_job_enabled(request, models.Job.objects.all(), True)
            request._messages.add.assert_called_once_with(
                40, 'Failed to sync job1 config with dkron - looking for d/a/emon', ''
            )
            # fails dkron update, but still updates DB, by design...
            j1.refresh_from_db()
            self.assertTrue(j1.enabled)

    def test_admin_change_job_enabled_disabled(self):
        j1 = models.Job.objects.create(name='job1')
        ja = admin.JobAdmin(j1, self.site)

        self.assertTrue(j1.enabled)
        request = mock.MagicMock()
        with mock.patch('dkron.admin.JobAdmin._change_job_enabled') as mp:
            _x = models.Job.objects.all()
            ja.disable_jobs(request, _x)
            mp.assert_called_once_with(request, _x, False)

            mp.reset_mock()
            ja.enable_jobs(request, _x)
            mp.assert_called_once_with(request, _x, True)

    def test_admin_save_model(self):
        j1 = models.Job.objects.create(name='job1')
        ja = admin.JobAdmin(j1, self.site)
        request = mock.MagicMock()
        with mock.patch('dkron.utils.sync_job') as mp:
            ja.save_model(request, j1, None, None)
            mp.assert_called_once_with(j1, job_update=None)
            request._messages.add.assert_not_called()

            mp.reset_mock()
            mp.side_effect = utils.DkronException(666, 'looking for d/a/emon')
            ja.save_model(request, j1, None, None)
            request._messages.add.assert_called_once_with(
                40, 'Failed to sync job1 config with dkron - looking for d/a/emon', ''
            )

    def test_admin_delete_model(self):
        request = mock.MagicMock()
        with mock.patch('dkron.utils.delete_job') as mp:
            j1 = models.Job.objects.create(name='job1')
            ja = admin.JobAdmin(j1, self.site)
            ja.delete_model(request, j1)
            mp.assert_called_once_with(j1)
            request._messages.add.assert_not_called()

            mp.reset_mock()
            mp.side_effect = utils.DkronException(666, 'looking for d/a/emon')
            j1 = models.Job.objects.create(name='job1')
            ja = admin.JobAdmin(j1, self.site)
            ja.delete_model(request, j1)
            request._messages.add.assert_called_once_with(
                40, 'Failed to delete job1 from dkron - looking for d/a/emon', ''
            )

    def test_admin_resync_button(self):
        resync_html = (
            '<a href="'
            + reverse('admin:dkron_job_resync')
            + '" class="override-change_list_object_tools change-list-object-tools-item">Resync jobs</a>'
        )
        self.user.is_staff = True
        self.user.save()
        self._login()
        r = self.client.get(reverse('admin:dkron_job_changelist'))
        self.assertEqual(r.status_code, 403)

        with mock.patch('dkron.utils.resync_jobs') as mp:
            self.user.user_permissions.add(self._job_perm('change_job'))
            r = self.client.get(reverse('admin:dkron_job_changelist'))
            self.assertNotContains(r, resync_html, status_code=200, html=True)
            r = self.client.get(reverse('admin:dkron_job_resync'))
            self.assertEqual(r.status_code, 403)

            self.user.user_permissions.add(self._job_perm('can_use_dashboard'))
            r = self.client.get(reverse('admin:dkron_job_changelist'))
            self.assertContains(r, resync_html, status_code=200, html=True)

            mp.return_value = [
                ('job1', 'u', None),
                ('job2', 'd', None),
                ('job3', 'd', 'failed deletion'),
                ('job5', 'u', 'failed update'),
            ]
            r = self.client.get(
                reverse('admin:dkron_job_resync') + '?_changelist_filters=enabled__exact%3d1', follow=True
            )
            self.assertRedirects(r, reverse('admin:dkron_job_changelist') + '?enabled__exact=1')  # preserved filters
            # Temporary
            self.assertContains(
                r,
                '''
                <ul class="messagelist">
                    <li class="error">Failed deletion</li>
                    <li class="error">Failed update</li>
                    <li class="info">1 jobs updated and 1 deleted</li>
                </ul>
                ''',
                status_code=200,
                html=True,
            )

    def test_webhook(self):
        with override_settings(DKRON_TOKEN=None):
            r = self.client.get(reverse('dkron_api:webhook'))
            self.assertEqual(r.status_code, 404)

        r = self.client.get(reverse('dkron_api:webhook'))
        self.assertEqual(r.status_code, 400)

        r = self.client.post(reverse('dkron_api:webhook'))
        self.assertEqual(r.status_code, 400)

        r = self.client.post(reverse('dkron_api:webhook'), data='1\n2', content_type='not_form_data')
        self.assertEqual(r.status_code, 400)

        r = self.client.post(reverse('dkron_api:webhook'), data='1\n2\n3', content_type='not_form_data')
        self.assertEqual(r.status_code, 403)

        r = self.client.post(reverse('dkron_api:webhook'), data='test\n2\n3', content_type='not_form_data')
        self.assertEqual(r.status_code, 404)

        j = models.Job.objects.create(name='job1')
        self.assertFalse(j.last_run_success)

        r = self.client.post(reverse('dkron_api:webhook'), data='test\njob1\n3', content_type='not_form_data')
        self.assertEqual(r.status_code, 200)
        j.refresh_from_db()
        self.assertFalse(j.last_run_success)

        r = self.client.post(reverse('dkron_api:webhook'), data='test\njob1\ntrue', content_type='not_form_data')
        self.assertEqual(r.status_code, 200)
        j.refresh_from_db()
        self.assertTrue(j.last_run_success)

    def test_webhook_notify(self):
        ev = notify_models.Event.objects.get(name='dkron_failed_job')
        notify_models.Subscription.objects.create(
            event=ev, service=notify_models.Subscription.Service.SLACK, target='@elon'
        )

        j = models.Job.objects.create(name='job1', notify_on_error=False)

        r = self.client.post(reverse('dkron_api:webhook'), data='test\njob1\n3', content_type='not_form_data')
        self.assertEqual(r.status_code, 200)
        j.refresh_from_db()
        self.assertFalse(j.last_run_success)
        self.assertEqual(notify_models.Notification.objects.count(), 0)

        j.notify_on_error = True
        j.save()
        r = self.client.post(reverse('dkron_api:webhook'), data='test\njob1\n3', content_type='not_form_data')
        self.assertEqual(r.status_code, 200)
        j.refresh_from_db()
        self.assertFalse(j.last_run_success)
        self.assertEqual(notify_models.Notification.objects.count(), 1)
        self.assertEqual(
            notify_models.Notification.objects.first().message,
            ':red-pipeline: dkron job *job1* <http://testserver/dkron/proxy/ui/#/jobs/job1/show/executions|failed>',
        )

        r = self.client.post(reverse('dkron_api:webhook'), data='test\njob1\ntrue', content_type='not_form_data')
        self.assertEqual(r.status_code, 200)
        j.refresh_from_db()
        self.assertTrue(j.last_run_success)
        self.assertEqual(notify_models.Notification.objects.count(), 1)

    @mock.patch('time.time', return_value=1)
    @mock.patch('requests.post')
    def test_run_async(self, mp, tp):
        mpp = mock.MagicMock()
        mp.return_value = mpp
        # Because of the way mock attributes are stored you can’t directly attach a PropertyMock to a mock object
        # https://docs.python.org/3/library/unittest.mock.html#raising-exceptions-on-attribute-access
        type(mpp).status_code = mock.PropertyMock(side_effect=[201, 200])
        x = utils.run_async('somecommand', 'arg1', kwarg='value', enable=True)
        mp.assert_has_calls(
            (
                mock.call(
                    'http://dkron/v1/jobs',
                    json={
                        'name': 'tmp_somecommand_1',
                        'tags': {'label': 'testapp:1'},
                        'schedule': '@manually',
                        'executor_config': {'command': 'python ./manage.py somecommand arg1 --kwarg value --enable'},
                        'metadata': {'temp': 'true'},
                        'disabled': False,
                        'executor': 'shell',
                    },
                    params={'runoncreate': 'true'},
                ),
            )
        )
        self.assertEqual(x, ('tmp_somecommand_1', '/dkron/proxy/ui/#/jobs/tmp_somecommand_1/show/executions'))

    @mock.patch('after_response.decorators.AFTER_RESPONSE_IMMEDIATE', new_callable=mock.PropertyMock, return_value=True)
    @mock.patch('dkron.utils.requests')
    @mock.patch('dkron.utils.call_command')
    def test_run_async_fallback(self, ccp, req_mock, __not_used):
        # force ConnectionError (to fallback) instead of using invalid URL
        req_mock.ConnectionError = Exception
        req_mock.post.side_effect = req_mock.ConnectionError
        x = utils.run_async('somecommand', 'arg1', kwarg='value')
        self.assertIsNone(x)
        ccp.assert_called_with('somecommand', 'arg1', kwarg='value')

    @mock.patch('dkron.utils._get')
    @mock.patch('dkron.utils.delete_job')
    def test_cleanup_command(self, dj_mock, get_mock):
        err = StringIO()
        test_now = timezone.now()

        jobs = [
            {'name': f'tmp_job1_{int((test_now - timezone.timedelta(days=1)).timestamp())}'},
            {'name': f'tmp_job2_{int((test_now - timezone.timedelta(days=5)).timestamp())}'},
        ]
        get_mock.return_value = mock.MagicMock(json=lambda: jobs)

        out = StringIO()
        with mock.patch('django.utils.timezone.now', return_value=test_now):
            management.call_command('cleanup_dkron', stdout=out, stderr=err)
        self.assertIn('Deleting 0 jobs (out of 2)', out.getvalue())
        self.assertEqual(err.getvalue(), '')
        get_mock.assert_called_once_with('jobs', params={'metadata[temp]': 'true'})

        get_mock.reset_mock()
        out = StringIO()
        with mock.patch('django.utils.timezone.now', return_value=test_now):
            management.call_command('cleanup_dkron', days=3, stdout=out, stderr=err)
        self.assertIn('Deleting 1 jobs (out of 2)', out.getvalue())
        self.assertEqual(err.getvalue(), '')
        get_mock.assert_called_once_with('jobs', params={'metadata[temp]': 'true'})
        dj_mock.assert_called_once_with(jobs[1]['name'])

        get_mock.reset_mock()
        dj_mock.reset_mock()
        out = StringIO()
        with mock.patch('django.utils.timezone.now', return_value=test_now):
            management.call_command('cleanup_dkron', days=0, stdout=out, stderr=err)
        self.assertIn('Deleting 2 jobs (out of 2)', out.getvalue())
        self.assertEqual(err.getvalue(), '')
        get_mock.assert_called_once_with('jobs', params={'metadata[temp]': 'true'})
        # called twice - on both jobs
        self.assertEqual(dj_mock.call_count, 2)

    @override_settings(DKRON_SERVER=False)
    @mock.patch('os.execv')
    def test_run_dkron(self, exec_mock):
        err = StringIO()
        out = StringIO()

        # skip download
        tmp = tempfile.mkdtemp()
        exe_name = os.path.join(tmp, 'dkron.exe' if platform.system() == 'Windows' else 'dkron')
        with open(exe_name, 'wb') as f:
            f.write(b'1')

        with mock.patch('tempfile.mkdtemp', return_value=tmp):
            management.call_command('run_dkron', stdout=out, stderr=err)

        exec_mock.assert_called_once_with(exe_name, [exe_name, 'agent', '--tag', 'label=testapp'])

    @mock.patch('requests.request')
    def test_proxy_auth(self, mp1):
        self.user.is_superuser = True
        self.user.save()
        r = self.client.get(reverse('dkron:proxy'))
        self.assertEqual(302, r.status_code)

        mp1.return_value = mock.MagicMock(content='', status_code=202)
        self._login()
        r = self.client.get(reverse('dkron:proxy'))
        self.assertEqual(202, r.status_code)

        self.user.is_superuser = False
        self.user.is_staff = True
        self.user.save()
        r = self.client.get(reverse('dkron:proxy'))
        self.assertEqual(302, r.status_code)

        self.user.user_permissions.add(self._job_perm('can_use_dashboard'))
        r = self.client.get(reverse('dkron:proxy'))
        self.assertEqual(202, r.status_code)

    @mock.patch('requests.request')
    def test_proxy_view(self, mp1):
        self.user.is_superuser = True
        self.user.save()
        self._login()

        mp1.return_value = mock.MagicMock(content='raw content', status_code=202)
        r = self.client.get(reverse('dkron:proxy'))
        self.assertEqual(202, r.status_code)
        self.assertEqual(b'raw content', r.content)

        mp1.return_value = mock.MagicMock(
            content='raw content', status_code=302, headers={'Location': 'whatever', 'X-Custom': 'untouched'}
        )
        r = self.client.get(reverse('dkron:proxy'))
        self.assertEqual(302, r.status_code)
        self.assertEqual(b'raw content', r.content)
        # relative path appended
        self.assertEqual(reverse('dkron:proxy') + 'whatever', r.headers['location'])
        # non-specific header remains untouched
        self.assertEqual('untouched', r.headers['x-custom'])

        mp1.return_value = mock.MagicMock(
            content='', status_code=302, headers={'Location': '/whatever', 'Content-Encoding': 'invalid'}
        )
        r = self.client.get(reverse('dkron:proxy'))
        self.assertEqual(302, r.status_code)
        # leading / is trimmed
        self.assertEqual(reverse('dkron:proxy') + 'whatever', r.headers['location'])
        # some headers from upstream are dropped
        self.assertIsNone(r.headers.get('Content-Encoding'))
