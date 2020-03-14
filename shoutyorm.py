# -*- coding: utf-8 -*-
from __future__ import absolute_import, unicode_literals

import logging
from django import VERSION as django_version
from django.db.models.query_utils import DeferredAttribute
from wrapt import CallableObjectProxy

try:
    # noinspection PyUnresolvedReferences
    from typing import Text, Any, Dict
except ImportError:  # pragma: no cover
    pass

from django.apps import AppConfig
from django.conf import settings
from django.db.models import Model

from django.db.models.fields.related_descriptors import ReverseManyToOneDescriptor

logger = logging.getLogger(__name__)


__version_info__ = "0.1.0"
__version__ = "0.1.0"
version = "0.1.0"
VERSION = "0.1.0"


def get_version():
    # type: () -> Text
    return version


class ShoutyAttributeError(AttributeError):
    pass


class MissingLocalField(ShoutyAttributeError):
    pass


class MissingRelationField(ShoutyAttributeError):
    pass


class MissingReverseRelationField(MissingRelationField):
    pass


_TMPL_MISSING_LOCAL = "Access to '{attr}' attribute on {cls} was prevented because it was not selected; probably defer() or only() were used."
_TMPL_MISSING_ANY_PREFETCH_REVERSE = "Access to reverse manager '{attr}' on {cls} was prevented because it was not selected; probably missing from prefetch_related()"
_TMPL_MISSING_SPECIFIC_PREFETCH_REVERSE = "Access to reverse manager '{attr}' on {cls} was prevented because it was not part of the prefetch_related() selection used"

__all__ = [
    "get_version",
    "ShoutyAttributeError",
    "MissingLocalField",
    "MissingRelationField",
    "MissingReverseRelationField",
    "patch",
    "Shout",
    "default_app_config",
]

# This is used so that when .only() and .defer() are used, I can prevent the
# bit which would cause a query for unselected fields.
old_deferredattribute_check_parent_chain = DeferredAttribute._check_parent_chain

# This is when you do "mymodel.myothermodel_set.all()" where the foreignkey
# exists on "MyOtherModel" and POINTS to "MyModel"
#
# In an ideal world I'd patch get_queryset() directly, but that's used by
# the get_prefetch_queryset() implementations and I don't know the ramifications
# of doing so, so instead we're going to proxy the "public" API.
old_reverse_foreignkey_descriptor_get = ReverseManyToOneDescriptor.__get__


def new_deferredattribute_check_parent_chain(self, instance, name=None):
    # In Django 3.0, DeferredAttribute was refactored somewhat so that
    # _check_parent_chain no longer requires passing a name instance.
    if django_version[0:2] < (3, 0):
        val = old_deferredattribute_check_parent_chain(self, instance, name=name)
    else:
        val = old_deferredattribute_check_parent_chain(self, instance)
        assert name is None, "Unexpected name value"
        name = self.field.attname
    if val is None:
        raise MissingLocalField(
            _TMPL_MISSING_LOCAL.format(attr=name, cls=instance.__class__.__name__,)
        )
    return val


class MissingPrefetchRelatedManager(CallableObjectProxy):

    __slots__ = ("__wrapped__", "_self_error_message")

    def __init__(self, wrapped, error_message):
        super().__init__(wrapped=wrapped)
        self._self_error_message = error_message

    def all(self):
        raise MissingReverseRelationField(self._self_error_message)


def new_reverse_foreignkey_descriptor_get(self, instance, cls=None):
    # type: (ReverseManyToOneDescriptor, Model, None) -> Any
    """
    This should get invoked when a Model is set up thus:
    ```
    class MyModel(...):
        pass

    class MyOtherModel(...):
        mymodel = ForeignKey(MyModel)
    ```

    and subsequently you try to use it like so:
    ```
    my_model = MyModel.objects.get(...)
    my_other_model = tuple(mymodel.myothermodel_set.all())
    ```

    without having used `prefetch_related("myothermodel_set")` to ensure
    it's not going to do N extra queries.
    """
    if instance is None:
        return self

    related_name = self.field.remote_field.get_cache_name()
    manager = old_reverse_foreignkey_descriptor_get(self, instance, cls)

    if not hasattr(instance, "_prefetched_objects_cache"):
        return MissingPrefetchRelatedManager(
            manager,
            error_message=_TMPL_MISSING_ANY_PREFETCH_REVERSE.format(
                attr=related_name, cls=instance.__class__.__name__,
            ),
        )
    elif (
        instance._prefetched_objects_cache
        and related_name not in instance._prefetched_objects_cache
    ):
        return MissingPrefetchRelatedManager(
            manager,
            error_message=_TMPL_MISSING_SPECIFIC_PREFETCH_REVERSE.format(
                attr=related_name, cls=instance.__class__.__name__,
            ),
        )
    return manager


