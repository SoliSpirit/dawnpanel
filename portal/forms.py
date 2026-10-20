from django import forms
from .models import Ticket
class PhoneForm(forms.Form):
    phone=forms.CharField(label='شماره موبایل',max_length=20,widget=forms.TextInput(attrs={'inputmode':'tel','autocomplete':'tel','placeholder':'۰۹۱۲۱۲۳۴۵۶۷','dir':'ltr'}))
class CodeForm(forms.Form):
    code=forms.RegexField(r'^[0-9]{6}$',label='کد شش رقمی',widget=forms.TextInput(attrs={'inputmode':'numeric','autocomplete':'one-time-code','maxlength':6,'dir':'ltr'}))
class OrderForm(forms.Form):
    quantity=forms.IntegerField(label='تعداد',min_value=1,max_value=100000000)
    target=forms.CharField(label='لینک یا شناسه مقصد',max_length=1500,required=False,widget=forms.TextInput(attrs={'dir':'ltr','placeholder':'https://…'}))
class TicketForm(forms.ModelForm):
    body=forms.CharField(label='پیام',min_length=5,max_length=5000,widget=forms.Textarea)
    class Meta: model=Ticket;fields=['subject','priority']
class ReplyForm(forms.Form):
    body=forms.CharField(label='پاسخ',min_length=1,max_length=5000,widget=forms.Textarea)
class ChargeForm(forms.Form):
    amount=forms.IntegerField(label='مبلغ شارژ به تومان',min_value=1000,max_value=100000000)

class GiftForm(forms.Form):
    code=forms.CharField(label='کد هدیه',max_length=50,widget=forms.TextInput(attrs={'dir':'ltr'}))
