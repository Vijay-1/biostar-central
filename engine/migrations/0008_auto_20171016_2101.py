# -*- coding: utf-8 -*-
# Generated by Django 1.11.4 on 2017-10-16 21:01
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('engine', '0007_auto_20171016_1706'),
    ]

    operations = [
        migrations.AlterField(
            model_name='job',
            name='log',
            field=models.TextField(default='No data logged for current job'),
        ),
    ]