def patch(invalid_locals, invalid_relations, invalid_reverse_relations):
    # type: (bool, bool, bool) -> bool
    """
    if invalid_locals is True, accessing fields which have been
    deferred via `.only()` and `.defer()` at the QuerySet level will error loudly.

    if invalid_relations is True, accessing OneToOnes which have not
    been `.select_related()` at the QuerySet level will error loudly.

    if invalid_reverse_relations is True, accessing foreignkeys from the "other"
    side (that is, via the reverse relation manager) which have not
    been `.prefetch_related()` at the QuerySet level will error loudly.

    if invalid_relations is turned on, accessing local foreignkeys
    which have not been `prefetch_related()` or `select_related()` at the queryset
    level will error loudly.
    """
    if invalid_locals is True:
        patched_deferredattr = getattr(DeferredAttribute, "_shouty", False)
        if patched_deferredattr is False:
            DeferredAttribute._check_parent_chain = (
                new_deferredattribute_check_parent_chain
            )

    if invalid_reverse_relations is True:
        patched_reverse_manytoone = getattr(
            ReverseManyToOneDescriptor, "_shouty", False
        )

        if patched_reverse_manytoone is False:
            ReverseManyToOneDescriptor.__get__ = new_reverse_foreignkey_descriptor_get

    return True


class Shout(AppConfig):  # type: ignore
    """
    Applies the patch automatically if enabled by adding `shoutyorm` or
    `shoutyorm.Shout` to INSTALLED_APPS.

    if SHOUTY_LOCAL_FIELDS is turned on, accessing fields which have been
    deferred via `.only()` and `.defer()` at the QuerySet level will error loudly.

    if SHOUTY_RELATION_FIELDS is turned on, accessing OneToOnes which have not
    been `.select_related()` at the QuerySet level will error loudly.

    if SHOUTY_RELATION_REVERSE_FIELDS is turned on, accessing foreignkeys from the "other"
    side (that is, via the reverse relation manager) which have not
    been `.prefetch_related()` at the QuerySet level will error loudly.

    if SHOUTY_RELATION_FIELDS is turned on, accessing local foreignkeys
    which have not been `prefetch_related()` or `select_related()` at the queryset
    level will error loudly.
    """

    # noinspection PyUnresolvedReferences
    name = "shoutyorm"

    def ready(self):
        # type: () -> bool
        logger.info("Applying shouty ORM patch")
        return patch(
            invalid_locals=getattr(settings, "SHOUTY_LOCAL_FIELDS", True),
            invalid_relations=getattr(settings, "SHOUTY_RELATION_FIELDS", True),
            invalid_reverse_relations=getattr(
                settings, "SHOUTY_RELATION_REVERSE_FIELDS", True
            ),
        )


default_app_config = "shoutyorm.Shout"


