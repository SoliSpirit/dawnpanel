from django.db import migrations, models
import django.db.models.deletion


def retain_published_rates(apps,schema_editor):
    # Keep only what was already effective before the switch, with the original
    # timestamp. New polls can never overwrite this published copy.
    fx=apps.get_model('portal','CurrencyPricing')
    fx.objects.using(schema_editor.connection.alias).exclude(source='manual').filter(
        observed_at__isnull=False,market_bid__isnull=False,market_ask__isnull=False
    ).update(candidate_key=models.F('quote_key'),candidate_at=models.F('observed_at'),
             candidate_bid=models.F('market_bid'),candidate_ask=models.F('market_ask'),
             published_at=models.F('observed_at'))


class Migration(migrations.Migration):
    dependencies=[('portal','0015_currency_pricing')]
    operations=[
        migrations.AddField(model_name='currencypricing',name='candidate_ask',field=models.DecimalField(decimal_places=8,editable=False,max_digits=25,null=True)),
        migrations.AddField(model_name='currencypricing',name='candidate_at',field=models.DateTimeField(editable=False,null=True)),
        migrations.AddField(model_name='currencypricing',name='candidate_bid',field=models.DecimalField(decimal_places=8,editable=False,max_digits=25,null=True)),
        migrations.AddField(model_name='currencypricing',name='candidate_key',field=models.CharField(blank=True,default='',editable=False,max_length=40)),
        migrations.AddField(model_name='currencypricing',name='published_at',field=models.DateTimeField(editable=False,null=True)),
        migrations.AddField(model_name='currencypricing',name='revision',field=models.PositiveBigIntegerField(default=0,editable=False)),
        migrations.RunPython(retain_published_rates,migrations.RunPython.noop),
        migrations.CreateModel(name='CryptoTopup',fields=[
            ('ticket',models.OneToOneField(on_delete=django.db.models.deletion.PROTECT,primary_key=True,related_name='crypto_topup',serialize=False,to='portal.ticket')),
            ('request_key',models.UUIDField(unique=True)),('code',models.CharField(max_length=20)),
            ('units',models.DecimalField(decimal_places=12,max_digits=28)),('requested_rate',models.PositiveBigIntegerField()),
            ('paid_ref',models.CharField(editable=False,max_length=160,null=True,unique=True)),
            ('paid_units',models.DecimalField(decimal_places=12,editable=False,max_digits=28,null=True)),
            ('paid_rate',models.PositiveBigIntegerField(editable=False,null=True)),
            ('credited',models.PositiveBigIntegerField(editable=False,null=True)),
            ('settled_at',models.DateTimeField(editable=False,null=True)),
            ('account',models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,to='portal.account')),
        ],options={'permissions':[('settle_crypto_topup','تأیید دریافت رمزارز و شارژ کیف پول')]}),
    ]
