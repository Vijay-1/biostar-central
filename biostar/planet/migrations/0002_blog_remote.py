# Generated by Django 3.1 on 2021-03-30 00:41

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('planet', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='blog',
            name='remote',
            field=models.BooleanField(default=True),
        ),
    ]