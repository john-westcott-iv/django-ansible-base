from rest_framework.permissions import SAFE_METHODS, BasePermission

from ansible_base.lib.utils.settings import get_setting

oauth2_provider_installed = "ansible_base.oauth2_provider" in get_setting("INSTALLED_APPS", [])


def try_add_oauth2_scope_permission(permission_classes: list):
    """
    Attach OAuth2ScopePermission to the provided permission_classes list

    :param permission_classes: list of rest_framework permissions
    :return: A list of permission_classes, including OAuth2ScopePermission
        if ansible_base.oauth2_provider is installed; otherwise the same
        permission_classes list supplied to the function
    """
    if oauth2_provider_installed:
        from ansible_base.oauth2_provider.permissions import OAuth2ScopePermission

        return [OAuth2ScopePermission] + permission_classes
    return permission_classes


class IsSuperuser(BasePermission):
    """
    Allows access only to superusers.
    """

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.is_superuser)


class IsSuperuserOrAuditor(BasePermission):
    """
    Allows write access only to system admin users.
    Allows read access only to system auditor users.
    """

    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        if request.user.is_superuser:
            return True
        if request.method in SAFE_METHODS:
            return getattr(request.user, 'is_platform_auditor', False)
        return False
