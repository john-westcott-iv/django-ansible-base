# Generated by Django 4.2.6 on 2024-02-09 22:10

from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('dab_authentication', '0001_initial'),
    ]

    operations = [
        migrations.AlterField(
            model_name='authenticator',
            name='users',
            field=models.ManyToManyField(blank=True, help_text='The list of users who have authenticated from this authenticator', related_name='authenticators', to=settings.AUTH_USER_MODEL),
        ),
    ]
