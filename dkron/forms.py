from django import forms


class JobForm(forms.ModelForm):
    def clean_schedule(self):
        data = self.cleaned_data["schedule"]
        if data.startswith("*"):
            raise forms.ValidationError("Job schedule cannot start with * as this will schedule a job to start every second and can have unintended consequences.")
        return data
