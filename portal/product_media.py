import io, uuid, warnings
from django import forms
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils.html import format_html
from PIL import Image, ImageOps, UnidentifiedImageError
from .models import Product, ProductVisual

MAX_BYTES=5*1024*1024
MAX_PIXELS=16_000_000

def normalize_product_image(upload):
    if upload.size>MAX_BYTES:
        raise forms.ValidationError('حجم تصویر باید کمتر از ۵ مگابایت باشد.')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(upload) as image:
                if image.format not in {'JPEG','PNG','WEBP'}:
                    raise forms.ValidationError('فقط تصویر JPG، PNG یا WebP مجاز است.')
                if image.width*image.height>MAX_PIXELS:
                    raise forms.ValidationError('ابعاد تصویر بیش از حد بزرگ است؛ حداکثر ۱۶ مگاپیکسل.')
                image.verify()
            upload.seek(0)
            with Image.open(upload) as source:
                image=ImageOps.exif_transpose(source).convert('RGB')
                image.thumbnail((1600,1600))
                output=io.BytesIO()
                image.save(output,format='WEBP',quality=84,method=4)
        return SimpleUploadedFile(uuid.uuid4().hex+'.webp',output.getvalue(),content_type='image/webp')
    except (UnidentifiedImageError,OSError,ValueError,Image.DecompressionBombError,Image.DecompressionBombWarning) as error:
        raise forms.ValidationError('فایل تصویر معتبر نیست.') from error

class ProductImageForm(forms.ModelForm):
    picture=forms.FileField(label='عکس محصول در حالت روز',required=False,help_text='JPG، PNG یا WebP تا ۵ مگابایت؛ تصویر بهینه و بدون اطلاعات اضافی ذخیره می‌شود.')
    night_picture=forms.FileField(label='عکس محصول در حالت شب',required=False,help_text='نسخه جداگانه مخصوص شب؛ بدون این عکس، تصویر شبِ دسته‌بندی نمایش داده می‌شود.')
    remove_night_picture=forms.BooleanField(label='حذف فقط عکس شب',required=False)
    picture_alt=forms.CharField(label='توضیح عکس برای سئو و دسترس‌پذیری',required=False,max_length=160)
    remove_picture=forms.BooleanField(label='حذف عکس فعلی از محصول',required=False)
    class Meta:
        model=Product
        fields='__all__'
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        if self.instance.pk and self.instance.visual:
            self.fields['picture_alt'].initial=self.instance.visual.alt_text
    def clean_picture(self):
        upload=self.cleaned_data.get('picture')
        return normalize_product_image(upload) if upload else None
    def clean_night_picture(self):
        upload=self.cleaned_data.get('night_picture')
        return normalize_product_image(upload) if upload else None

def save_product_picture(product,form):
    picture=form.cleaned_data.get('picture')
    night_picture=form.cleaned_data.get('night_picture')
    if form.cleaned_data.get('remove_picture'):
        ProductVisual.objects.filter(product_id=product.pk).delete()
        product.__dict__.pop('_visual_cache',None)
        return
    visual=ProductVisual.objects.filter(product_id=product.pk).first()
    if picture or night_picture or visual:
        visual=visual or ProductVisual(product_id=product.pk,image='')
        if picture: visual.image=picture
        if night_picture: visual.night_image=night_picture
        elif form.cleaned_data.get('remove_night_picture'): visual.night_image=''
        visual.alt_text=form.cleaned_data.get('picture_alt','')
        visual.save()
    product.__dict__.pop('_visual_cache',None)
