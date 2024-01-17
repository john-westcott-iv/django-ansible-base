# django-ansible-base Features
django-ansible-base provides features as combination of django applications and python libraries.

All top level folders in ansible_base are django applications for features except for the lib folder.

## Determining if a new feature should be an app or a lib

To determine if a feature should be a library or a django-application please consider the following criteria.

If any of the following are true, you should create your new feature as a django app:
1) Does the feature require models
2) Does the feature require urls
3) Does the feature provide management commands
4) Does the feature require settings

If all of these are false, your feature should be a library under the `libs` folder.

## Initializing a new application

### Selecting a name

Please try to choose a concise descriptive name that is not an overloaded term.

For example, we chose `rest_filters` instead of using a generic term like `filters`.

### Initializing an application

To have django initialize your application run the following commands:

```
cd ansible_base
python ../manage.py startapp <app name>
```

This will automatically create a folder and files for you with the name of your application in ansible_base.

You can leave the `__init__.py` and the `migrations` folder alone.

The `admin.py` file should be deleted.

In the `apps.py` file be sure to change the `name` of the application to be prefixed with `ansible_base.`. For example, if your called your app `testing` the generated line would be:

```
name = 'testing'
```

But we need to change it to:
```
name = 'ansible_base.testing'
```

If you plan to have models you can either add them to `models.py` or, if you have multiple you can remove `models.py` and create a `models` folder (be sure to add an `__init__.py` into the models folder). If you don't plan to have models `models.py` can be deleted.

You can remove `tests.py` as we don't put tests in ansible_base. Additionally, you should create a folder matching your application name in `test_app/tests` and put all of your test files in there.

If you have views you can add them to `views.py` or, like models, remove `views.py` and create a `views` folder. If you don't plan to have views `views.py` can be deleted.

Finally, be sure to add `urls.py`. If your application does not require any URLS you can simply leave it blank like:

```
# This feature does not require any urls

urlpatterns = []
```

We need to do this for the dynamic url loader.
