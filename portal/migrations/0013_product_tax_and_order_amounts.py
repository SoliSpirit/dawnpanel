import django.core.validators
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('portal', '0012_product_families')]
    operations = [
        migrations.CreateModel(
            name='ProductTax',
            fields=[
                ('product', models.OneToOneField(db_constraint=False, on_delete=django.db.models.deletion.CASCADE,
                    primary_key=True, related_name='tax_policy', serialize=False, to='portal.product')),
                ('percent', models.DecimalField(decimal_places=2, default=0, max_digits=5,
                    validators=[django.core.validators.MinValueValidator(0), django.core.validators.MaxValueValidator(100)],
                    verbose_name='درصد مالیات')),
            ],
            options={'constraints': [models.CheckConstraint(condition=models.Q(percent__gte=0, percent__lte=100),
                                                             name='product_tax_in_range')]},
        ),
        migrations.CreateModel(
            name='OrderAmounts',
            fields=[
                ('order', models.OneToOneField(db_constraint=False, on_delete=django.db.models.deletion.DO_NOTHING,
                    primary_key=True, related_name='amounts', serialize=False, to='portal.order')),
                ('subtotal', models.PositiveBigIntegerField(verbose_name='مبلغ پیش از مالیات')),
                ('tax_percent', models.DecimalField(decimal_places=2, max_digits=5, verbose_name='درصد مالیات هنگام خرید')),
                ('tax_amount', models.PositiveBigIntegerField(verbose_name='مبلغ مالیات')),
            ],
        ),
    ]
