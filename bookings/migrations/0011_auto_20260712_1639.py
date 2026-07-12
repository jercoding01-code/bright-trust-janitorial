from django.db import migrations

def create_default_superuser(apps, schema_editor):
    # Retrieve model dynamically using apps.get_model to avoid direct import issues
    User = apps.get_model('auth', 'User')
    if not User.objects.filter(username='admin').exists():
        # Django's create_superuser cannot be called directly on the model class returned by get_model, 
        # but we can create a normal user and set the password + flags manually!
        user = User(
            username='admin',
            email='admin@brighttrustjanitorial.ca',
            is_staff=True,
            is_superuser=True
        )
        # To hash the password correctly, we can use make_password from django.contrib.auth.hashers
        from django.contrib.auth.hashers import make_password
        user.password = make_password('SecureOwnerPassword123!')
        user.save()

def remove_default_superuser(apps, schema_editor):
    User = apps.get_model('auth', 'User')
    User.objects.filter(username='admin').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('bookings', '0010_cleaninglead_square_checkout_url'),
        # Ensure auth tables exist before creating user
        ('auth', '__first__'),
    ]

    operations = [
        migrations.RunPython(create_default_superuser, reverse_code=remove_default_superuser),
    ]
