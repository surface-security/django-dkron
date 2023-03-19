from unittest import mock
from django.urls import reverse
from django.test import override_settings

from dkron import models, utils

from .test_generic import Test as GenericTest


@override_settings(DKRON_PATH='/dkron/proxy/ui/', DKRON_URL='http://dkron', DKRON_NAMESPACE='wtv')
class Test(GenericTest):
    def test_sync_job(self, job_prefix=''):
        super().test_sync_job(job_prefix='wtv_')

    def test_delete_job(self, job_prefix=''):
        super().test_delete_job(job_prefix='wtv_')

    @mock.patch('requests.get')
    def test_resync_jobs(self, mp1):
        j1 = models.Job.objects.create(name='job1')
        j2 = models.Job.objects.create(name='job2')
        jobs = [
            {'name': 'wtv_job1', 'tags': {'label': 'testapp'}, 'metadata': {'cron': 'auto'}},
            {'name': 'wtv_job3', 'tags': {'label': 'testapp'}, 'metadata': {'cron': 'auto'}},
            # ignore, not wtv namespace
            {'name': 'ign_job4', 'tags': {'label': 'testapp'}, 'metadata': {'cron': 'auto'}},
            # skipped, wrong label
            {'name': 'wtv_job5', 'tags': {'label': 'testapp2'}, 'metadata': {'cron': 'auto'}},
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
            self.assertEqual(('job3', 'd', None), el)
            mp3.assert_called_once_with('job3')
            mp3.reset_mock()

            with self.assertRaises(StopIteration):
                # assert nothing left
                next(it)

    def test_webhook(self, job_prefix=''):
        super().test_webhook(job_prefix='wtv_')

    def test_webhook_namespace_mismatch(self):
        j = models.Job.objects.create(name='job1')
        self.assertFalse(j.last_run_success)

        r = self.client.post(reverse('dkron_api:webhook'), data='test\njob1\ntrue', content_type='not_form_data')
        self.assertEqual(r.status_code, 404)

        r = self.client.post(reverse('dkron_api:webhook'), data='test\nwtv_job1\ntrue', content_type='not_form_data')
        self.assertEqual(r.status_code, 200)
        j.refresh_from_db()
        self.assertTrue(j.last_run_success)

    def test_webhook_notify(self, job_prefix=''):
        super().test_webhook_notify(job_prefix='wtv_')

    def test_run_async(self, job_prefix=''):
        super().test_run_async(job_prefix='wtv_')
