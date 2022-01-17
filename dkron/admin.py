import re
from urllib.parse import parse_qsl

from django import forms
from django.contrib import admin
from django.http.response import HttpResponseForbidden, HttpResponseRedirect
from django.templatetags.static import static
from django.urls import reverse
from django.utils.html import format_html
from dkron import models, utils


class JobAdminForm(forms.ModelForm):
    NAME_RE = re.compile(r'^[a-zA-Z0-9\-_]+$')

    def clean_name(self):
        if self.NAME_RE.match(self.cleaned_data['name']) is None:
            raise forms.ValidationError('Invalid value')
        return self.cleaned_data['name'].lower()

    def clean_schedule(self):
        # crappy way to validate it but oh well...
        j = models.Job(
            name='tmp_test_job', schedule=self.cleaned_data['schedule'], enabled=False, command='echo validator'
        )
        try:
            utils.sync_job(j)
        except utils.DkronException:
            raise forms.ValidationError('Invalid value')
        else:
            try:
                utils.delete_job(j)
            except Exception:
                # don't really care, just cleanup
                pass
        return self.cleaned_data['schedule']


@admin.register(models.Job)
class JobAdmin(admin.ModelAdmin):
    form = JobAdminForm
    list_display = (
        'name',
        'schedule',
        'command',
        'description',
        'enabled',
        'notify_on_error',
        'get_last_run',
        'get_dkron_link',
    )
    list_display_links = ('name',)
    search_fields = ('name', 'schedule', 'command', 'description')
    list_filter = ('name', 'schedule', 'enabled', 'last_run_success', 'notify_on_error')
    actions = ['disable_jobs', 'enable_jobs']

    def has_dashboard_permission(self, request):
        return request.user.has_perm('dkron.can_use_dashboard')

    def _change_job_enabled(self, request, queryset, value):
        queryset.update(enabled=value)
        for job in queryset:
            try:
                utils.sync_job(job)
            except utils.DkronException as e:
                self.message_user(request, f'Failed to sync {job.name} config with dkron - {str(e)}', 'ERROR')

    def get_dkron_link(self, obj):
        return format_html(
            '''
            <a href="{}" target="_blank" rel="noopener">
            <i class="fas fa-external-link-alt"></i>
            </a>
            ''',
            utils.job_executions(obj.name),
        )

    get_dkron_link.short_description = 'Dkron Link'

    def get_last_run(self, obj):
        if obj.last_run_date is None:
            return None
        return format_html(
            '{} <img src="{}">',
            obj.last_run_date.strftime('%d/%m/%Y %H:%M'),
            static('admin/img/icon-{}.svg'.format('yes' if obj.last_run_success else 'no')),
        )

    get_last_run.short_description = 'Last Run'
    get_last_run.admin_order_field = 'last_run_date'

    def disable_jobs(self, request, queryset):
        self._change_job_enabled(request, queryset, False)

    disable_jobs.short_description = 'Disable selected jobs'

    def enable_jobs(self, request, queryset):
        self._change_job_enabled(request, queryset, True)

    enable_jobs.short_description = 'Enable selected jobs'

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        try:
            utils.sync_job(obj, job_update=None)
        except utils.DkronException as e:
            self.message_user(request, f'Failed to sync {obj.name} config with dkron - {str(e)}', 'ERROR')

    def delete_model(self, request, obj):
        super().delete_model(request, obj)
        try:
            utils.delete_job(obj)
        except utils.DkronException as e:
            self.message_user(request, f'Failed to delete {obj.name} from dkron - {str(e)}', 'ERROR')

    def resync(self, request):
        if not self.has_dashboard_permission(request):
            return HttpResponseForbidden()
        c = [0, 0]
        for _, action, result in utils.resync_jobs():
            if result:
                self.message_user(request, result, 'ERROR')
            else:
                if action == 'u':
                    c[0] += 1
                else:
                    c[1] += 1

        self.message_user(request, '%d jobs updated and %d deleted' % tuple(c))
        post_url = reverse('admin:dkron_job_changelist', current_app=self.admin_site.name)
        preserved_filters = self.get_preserved_filters(request)
        preserved_filters = dict(parse_qsl(preserved_filters)).get('_changelist_filters')
        if preserved_filters:
            post_url = '%s?%s' % (post_url, preserved_filters)
        return HttpResponseRedirect(post_url)

    def get_urls(self):
        from django.urls import path

        urls = super().get_urls()
        urls.insert(0, path('resync/', self.admin_site.admin_view(self.resync), name='dkron_job_resync'))
        return urls

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        extra_context['has_dashboard_permission'] = self.has_dashboard_permission(request)
        extra_context['has_change_permission'] = self.has_change_permission(request)
        return super().changelist_view(request, extra_context)
