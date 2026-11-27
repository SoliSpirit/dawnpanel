from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('portal', '0016_reviewed_rates_and_crypto_tickets')]
    operations = [
        migrations.AlterField(
            model_name='currencypricing', name='source',
            field=models.CharField(max_length=12, default='manual', choices=[
                ('manual', 'نرخ پایهٔ دستی'), ('nobitex', 'نوبیتکس · بازار رمزارز'),
                ('nerkhara', 'نرخ‌آرا · بازار آزاد ارز'), ('denapanel', 'دناپنل · استارز تلگرام'),
            ]),
        ),
    ]
