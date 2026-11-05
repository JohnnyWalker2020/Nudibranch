from django import forms
from .models import ParameterLog, Animal, AnimalGroup, ParameterType


class QuickParameterLogForm(forms.ModelForm):
    """Mobile-friendly quick add form for water parameters."""
    class Meta:
        model = ParameterLog
        fields = ['parameter_type', 'value', 'notes', 'measured_at']
        widgets = {
            'parameter_type': forms.Select(attrs={
                'class': 'w-full px-4 py-3 bg-slate-800 border border-slate-700 rounded-xl text-white focus:outline-none focus:ring-2 focus:ring-cyan-500 text-lg'
            }),
            'value': forms.NumberInput(attrs={
                'class': 'w-full px-4 py-3 bg-slate-800 border border-slate-700 rounded-xl text-white focus:outline-none focus:ring-2 focus:ring-cyan-500 text-2xl font-bold tracking-wide text-center',
                'placeholder': '0.00',
                'step': 'any',
                'inputmode': 'decimal',
            }),
            'notes': forms.TextInput(attrs={
                'class': 'w-full px-4 py-2 bg-slate-800 border border-slate-700 rounded-xl text-slate-300 focus:outline-none focus:ring-2 focus:ring-cyan-500 text-sm',
                'placeholder': 'Optional note (e.g. before water change)'
            }),
            'measured_at': forms.DateTimeInput(attrs={
                'class': 'w-full px-4 py-2 bg-slate-800 border border-slate-700 rounded-xl text-slate-400 focus:outline-none focus:ring-2 focus:ring-cyan-500 text-sm',
                'type': 'datetime-local'
            })
        }


class AnimalForm(forms.ModelForm):
    class Meta:
        model = Animal
        fields = ['name', 'species', 'groups', 'count', 'acquired_date', 'status', 'photo', 'notes']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'w-full px-4 py-2.5 bg-slate-800 border border-slate-700 rounded-xl text-white'}),
            'species': forms.TextInput(attrs={'class': 'w-full px-4 py-2.5 bg-slate-800 border border-slate-700 rounded-xl text-white'}),
            'groups': forms.SelectMultiple(attrs={'class': 'w-full px-4 py-2.5 bg-slate-800 border border-slate-700 rounded-xl text-white'}),
            'count': forms.NumberInput(attrs={'class': 'w-full px-4 py-2.5 bg-slate-800 border border-slate-700 rounded-xl text-white'}),
            'acquired_date': forms.DateInput(attrs={'class': 'w-full px-4 py-2.5 bg-slate-800 border border-slate-700 rounded-xl text-white', 'type': 'date'}),
            'status': forms.Select(attrs={'class': 'w-full px-4 py-2.5 bg-slate-800 border border-slate-700 rounded-xl text-white'}),
            'photo': forms.FileInput(attrs={'class': 'w-full px-4 py-2 bg-slate-800 border border-slate-700 rounded-xl text-slate-300'}),
            'notes': forms.Textarea(attrs={'class': 'w-full px-4 py-2 bg-slate-800 border border-slate-700 rounded-xl text-slate-300', 'rows': 3}),
        }
