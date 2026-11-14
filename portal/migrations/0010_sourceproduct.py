from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('portal', '0009_productvisual_duration_months_and_more')]
    operations = [
        migrations.CreateModel(
            name='SourceProduct',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('source', models.CharField(max_length=30)),
                ('external_id', models.CharField(max_length=80)),
                ('product_id', models.PositiveBigIntegerField(unique=True)),
                ('source_url', models.URLField(blank=True, max_length=1000)),
                ('last_price', models.PositiveBigIntegerField()),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={'constraints': [models.UniqueConstraint(fields=('source', 'external_id'), name='unique_source_product')]},
        ),
    ]
