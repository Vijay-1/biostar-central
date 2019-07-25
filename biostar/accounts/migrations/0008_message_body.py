# Generated by Django 2.2.1 on 2019-06-12 15:59

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0007_profile_prefs'),
    ]

    operations = [
        migrations.CreateModel(
            name='MessageBody',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('body', models.TextField(max_length=10000)),
                ('html', models.TextField(default='', max_length=100000)),
            ],
        ),
        migrations.RemoveField(
            model_name='message',
            name='html',
        ),
        migrations.AlterField(
            model_name='message',
            name='body',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='accounts.MessageBody'),
        ),
    ]