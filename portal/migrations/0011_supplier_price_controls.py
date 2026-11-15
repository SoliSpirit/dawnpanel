import django.core.validators
from django.db import migrations, models


def source_defaults(apps, schema_editor):
    settings = apps.get_model('portal','SourceSyncSettings')
    for source in ('denapanel','premstore'):
        settings.objects.using(schema_editor.connection.alias).get_or_create(source=source)


class Migration(migrations.Migration):
    dependencies = [('portal','0010_sourceproduct')]
    operations = [
        migrations.CreateModel(name='SourceSyncSettings',fields=[
            ('id',models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name='ID')),
            ('source',models.CharField(choices=[('denapanel','دناپنل'),('premstore','پریم‌استور')],max_length=30,unique=True,verbose_name='منبع')),
            ('enabled',models.BooleanField(default=False,verbose_name='دریافت زمان‌بندی‌شده')),
            ('require_approval',models.BooleanField(default=True,verbose_name='نیاز به تأیید پیش از اعمال')),
            ('interval_minutes',models.PositiveIntegerField(default=60,validators=[django.core.validators.MinValueValidator(15)],verbose_name='فاصله دریافت به دقیقه')),
            ('max_change_percent',models.PositiveIntegerField(default=25,validators=[django.core.validators.MinValueValidator(1)],verbose_name='حداکثر تغییر برای اعمال خودکار (%)')),
            ('last_attempt',models.DateTimeField(blank=True,editable=False,null=True,verbose_name='آخرین تلاش')),
            ('last_success',models.DateTimeField(blank=True,editable=False,null=True,verbose_name='آخرین دریافت موفق')),
            ('running_until',models.DateTimeField(blank=True,editable=False,null=True)),
            ('last_error',models.CharField(blank=True,editable=False,max_length=200,verbose_name='خطای آخر')),
        ],options={'verbose_name':'تنظیم دریافت قیمت','verbose_name_plural':'تنظیمات دریافت قیمت'}),
        migrations.AlterModelOptions(name='sourceproduct',options={'verbose_name':'قیمت منبع محصول','verbose_name_plural':'بررسی قیمت محصولات'}),
        migrations.AddField(model_name='sourceproduct',name='available',field=models.BooleanField(default=False,verbose_name='موجود در منبع')),
        migrations.AddField(model_name='sourceproduct',name='observed_at',field=models.DateTimeField(blank=True,null=True,verbose_name='آخرین دریافت معتبر')),
        migrations.AddField(model_name='sourceproduct',name='price_baseline',field=models.JSONField(default=dict,editable=False)),
        migrations.AddField(model_name='sourceproduct',name='proposed_price',field=models.PositiveBigIntegerField(blank=True,null=True,verbose_name='قیمت پیشنهادی تومان')),
        migrations.AddField(model_name='sourceproduct',name='review_status',field=models.CharField(choices=[
            ('new','دریافت نشده'),('pending','منتظر تأیید'),('applied','اعمال شده'),('unchanged','بدون تغییر'),
            ('conflict','نیازمند بررسی'),('rejected','رد شده'),('unavailable','ناموجود در منبع')],default='new',max_length=20,verbose_name='وضعیت قیمت')),
        migrations.AddField(model_name='sourceproduct',name='sync_enabled',field=models.BooleanField(default=True,verbose_name='دریافت قیمت این محصول')),
        migrations.RunPython(source_defaults,migrations.RunPython.noop),
    ]
