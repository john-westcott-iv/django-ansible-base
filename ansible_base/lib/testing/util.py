def copy_fixture(copies=1):
    """
    Decorator to create 'copies' copies of a fixture.

    The copies will be named func_1, func_2, ..., func_n in the same module as
    the original fixture.
    """

    def wrapper(func):
        if '_pytestfixturefunction' not in dir(func):
            raise TypeError(f"Can't apply copy_fixture to {func.__name__} because it is not a fixture. HINT: @copy_fixture must be *above* @pytest.fixture")

        module_name = func.__module__
        module = __import__(module_name, fromlist=[''])

        for i in range(copies):
            new_name = f"{func.__name__}_{i + 1}"
            setattr(module, new_name, func)
        return func

    return wrapper


def delete_authenticator(authenticator):
    from ansible_base.authentication.models import AuthenticatorUser
    from ansible_base.lib.utils.models import get_system_username

    for au in AuthenticatorUser.objects.filter(provider=authenticator):
        try:
            # The tests are very sensitive to the system user being removed so we won't delete that user
            if au.username != get_system_username[0]:
                au.user.delete()
        except Exception:
            # Its possible that something else already deleted the user if a user was multi linked somehow
            pass
        au.delete()
    authenticator.delete()
