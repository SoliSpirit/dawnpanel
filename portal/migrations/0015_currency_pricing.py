import django.core.validators
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('portal','0014_source_price_evidence')]
    operations = [
        migrations.CreateModel(name='CurrencyPricing',fields=[
            ('currency',models.OneToOneField(db_constraint=False,on_delete=django.db.models.deletion.CASCADE,
                primary_key=True,related_name='fx',serialize=False,to='portal.currency')),
            ('source',models.CharField(choices=[('manual','نرخ پایهٔ دستی'),('nobitex','نوبیتکس · بازار رمزارز'),
                ('nerkhara','نرخ‌آرا · بازار آزاد ارز')],default='manual',max_length=12)),
            ('spread_mode',models.CharField(choices=[('fixed','مبلغ ثابت به تومان'),('percent','درصد از نرخ مرجع')],default='fixed',max_length=8)),
            ('sell_extra',models.DecimalField(decimal_places=4,default=0,max_digits=16,validators=[django.core.validators.MinValueValidator(0)])),
            ('buy_less',models.DecimalField(decimal_places=4,default=0,max_digits=16,validators=[django.core.validators.MinValueValidator(0)])),
            ('quote_key',models.CharField(blank=True,default='',editable=False,max_length=40)),
            ('market_bid',models.DecimalField(decimal_places=8,editable=False,max_digits=25,null=True)),
            ('market_ask',models.DecimalField(decimal_places=8,editable=False,max_digits=25,null=True)),
            ('observed_at',models.DateTimeField(editable=False,null=True)),
            ('checked_at',models.DateTimeField(editable=False,null=True)),
            ('last_error',models.CharField(blank=True,default='',editable=False,max_length=200)),
        ]),
    ]
