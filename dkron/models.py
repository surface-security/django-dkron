from django.db import models


class Job(models.Model):
    name = models.CharField(max_length=255, null=False, blank=False, unique=True)
    schedule = models.CharField(
        max_length=255,
        null=False,
        blank=False,
        help_text='https://dkron.io/usage/cron-spec/ or "@parent JOBNAME" for dependent jobs',
    )
    # if we add more executors (besides the default "shell"), this needs to change
    command = models.CharField(max_length=255, null=False, blank=False)
    description = models.CharField(max_length=255, null=True, blank=True)
    enabled = models.BooleanField(default=True)
    use_shell = models.BooleanField(default=False, help_text='/bin/sh -c "..."')
    last_run_date = models.DateTimeField(null=True, blank=True, editable=False)
    last_run_success = models.BooleanField(null=True, editable=False)
    notify_on_error = models.BooleanField(default=True)
    retries = models.IntegerField(default=0)

    def __str__(self):
        return self.name

    class Meta:
        permissions = (("can_use_dashboard", "Can use the dashboard"),)
