from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('portal', '0011_supplier_price_controls')]
    operations = [
        migrations.AddField(model_name='sourceproduct', name='family_name',
            field=models.CharField('نام خانواده محصول', max_length=500, blank=True, default='')),
        migrations.AddField(model_name='sourceproduct', name='family_summary',
            field=models.TextField('معرفی خانواده محصول', blank=True, default='')),
    ]
