# -*- coding: utf-8 -*-
from __future__ import absolute_import, unicode_literals

import logging
from django import VERSION as django_version
from django.db.models.query_utils import DeferredAttribute

try:
    # noinspection PyUnresolvedReferences
    from typing import Text, Any, Dict
except ImportError:  # pragma: no cover
    pass

from django.apps import AppConfig
from django.conf import settings


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
        raise MissingLocalField(_TMPL_MISSING_LOCAL.format(
                attr=name, cls=instance.__class__.__name__,
            )
        )
    return val


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
    )
    django.setup()
    from django.contrib.auth.models import User
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
            test_runner.test_loader.loadTestsFromTestCase(FormTestCase),
        ),
    )
