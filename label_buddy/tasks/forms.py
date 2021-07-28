from django import forms

from .models import Task

class TaskForm(forms.ModelForm):

    file = forms.FileField(label='', widget=forms.FileInput(attrs={'id': 'import-file', 'onchange': 'checkExtension(this)'}))
    class Meta:
        model = Task
        fields = [
            "file",
        ]

    # to check if file is in correct format
    # def clean(self):
    #     cleaned_data = self.cleaned_data

    #     if True:
    #         raise forms.ValidationError("You have failed validation!")
    #     else:
    #         return cleaned_data 