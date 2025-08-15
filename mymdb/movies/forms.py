from django import forms
from .models import Review

class ReviewForm(forms.ModelForm):
    title = forms.CharField(max_length=200, required=False, help_text="Optional.")
    body = forms.CharField(widget=forms.Textarea(attrs={'rows': 4}), required=True, label="Write your review")

    class Meta:
        model = Review
        fields = ['title', 'body']
