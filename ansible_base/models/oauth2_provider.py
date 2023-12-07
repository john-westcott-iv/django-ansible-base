import logging
import re

from awx.sso.common import get_external_account
from django.conf import settings
from django.core.validators import RegexValidator
from django.db import connection, models
from django.utils.timezone import now
from django.utils.translation import gettext_lazy as _

from ansible_base.utils.encryption import ansible_encryption
from ansible_base.utils.settings import feature_enabled

DATA_URI_RE = re.compile(r'.*')  # FIXME

logger = logging.getLogger('ansible_base.models.oauth')


if feature_enabled('OAUTH2_SERVER'):
    import oauth2_provider.models as oauth2_models
    from oauth2_provider.generators import generate_client_secret
    from oauthlib import oauth2

    class OAuth2ClientSecretField(models.CharField):
        def get_db_prep_value(self, value, connection, prepared=False):
            return super().get_db_prep_value(ansible_encryption.encrypt(value), connection, prepared)

        def from_db_value(self, value, expression, connection):
            if value and value.startswith('$encrypted$'):
                return ansible_encryption.decrypt(value)
            return value

    class OAuth2Application(oauth2_models.AbstractApplication):
        class Meta(oauth2_models.AbstractAccessToken.Meta):
            app_label = 'ansible_base'
            verbose_name = _('application')
            unique_together = (("name", "organization"),)
            ordering = ('organization', 'name')
            swappable = "OAUTH2_PROVIDER_APPLICATION_MODEL"

        CLIENT_TYPES = (
            ("confidential", _("Confidential")),
            ("public", _("Public")),
        )

        GRANT_TYPES = (
            ("authorization-code", _("Authorization code")),
            ("password", _("Resource owner password-based")),
        )

        description = models.TextField(
            default='',
            blank=True,
        )
        logo_data = models.TextField(
            default='',
            editable=False,
            validators=[RegexValidator(DATA_URI_RE)],
        )
        organization = models.ForeignKey(
            'Organization',
            related_name='applications',
            help_text=_('Organization containing this application.'),
            on_delete=models.CASCADE,
            null=True,
        )
        client_secret = OAuth2ClientSecretField(
            max_length=1024,
            blank=True,
            default=generate_client_secret,
            db_index=True,
            help_text=_('Used for more stringent verification of access to an application when creating a token.'),
        )
        client_type = models.CharField(
            max_length=32, choices=CLIENT_TYPES, help_text=_('Set to Public or Confidential depending on how secure the client device is.')
        )
        skip_authorization = models.BooleanField(default=False, help_text=_('Set True to skip authorization step for completely trusted applications.'))
        authorization_grant_type = models.CharField(
            max_length=32, choices=GRANT_TYPES, help_text=_('The Grant type the user must use for acquire tokens for this application.')
        )

    class OAuth2AccessToken(oauth2_models.AbstractAccessToken):
        class Meta(oauth2_models.AbstractAccessToken.Meta):
            app_label = 'ansible_base'
            verbose_name = _('access token')
            ordering = ('id',)
            swappable = "OAUTH2_PROVIDER_ACCESS_TOKEN_MODEL"

        user = models.ForeignKey(
            settings.AUTH_USER_MODEL,
            on_delete=models.CASCADE,
            blank=True,
            null=True,
            related_name="%(app_label)s_%(class)s",
            help_text=_('The user representing the token owner'),
        )
        description = models.TextField(
            default='',
            blank=True,
        )
        last_used = models.DateTimeField(
            null=True,
            default=None,
            editable=False,
        )
        scope = models.TextField(
            blank=True,
            default='write',
            help_text=_(
                'Allowed scopes, further restricts user\'s permissions. Must be a simple space-separated string with allowed scopes [\'read\', \'write\'].'
            ),
        )
        modified = models.DateTimeField(editable=False, auto_now=True)

        def is_valid(self, scopes=None):
            valid = super(OAuth2AccessToken, self).is_valid(scopes)
            if valid:
                self.last_used = now()

                def _update_last_used():
                    if OAuth2AccessToken.objects.filter(pk=self.pk).exists():
                        self.save(update_fields=['last_used'])

                connection.on_commit(_update_last_used)
            return valid

        def validate_external_users(self):
            if self.user and settings.ALLOW_OAUTH2_FOR_EXTERNAL_USERS is False:
                external_account = get_external_account(self.user)
                if external_account is not None:
                    raise oauth2.AccessDeniedError(
                        _('OAuth2 Tokens cannot be created by users associated with an external authentication provider ({})').format(external_account)
                    )

        def save(self, *args, **kwargs):
            if not self.pk:
                self.validate_external_users()
            super(OAuth2AccessToken, self).save(*args, **kwargs)

    class OAuth2AccessRefreshToken(oauth2_models.AbstractRefreshToken):
        class Meta(oauth2_models.AbstractRefreshToken.Meta):
            app_label = 'ansible_base'
            verbose_name = _('access token')
            ordering = ('id',)
            swappable = "OAUTH2_PROVIDER_REFRESH_TOKEN_MODEL"

    class OAuth2IDToken(oauth2.models.AbstractIDToken):
        class Meta(oauth2.models.AbstractIDToken):
            app_label = 'ansible_base'
            verbose_name = _('id token')
            swappable = "OAUTH2_PROVIDER_ID_TOKEN_MODEL"
