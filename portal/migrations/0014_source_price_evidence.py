from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('portal','0013_product_tax_and_order_amounts')]
    operations = [
        migrations.AddField(model_name='sourceproduct', name='item_url',
            field=models.URLField('صفحهٔ قیمت در منبع', max_length=2000, blank=True, default='')),
        migrations.AlterField(model_name='sourceproduct', name='review_status',
            field=models.CharField('وضعیت قیمت', max_length=20, default='new', choices=[
                ('new','دریافت نشده'),('pending','منتظر تأیید'),('applied','اعمال شده'),
                ('unchanged','بدون تغییر'),('conflict','نیازمند بررسی'),('rejected','رد شده'),
                ('unavailable','ناموجود در منبع'),('missing','شناسه در فهرست منبع پیدا نشد')])),
    ]
