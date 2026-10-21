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
    picture=forms.FileField(label='آپلود عکس محصول',required=False,help_text='JPG، PNG یا WebP تا ۵ مگابایت؛ تصویر بهینه و بدون اطلاعات اضافی ذخیره می‌شود.')
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

def save_product_picture(product,form):
    picture=form.cleaned_data.get('picture')
    if picture:
        visual,_=ProductVisual.objects.get_or_create(product_id=product.pk,defaults={'image':''})
        visual.image=picture
        visual.alt_text=form.cleaned_data.get('picture_alt','')
        visual.save()
    elif form.cleaned_data.get('remove_picture'):
        ProductVisual.objects.filter(product_id=product.pk).delete()
    else:
        ProductVisual.objects.filter(product_id=product.pk).update(alt_text=form.cleaned_data.get('picture_alt',''))
