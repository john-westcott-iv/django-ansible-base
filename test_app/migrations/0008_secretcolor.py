# Generated by Django 4.2.8 on 2024-04-05 17:43

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('test_app', '0007_alter_animal_created_by_alter_animal_modified_by_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='SecretColor',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('color', models.CharField(default='blue', max_length=20, null=True)),
            ],
        ),
    ]
