def is_rbac_installed() -> bool:
    from django.conf import settings

    return bool('ansible_base.rbac' in settings.INSTALLED_APPS)
