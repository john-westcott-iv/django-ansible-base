# Generated by Django 4.2.8 on 2024-05-09 16:12

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('dab_oauth2_provider', '0002_alter_oauth2refreshtoken_options_and_more'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='oauth2application',
            name='logo_data',
        ),
    ]