from django.apps import AppConfig
from django.core.checks import register


class Oauth2ProviderConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'ansible_base.oauth2_provider'
    label = 'dab_oauth2_provider'

    def ready(self):
        # Load checks
        from ansible_base.oauth2_provider.checks.permisssions_check import oauth2_permission_scope_check

        register(oauth2_permission_scope_check, "oauth2_permissions", deploy=True)
