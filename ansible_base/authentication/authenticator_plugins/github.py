import logging
import urllib.parse as urlparse

from django.urls import reverse
from django.contrib.auth.backends import ModelBackend
from django.core.exceptions import ValidationError

from social_core.backends.github import GithubOAuth2

from ansible_base.authentication.authenticator_plugins.base import AbstractAuthenticatorPlugin, BaseAuthenticatorConfiguration
from ansible_base.authentication.models import AuthenticatorUser

from ansible_base.authentication.social_auth import SocialAuthMixin
from ansible_base.lib.serializers.fields import CharField, URLField

logger = logging.getLogger('ansible_base.authentication.authenticator_plugins.local')



# FIXME ... what should happen here in gateway?
class SocialAuthCallbackURL(object):
    def __init__(self, provider):
        self.provider = provider

    def __call__(self):
        path = reverse('social:complete', args=(self.provider,))
        # return urlparse.urljoin(settings.TOWER_URL_BASE, path)
        return urlparse.urljoin('/api/gateway', path)


class GithubConfiguration(BaseAuthenticatorConfiguration):

    documenation_url = None

    SOCIAL_AUTH_GITHUB_CALLBACK_URL = URLField(
        help_text=_(
            'Provide this URL as the callback URL for your'
            ' application as part of your registration process.'
            ' Refer to the documentation for more detail.'
        ),
        default=SocialAuthCallbackURL('github'),
        allow_null=False,
        ui_field_label=('Callback URL'),
    )

    SOCIAL_AUTH_GITHUB_KEY = CharField(
        help_text=('The OAuth2 key (Client ID) from your GitHub developer application.'),
        allow_null=False,
        ui_field_label=('GitHub OAuth2 Key'),
    )

    SOCIAL_AUTH_GITHUB_SECRET = CharField(
        help_text=('The OAuth2 secret (Client Secret) from your GitHub developer application.'),
        allow_null=False,
        ui_field_label=('GitHub OAuth2 Secret'),
    )


class AuthenticatorPlugin(SocialAuthMixin, GithubOAuth2, AbstractAuthenticatorPlugin):
    configuration_class = GithubConfiguration
    logger = logger
    type = "github"
    category = "sso"
