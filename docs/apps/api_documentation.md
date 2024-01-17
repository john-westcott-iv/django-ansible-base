# Open API and Swagger documentation

django-ansible-base uses django-spectacular to auto-generate both Open API and Swagger documentation of the API.

## Settings

Add `ansible_base.api_documentation` to your installed apps:

```
INSTALLED_APPS = [
    ...
    'ansible_base.api_documentation',
]
```

### Additional Settings
Additional settings are required to enable api_documentation.
This will happen automatically if using [dynamic_settings](./dyanmic_settings.md)

First, you need to add `drf_spectacular` to your `INSTALLED_APPS`:
```
INSTALLED_APPS = [
    ...
    'drf_spectacular',
    ...
]
```

Additionally, we create a `SPECTACULAR_SETTINGS` entry if its not already present:
```
SPECTACULAR_SETTINGS = {
    'TITLE': 'AAP Open API',
    'DESCRIPTION': 'AAP Open API',
    'VERSION': 'v1',
    'SCHEMA_PATH_PREFIX': '/api/v1/',
}
```

Finally, add a `DEFAULT_SCHEMA_CLASS` to your `REST_FRAMEWORK` setting:
```
REST_FRAMEWORK = {
    ...
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
    ...
}
```

## URLS

This feature includes URLs which you will get if you are using [dynamic urls](./dyanmic_config.md)

If you want to manually add the urls without dynamic urls add the following to your urls.py:
```
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView

urlpatterns = [
    ...
    path('api/v1/docs/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/v1/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    path('api/v1/docs/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),   
    ...
]
```
