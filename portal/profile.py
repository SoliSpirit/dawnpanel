import base64,hashlib,re
from django import forms
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.utils import timezone
from cryptography.fernet import Fernet
import jdatetime


def profile_cipher():
    key=settings.PROFILE_ENCRYPTION_KEY
    if not key:
        if settings.PRODUCTION: raise ImproperlyConfigured('Private profile encryption key is required')
        key=base64.urlsafe_b64encode(hashlib.sha256(('local-profile:'+settings.SECRET_KEY).encode()).digest())
    return Fernet(key)


def digits(value):
    return value.translate(str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩','01234567890123456789'))


class ProfileForm(forms.Form):
    first_name=forms.CharField(label='نام',max_length=150,required=False,widget=forms.TextInput(attrs={'autocomplete':'given-name'}))
    last_name=forms.CharField(label='نام خانوادگی',max_length=150,required=False,widget=forms.TextInput(attrs={'autocomplete':'family-name'}))
    email=forms.EmailField(label='ایمیل',max_length=254,required=False,widget=forms.EmailInput(attrs={'autocomplete':'email','dir':'ltr'}))
    national_code=forms.CharField(label='کد ملی',required=False,max_length=10,help_text='۱۰ رقم؛ برای نگه‌داشتن کد قبلی، خالی بگذارید.',widget=forms.TextInput(attrs={'inputmode':'numeric','dir':'ltr','autocomplete':'off'}))
    clear_national_code=forms.BooleanField(label='حذف کد ملی ذخیره‌شده',required=False)
    birth_date=forms.CharField(label='تاریخ تولد شمسی',required=False,max_length=10,help_text='سال/ماه/روز، مثلاً ۱۳۸۰/۰۱/۱۵',widget=forms.TextInput(attrs={'inputmode':'numeric','dir':'ltr','placeholder':'1380/01/15'}))
    province=forms.CharField(label='استان',max_length=80,required=False,widget=forms.TextInput(attrs={'autocomplete':'address-level1'}))
    city=forms.CharField(label='شهر',max_length=80,required=False,widget=forms.TextInput(attrs={'autocomplete':'address-level2'}))

    def clean_national_code(self):
        code=digits(self.cleaned_data['national_code'].strip())
        if not code:return ''
        if not re.fullmatch('[0-9]{10}',code) or len(set(code))==1:
            raise forms.ValidationError('کد ملی معتبرِ ۱۰ رقمی وارد کنید.')
        remainder=sum(int(code[i])*(10-i) for i in range(9))%11
        if int(code[-1])!=(remainder if remainder<2 else 11-remainder):
            raise forms.ValidationError('رقم کنترلی کد ملی صحیح نیست.')
        return code

    def clean_birth_date(self):
        value=digits(self.cleaned_data['birth_date'].strip()).replace('-','/')
        if not value:return None
        try:
            if not re.fullmatch(r'[0-9]{4}/[0-9]{1,2}/[0-9]{1,2}',value):raise ValueError
            year,month,day=map(int,value.split('/'))
            birthday=jdatetime.date(year,month,day).togregorian()
            if year<1200 or birthday>timezone.localdate():raise ValueError
            return birthday
        except (ValueError,OverflowError):
            raise forms.ValidationError('تاریخ شمسی معتبر و پیش از امروز وارد کنید.') from None
