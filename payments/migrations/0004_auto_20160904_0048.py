# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2016-09-04 00:48
from __future__ import unicode_literals

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import jsonfield.fields


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('payments', '0003_auto_20151209_0440'),
    ]

    operations = [
        migrations.CreateModel(
            name='Subscription',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('backend_id', models.CharField(choices=[('bitcoin', 'Bitcoin'), ('coinbase', 'Coinbase'), ('manual', 'Manual'), ('paypal', 'PayPal'), ('stripe', 'Stripe')], max_length=16)),
                ('created', models.DateTimeField(auto_now_add=True)),
                ('period', models.CharField(choices=[('3m', 'Every 3 months'), ('6m', 'Every 6 months'), ('12m', 'Every year')], max_length=16)),
                ('last_confirmed_payment', models.DateTimeField(blank=True, null=True)),
                ('status', models.CharField(choices=[('new', 'Waiting for payment'), ('active', 'Active'), ('cancelled', 'Cancelled')], default='new', max_length=16)),
                ('backend_extid', models.CharField(blank=True, max_length=64, null=True)),
                ('backend_data', jsonfield.fields.JSONField(blank=True, default=dict)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.RemoveField(
            model_name='recurringpaymentsource',
            name='user',
        ),
        migrations.RemoveField(
            model_name='payment',
            name='recurring_source',
        ),
        migrations.DeleteModel(
            name='RecurringPaymentSource',
        ),
        migrations.AddField(
            model_name='payment',
            name='subscription',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, to='payments.Subscription'),
        ),
    ]