if __name__ == "__main__":
    from django.test import TestCase
    from django.test.runner import DiscoverRunner
    from unittest import expectedFailure
    import django

    settings.configure(
        DATABASES={
            "default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}
        },
        INSTALLED_APPS=(
            "django.contrib.contenttypes",
            "django.contrib.auth",
            "django.contrib.messages",
            "django.contrib.admin",
            "shoutyorm",
        ),
        MIDDLEWARE=(
            "django.contrib.auth.middleware.AuthenticationMiddleware",
            "django.contrib.messages.middleware.MessageMiddleware",
            "django.contrib.sessions.middleware.SessionMiddleware",
        ),
        TEMPLATES=[
            {
                "BACKEND": "django.template.backends.django.DjangoTemplates",
                "DIRS": [],
                "APP_DIRS": True,
                "OPTIONS": {
                    "context_processors": (
                        "django.contrib.auth.context_processors.auth",
                        "django.contrib.messages.context_processors.messages",
                    )
                },
            },
        ],
        SHOUTY_LOCAL_FIELDS=True,
        SHOUTY_RELATION_FIELDS=True,
        SHOUTY_RELATION_REVERSE_FIELDS=True,
    )
    django.setup()
    from django.contrib.auth.models import User, Group, Permission
    from django.contrib.contenttypes.models import ContentType
    from django import forms

    # noinspection PyStatementEffect
    class LocalFieldsTestCase(TestCase):  # type: ignore
        """
        Show what happens when new_deferredattribute_check_parent_chain
        is in play.
        """

        def setUp(self):
            # type: () -> None
            # Have to import the exceptions here to avoid __main__.ExceptionCls
            # not being the same as shoutyorm.ExceptionCls, otherwise the test
            # cases have to be outside the __main__ block.
            # noinspection PyUnresolvedReferences
            from shoutyorm import MissingLocalField

            self.MissingLocalField = MissingLocalField
            self.instance = User.objects.create()

        def test_normal_behaviour(self):
            # type: () -> None
            with self.assertNumQueries(1):
                u = User.objects.get(pk=self.instance.pk)
            with self.assertNumQueries(0):
                u.pk
                u.first_name
                u.date_joined
                u.last_name

        # noinspection PyStatementEffect
        def test_only_local(self):
            # type: () -> None
            with self.assertNumQueries(1):
                obj = User.objects.only("pk").get(pk=self.instance.pk)  # type: User
            with self.assertNumQueries(0):
                obj.pk
                obj.id
                with self.assertRaisesMessage(
                    self.MissingLocalField,
                    "Access to 'first_name' attribute on User was prevented because it was not selected; probably defer() or only() were used.",
                ):
                    obj.first_name

        def test_defer_local(self):
            # type: () -> None
            with self.assertNumQueries(1):
                obj = User.objects.defer("date_joined").get(
                    pk=self.instance.pk
                )  # type: User
            with self.assertNumQueries(0):
                obj.pk
                obj.id
                obj.first_name
                with self.assertRaisesMessage(
                    self.MissingLocalField,
                    "Access to 'date_joined' attribute on User was prevented because it was not selected; probably defer() or only() were used.",
                ):
                    obj.date_joined

        def test_with_annotation_virtual_field(self):
            # type: () -> None
            from django.db.models import Value, F, BooleanField

            with self.assertNumQueries(1):
                obj = (
                    User.objects.annotate(
                        testing=Value(True, output_field=BooleanField()),
                        testing_aliasing=F("first_name"),
                    )
                    .only("pk", "first_name")
                    .get(pk=self.instance.pk)
                )  # type: User
            with self.assertNumQueries(0):
                obj.pk
                obj.id
                obj.first_name
                # noinspection PyUnresolvedReferences
                self.assertTrue(obj.testing)
                # noinspection PyUnresolvedReferences
                self.assertEqual(obj.testing_aliasing, obj.first_name)
                with self.assertRaisesMessage(
                    self.MissingLocalField,
                    "Access to 'last_name' attribute on User was prevented because it was not selected; probably defer() or only() were used.",
                ):
                    obj.last_name

    # noinspection PyStatementEffect
    class NormalRelationFieldsTestCase(TestCase):  # type: ignore
        """
        Covers how the following behave:
        - new_foreignkey_descriptor_get_object
        """

        def setUp(self):
            # type: () -> None
            # Have to import the exceptions here to avoid __main__.ExceptionCls
            # not being the same as shoutyorm.ExceptionCls, otherwise the test
            # cases have to be outside the __main__ block.
            # noinspection PyUnresolvedReferences
            from shoutyorm import MissingRelationField

            self.MissingRelationField = MissingRelationField

        def test_accessing_foreignkey_with_select_related(self):
            # type: () -> None
            """ Never hits new_foreignkey_descriptor_get_object """
            with self.assertNumQueries(1):
                obj = Permission.objects.select_related("content_type").all()[
                    0
                ]  # type: Permission
            with self.assertNumQueries(0):
                obj.name
                obj.codename
                obj.content_type_id
                obj.content_type.pk

        def test_accessing_foreignkey_with_prefetch_related(self):
            # type: () -> None
            """ Never hits new_foreignkey_descriptor_get_object """
            with self.assertNumQueries(2):
                obj = Permission.objects.prefetch_related("content_type").all()[
                    0
                ]  # type: Permission
            with self.assertNumQueries(0):
                obj.name
                obj.codename
                obj.content_type_id
                obj.content_type.pk

    # noinspection PyStatementEffect
    class ReverseRelationFieldsTestCase(TestCase):  # type: ignore
        """
        These tests should demonstrate behaviour of
        new_reverse_foreignkey_descriptor_get
        """

        def setUp(self):
            # type: () -> None
            # Have to import the exceptions here to avoid __main__.ExceptionCls
            # not being the same as shoutyorm.ExceptionCls, otherwise the test
            # cases have to be outside the __main__ block.
            # noinspection PyUnresolvedReferences
            from shoutyorm import MissingReverseRelationField

            self.MissingReverseRelationField = MissingReverseRelationField

        def test_accessing_other_side_of_foreignkey(self):
            # type: () -> None
            with self.assertNumQueries(1):
                obj = ContentType.objects.all()[0]  # type: ContentType
            with self.assertNumQueries(0):
                obj.app_label
                obj.model
                with self.assertRaisesMessage(
                    self.MissingReverseRelationField,
                    "Access to reverse manager 'permission_set' on ContentType was prevented because it was not selected; probably missing from prefetch_related()",
                ):
                    obj.permission_set.all()

        def test_accessing_other_side_of_foreignkey_with_prefetch_related(self):
            # type: () -> None
            with self.assertNumQueries(2):
                obj = ContentType.objects.prefetch_related("permission_set").all()[
                    0
                ]  # type: ContentType
            with self.assertNumQueries(0):
                obj.app_label
                obj.model
                set(obj.permission_set.all())

        def test_accessing_other_side_of_foreignkey_with_only_some_prefetch_related(
            self,
        ):
            # type: () -> None
            with self.assertNumQueries(2):
                obj = ContentType.objects.prefetch_related("permission_set").all()[
                    0
                ]  # type: ContentType
            with self.assertNumQueries(0):
                obj.app_label
                obj.model
                with self.assertRaisesMessage(
                    self.MissingReverseRelationField,
                    "Access to reverse manager 'logentry_set' on ContentType was prevented because it was not part of the prefetch_related() selection used",
                ):
                    set(obj.logentry_set.all())

        def test_accessing_other_side_of_foreignkey_with_multiple_prefetch_related(
            self,
        ):
            # type: () -> None
            with self.assertNumQueries(3):
                obj = ContentType.objects.prefetch_related(
                    "permission_set", "logentry_set"
                ).all()[
                    0
                ]  # type: ContentType
            with self.assertNumQueries(0):
                obj.app_label
                obj.model
                set(obj.permission_set.all())
                set(obj.logentry_set.all())

        def test_using_other_side_of_foreignkey_for_adding_etc(self):
            # type: () -> None
            with self.assertNumQueries(2):
                group = Group.objects.create()
                user = User.objects.create(username="test")
            with self.assertNumQueries(1):
                group.user_set.clear()
            with self.assertNumQueries(1):
                group.user_set.add(user)
            with self.assertNumQueries(1):
                group.user_set.remove(user)
            with self.assertNumQueries(2):
                self.assertIsNone(group.user_set.first())
                self.assertIsNone(group.user_set.last())
            with self.assertNumQueries(2):
                group.user_set.set((user,))
            # Not sure why both of these are 0 queries? Neither uses the _result_cache
            # AFAIK, so surely they should always do one?
            with self.assertNumQueries(0):
                group.user_set.exclude(username__icontains="test")
            with self.assertNumQueries(0):
                group.user_set.filter(username__icontains="test")
            # Especially as the following all ... do a query?
            with self.assertNumQueries(1):
                self.assertEqual(group.user_set.count(), 1)
            with self.assertNumQueries(1):
                self.assertTrue(group.user_set.exists())
            with self.assertNumQueries(2):
                self.assertIsNotNone(group.user_set.first())
                self.assertIsNotNone(group.user_set.last())

    class FormTestCase(TestCase):  # type: ignore
        """
        Auto generated modelforms are super common, so let's
        demonstrate how all the behaviours link together
        to cause issues or corrections.
        """

        def setUp(self):
            # type: () -> None
            # Have to import the exceptions here to avoid __main__.ExceptionCls
            # not being the same as shoutyorm.ExceptionCls, otherwise the test
            # cases have to be outside the __main__ block.
            # noinspection PyUnresolvedReferences
            from shoutyorm import MissingRelationField, MissingLocalField

            self.MissingLocalField = MissingLocalField
            self.MissingRelationField = MissingRelationField

        def test_foreignkey_in_form(self):
            # type: () -> None
            """
            Prove that the patch doesn't affect modelform generation.
            """

            class PermissionForm(forms.ModelForm):  # type: ignore
                class Meta:
                    model = Permission
                    fields = "__all__"

            with self.assertNumQueries(1):
                obj = Permission.objects.all()[0]  # type: Permission
            with self.assertNumQueries(3):
                form = PermissionForm(
                    data={
                        "name": obj.name,
                        "content_type": obj.content_type_id,
                        "codename": obj.codename,
                    },
                    instance=obj,
                )
                form.is_valid()
                self.assertEqual(form.errors, {})
            with self.assertNumQueries(1):
                form.save()

        def test_local_in_form(self):
            instance = User.objects.create()

            class UserForm(forms.ModelForm):  # type: ignore
                class Meta:
                    model = User
                    fields = ("first_name", "password")

            with self.assertNumQueries(1):
                obj = User.objects.only("pk", "first_name").get(pk=instance.pk)
                with self.assertRaisesMessage(
                    self.MissingLocalField,
                    "Access to 'password' attribute on User was prevented because it was not selected; probably defer() or only() were used.",
                ):
                    UserForm(data=None, instance=obj)

    test_runner = DiscoverRunner(interactive=False, verbosity=2)
    failures = test_runner.run_tests(
        test_labels=(),
        extra_tests=(
            test_runner.test_loader.loadTestsFromTestCase(LocalFieldsTestCase),
            test_runner.test_loader.loadTestsFromTestCase(NormalRelationFieldsTestCase),
            test_runner.test_loader.loadTestsFromTestCase(
                ReverseRelationFieldsTestCase
            ),
            test_runner.test_loader.loadTestsFromTestCase(FormTestCase),
        ),
    )
