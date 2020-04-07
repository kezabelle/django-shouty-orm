# -*- coding: utf-8 -*-
"""
A series of monkeypatches to apply to Django's various ORM methods to force it
to error loudly when another query would be triggered, rather than silently
backfill the requested data causing N+1 queries.

Alternative options include:
 - django-seal <https://github.com/charettes/django-seal>
 - django-eraserhead <https://github.com/dizballanze/django-eraserhead>

The expected public API usage is simply to include `shoutyorm` or `shoutyorm.Shout`
in your django project's INSTALLED_APPS, and set
SHOUTY_LOCAL_FIELDS / SHOUTY_RELATION_FIELDS / SHOUTY_RELATION_REVERSE_FIELDS
to True/False as desired.

If for whatever reason the patches aren't applied soon enough, you should be
able to manually call shoutyorm.patch(...) to set them up.

Patches are expected to work on Django 2.2 (LTS) onwards.

Settings
--------

SHOUTY_LOCAL_FIELDS = True
Accessing fields which have been deferred via `.only()` and `.defer()` at
the QuerySet level will error loudly.

SHOUTY_RELATION_FIELDS = True
Accessing OneToOnes which have not been `.select_related()` at the QuerySet
level will error loudly.
Accessing local foreignkeys which have not been `prefetch_related()` or
`select_related()` at the queryset level will error loudly.

SHOUTY_RELATION_REVERSE_FIELDS = True
Accessing foreignkeys from the "other" side (that is, via the reverse relation
manager) which have not been `.prefetch_related()` at the QuerySet level will error loudly.

Problems?
---------

There are likely to be both false positives and false negatives.
If you encounter a situation where an exception IS raised to prevent a query when
one shouldn't be (because it wouldn't do a query) please report it via the URL
below.
Likewise if you find it NOT raising an exception and letting a query silently
happen, please report it.

<https://github.com/kezabelle/django-shouty-orm/issues/new>
"""
from __future__ import absolute_import, unicode_literals

import logging
import os

from django import VERSION as DJANGO_VERSION
from django.db.models.query_utils import DeferredAttribute
from wrapt import CallableObjectProxy

try:
    from typing import Text, Any, Optional
except ImportError:  # pragma: no cover
    pass

from django.apps import AppConfig
from django.db.models import Model, Manager

from django.db.models.fields.related_descriptors import (
    ReverseManyToOneDescriptor,
    ManyToManyDescriptor,
    ReverseOneToOneDescriptor,
    ForwardManyToOneDescriptor,
)

logger = logging.getLogger(__name__)


__version_info__ = "0.1.1"
__version__ = "0.1.1"
version = "0.1.1"
VERSION = "0.1.1"


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
_TMPL_MISSING_M2M_PREFETCH = "Access to '{attr}' ManyToMany manager attribute on {cls} was prevented because it was not selected; probably missing from prefetch_related()"
_TMPL_MISSING_LOCAL_FK = "Access to '{attr}' attribute on {cls} was prevented because it was not selected; probably missing from prefetch_related() or select_related()"
_TMPL_MISSING_REVERSE_121 = "Access to '{attr}' relation attribute on {cls} was prevented because it was not selected; probably missing from select_related()"

__all__ = [
    "patch",
    "Shout",
    "default_app_config",
    "get_version",
    "ShoutyAttributeError",
    "MissingLocalField",
    "MissingRelationField",
    "MissingReverseRelationField",
]

# This is used so that when .only() and .defer() are used, I can prevent the
# bit which would cause a query for unselected fields.
# noinspection PyProtectedMember
old_deferredattribute_check_parent_chain = DeferredAttribute._check_parent_chain

# This is when you do "mymodel.myothermodel_set.all()" where the foreignkey
# exists on "MyOtherModel" and POINTS to "MyModel"
#
# In an ideal world I'd patch get_queryset() directly, but that's used by
# the get_prefetch_queryset() implementations and I don't know the ramifications
# of doing so, so instead we're going to proxy the "public" API.
old_reverse_foreignkey_descriptor_get = ReverseManyToOneDescriptor.__get__

# This is when you do "mymodel.myfield" where "myfield" is a OneToOneField
# on MyOtherModel which points back to MyModel
#
# In an ideal world I'd patch get_queryset() directly, but that's used by
# the get_prefetch_queryset() implementations and I don't know the ramifications
# of doing so, so instead we're going to proxy the "public" API.
old_reverse_onetoone_descriptor_get = ReverseOneToOneDescriptor.__get__


# This is used when you have mymodel.m2m.all() where m2m is a ManyToManyField
# because of the way this descriptor's related manager is set up, in combination
# with the way prefetching works (get_prefetch_queryset, get the manager, get_queryset, etc)
# This is the best entry point I could find.
old_manytomany_descriptor_get = ManyToManyDescriptor.__get__


# This is when you do "mymodel.myfield" where "myfield" is a ForeignKey
# on the "MyModel" class
#
# As far as I can tell it's safe to patch get_object() directly here instead
# of __get__ as I have for the other ones, because get_object()
# solely does the database querying, and nothing else.
#
# This ... MIGHT ... also patch the ForwardOneToOneDescriptor as that ultimately
# subclasses the ManyToOne and calls super().get_object() but I've not tested it.
old_foreignkey_descriptor_get_object = ForwardManyToOneDescriptor.get_object


def new_deferredattribute_check_parent_chain(self, instance, name=None):
    # type: (DeferredAttribute, Model, Optional[Text]) -> Any
    # In Django 3.0, DeferredAttribute was refactored somewhat so that
    # _check_parent_chain no longer requires passing a name instance.
    if DJANGO_VERSION[0:2] < (3, 0):
        # noinspection PyArgumentList
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


class MissingPrefetchRelatedManager(CallableObjectProxy):  # type: ignore

    __slots__ = ("__wrapped__", "_self_error_message")

    def __init__(self, wrapped, error_message):
        # type: (Manager, str) -> None
        super(CallableObjectProxy, self).__init__(wrapped=wrapped)
        self._self_error_message = error_message

    def all(self):
        # type: () -> None
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

    # noinspection PyProtectedMember
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


def new_reverse_onetoone_descriptor_get(self, instance, cls=None):
    # type: (ReverseOneToOneDescriptor, Model, None) -> Any
    """
    This should get invoked when a Model is set up thus:
    ```
    class MyModel(...):
        pass

    class MyOtherModel(...):
        mymodel = OneToOneField(MyModel)
    ```

    and subsequently you try to use it like so:
    ```
    my_model = MyModel.objects.get(...)
    my_other_model = mymodel.myothermodel.pk
    ```

    without having used `select_related("myothermodel")` to ensure it's not
    going to trigger further queries.
    """
    if instance is None:
        return self
    try:
        self.related.get_cached_value(instance)
    except KeyError:
        attr = self.related.get_accessor_name()
        raise MissingRelationField(
            _TMPL_MISSING_REVERSE_121.format(
                attr=attr, cls=instance.__class__.__name__,
            )
        )
    return old_reverse_onetoone_descriptor_get(self, instance, cls)


def new_manytomany_descriptor_get(self, instance, cls=None):
    # type: (ManyToManyDescriptor, Model, None) -> Any
    """
    This is invoked when you're asking for mymodel.m2m.all() or more specifically
    asking for mymodel.m2m... accessing .all() in SOME scenarios will now
    raise an exception because we've proxied the manager due to prefetch_related
    usage (or lack thereof)
    """
    if instance is None:
        return self

    if self.reverse is True:
        related_name = self.field.remote_field.get_cache_name()
    else:
        related_name = self.field.get_cache_name()

    manager = old_manytomany_descriptor_get(self, instance, cls)
    prefetch_name = manager.prefetch_cache_name

    # noinspection PyProtectedMember
    if not hasattr(instance, "_prefetched_objects_cache"):
        return MissingPrefetchRelatedManager(
            manager,
            error_message=_TMPL_MISSING_M2M_PREFETCH.format(
                attr=related_name, cls=instance.__class__.__name__,
            ),
        )
    elif (
        instance._prefetched_objects_cache
        and prefetch_name not in instance._prefetched_objects_cache
    ):
        return MissingPrefetchRelatedManager(
            manager,
            error_message=_TMPL_MISSING_M2M_PREFETCH.format(
                attr=related_name, cls=instance.__class__.__name__,
            ),
        )
    return manager


def new_foreignkey_descriptor_get_object(self, instance):
    # type: (ForwardManyToOneDescriptor, Model) -> None
    """
    In a scenario with a model like the below:

    class MyModel(models.Model):
        myfk = models.ForeignKey(...)

    this will be invoked when trying to access mymodel_instance.myfk
    without having either used prefetch_related() or select_related()
    """
    raise MissingRelationField(
        _TMPL_MISSING_LOCAL_FK.format(
            attr=self.field.get_cache_name(), cls=instance.__class__.__name__,
        )
    )


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

    if invalid_relations is True:

        patched_manytoone = getattr(ForwardManyToOneDescriptor, "_shouty", False)
        if patched_manytoone is False:
            ForwardManyToOneDescriptor.get_object = new_foreignkey_descriptor_get_object

        # patched_onetoone = getattr(ForwardManyToOneDescriptor, "_shouty", False)
        # ForwardOneToOneDescriptor

        patched_manytomany = getattr(ManyToManyDescriptor, "_shouty", False)
        if patched_manytomany is False:
            ManyToManyDescriptor.__get__ = new_manytomany_descriptor_get

    if invalid_reverse_relations is True:
        patched_reverse_onetone = getattr(ReverseOneToOneDescriptor, "_shouty", False)
        if patched_reverse_onetone is False:
            ReverseOneToOneDescriptor.__get__ = new_reverse_onetoone_descriptor_get

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
        # The import of settings is deferred until here so that help(shoutyorm)
        # and by extension "$ pydoc shoutyorm" both work instead of barfing
        # about django not being configured yet.
        from django.conf import settings

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
    from django.conf import settings

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
    from django.db.models import Prefetch
    from django.contrib.auth.models import User, Group, Permission
    from django.contrib.contenttypes.models import ContentType
    from django import forms
    from django.template import Template, Context

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
            q = 1
            if DJANGO_VERSION[0:2] < (3, 0):
                q = 2
            with self.assertNumQueries(q):
                group.user_set.add(user)
            with self.assertNumQueries(1):
                group.user_set.remove(user)
            with self.assertNumQueries(2):
                self.assertIsNone(group.user_set.first())
                self.assertIsNone(group.user_set.last())
            q = 2
            if DJANGO_VERSION[0:2] < (3, 0):
                q = 3
            with self.assertNumQueries(q):
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

    class MostlyM2MPrefetchRelatedTestCase(TestCase):  # type: ignore
        def setUp(self):
            # type: () -> None
            # Have to import the exceptions here to avoid __main__.ExceptionCls
            # not being the same as shoutyorm.ExceptionCls, otherwise the test
            # cases have to be outside the __main__ block.
            # noinspection PyUnresolvedReferences
            from shoutyorm import MissingRelationField

            self.MissingRelationField = MissingRelationField
            self.user = User.objects.create()

        def test_accessing_nonprefetched_m2m_works_when_trying_to_add(self):
            # type: () -> None
            """
            There are certain methods you want to access on an m2m which disregard
            the prefetch cache and should specifically not error.
            """
            with self.assertNumQueries(1):
                i = User.objects.get(pk=self.user.pk)
            q = 2
            if DJANGO_VERSION[0:2] < (3, 0):
                q = 3
            with self.assertNumQueries(q):
                i.groups.add(Group.objects.create(name="test"))

        def test_accessing_nonprefetched_m2m_fails_when_accessing_all(self):
            # type: () -> None
            """
            Normal use case - failure to prefetch should error loudly
            """
            with self.assertNumQueries(1):
                i = User.objects.get(pk=self.user.pk)
                with self.assertRaisesMessage(
                    self.MissingRelationField,
                    "Access to 'groups' ManyToMany manager attribute on User was prevented because it was not selected; probably missing from prefetch_related()",
                ):
                    i.groups.all()
                with self.assertRaisesMessage(
                    self.MissingRelationField,
                    "Access to 'user_permissions' ManyToMany manager attribute on User was prevented because it was not selected; probably missing from prefetch_related()",
                ):
                    i.user_permissions.all()

        def test_accessing_nonprefetched_nested_relations_fails(self):
            # type: () -> None
            """
            It's OK to access groups because we prefetched it, but accessing
            the group's permissions is NOT ok.
            """
            self.user.groups.add(Group.objects.create(name="test"))
            with self.assertNumQueries(2):
                i = User.objects.prefetch_related("groups").get(pk=self.user.pk)
            with self.assertNumQueries(0):
                tuple(i.groups.all())
                with self.assertRaisesMessage(
                    self.MissingRelationField,
                    "Access to 'permissions' ManyToMany manager attribute on Group was prevented because it was not selected; probably missing from prefetch_related()",
                ):
                    i.groups.all()[0].permissions.all()

        def test_accessing_prefetched_nested_relations_is_ok(self):
            # type: () -> None
            """
            If we've pre-selected groups and the permissions on those groups,
            it should be fine to access any permissions in any index of the
            groups queryset.
            """
            self.user.groups.add(Group.objects.create(name="test"))
            with self.assertNumQueries(3):
                i = User.objects.prefetch_related("groups", "groups__permissions").get(
                    pk=self.user.pk
                )
            with self.assertNumQueries(0):
                tuple(i.groups.all())
                tuple(i.groups.all()[0].permissions.all())
                with self.assertRaisesMessage(
                    self.MissingRelationField,
                    "Access to 'user_permissions' ManyToMany manager attribute on User was prevented because it was not selected; probably missing from prefetch_related()",
                ):
                    tuple(i.user_permissions.all())

        def test_accessing_multiple_prefetched_nonnested_relations_is_ok(self):
            # type: () -> None
            """
            Accessing more than 1 prefetch at the same level is OK.
            This was part of the difficulty in figuring this out, because by the
            time you get to the second prefetch selection you need to NOT prevent
            access to the queryset until ALL prefetching looks to have finished.
            """
            self.user.groups.add(Group.objects.create(name="test"))
            with self.assertNumQueries(3):
                i = User.objects.prefetch_related("groups", "user_permissions").get(
                    pk=self.user.pk
                )
            with self.assertNumQueries(0):
                tuple(i.groups.all())
                tuple(i.user_permissions.all())

        def test_accessing_relations_involving_prefetch_objects_is_ok(self):
            # type: () -> None
            """
            Make sure using a Prefetch object doesn't throw a spanner in the works.
            """
            self.user.groups.add(Group.objects.create(name="test"))
            with self.assertNumQueries(4):
                i = User.objects.prefetch_related(
                    Prefetch("groups", Group.objects.all()),
                    "groups__permissions",
                    "user_permissions",
                ).get(pk=self.user.pk)
            with self.assertNumQueries(0):
                tuple(i.groups.all())
                tuple(i.user_permissions.all())
                tuple(i.groups.all()[0].permissions.all())

        def test_accessing_relations_involving_prefetch_objects_is_ok2(self):
            # type: () -> None
            """
            Make sure using a Prefetch object doesn't throw a spanner in the works.
            """
            self.user.groups.add(Group.objects.create(name="test"))
            with self.assertNumQueries(4):
                i = User.objects.prefetch_related(
                    "groups",
                    Prefetch("groups__permissions", Permission.objects.all()),
                    "user_permissions",
                ).get(pk=self.user.pk)
            with self.assertNumQueries(0):
                tuple(i.groups.all())
                tuple(i.user_permissions.all())
                tuple(i.groups.all()[0].permissions.all())

    class PrefetchReverseRelatedTestCase(TestCase):  # type: ignore
        """
        Demonstrate how
        - new_manytomany_descriptor_get
        - new_modeliterable_iter
        interact with things.
        """

        def setUp(self):
            # type: () -> None
            # Have to import the exceptions here to avoid __main__.ExceptionCls
            # not being the same as shoutyorm.ExceptionCls, otherwise the test
            # cases have to be outside the __main__ block.
            # noinspection PyUnresolvedReferences
            from shoutyorm import MissingRelationField

            self.MissingRelationField = MissingRelationField
            self.group = Group.objects.create()

        def test_accessing_nonprefetched_m2m_works_when_trying_to_add(self):
            # type: () -> None
            """
            There are certain methods you want to access on an m2m which disregard
            the prefetch cache and should specifically not error.
            """
            with self.assertNumQueries(1):
                i = Group.objects.get(pk=self.group.pk)
            q = 2
            if DJANGO_VERSION[0:2] < (3, 0):
                q = 3
            with self.assertNumQueries(q):
                i.user_set.add(User.objects.create())

        def test_accessing_nonprefetched_m2m_fails_when_accessing_all(self):
            # type: () -> None
            """
            Normal use case - failure to prefetch should error loudly
            """
            with self.assertNumQueries(1):
                i = Group.objects.get(pk=self.group.pk)
                with self.assertRaisesMessage(
                    self.MissingRelationField,
                    "Access to 'user_set' ManyToMany manager attribute on Group was prevented because it was not selected; probably missing from prefetch_related()",
                ):
                    i.user_set.all()

        def test_accessing_nonprefetched_nested_relations_fails(self):
            # type: () -> None
            """
            It's OK to access groups because we prefetched it, but accessing
            the group's permissions is NOT ok.
            """
            self.group.user_set.add(User.objects.create())
            with self.assertNumQueries(2):
                i = Group.objects.prefetch_related("user_set").get(pk=self.group.pk)
            with self.assertNumQueries(0):
                tuple(i.user_set.all())
                with self.assertRaisesMessage(
                    self.MissingRelationField,
                    "Access to 'user_permissions' ManyToMany manager attribute on User was prevented because it was not selected; probably missing from prefetch_related()",
                ):
                    i.user_set.all()[0].user_permissions.all()

        def test_accessing_prefetched_nested_relations_is_ok(self):
            # type: () -> None
            """
            If we've pre-selected groups and the permissions on those groups,
            it should be fine to access any permissions in any index of the
            groups queryset.
            """
            self.group.user_set.add(User.objects.create())
            with self.assertNumQueries(3):
                i = Group.objects.prefetch_related(
                    "user_set", "user_set__user_permissions"
                ).get(pk=self.group.pk)
            with self.assertNumQueries(0):
                tuple(i.user_set.all())
                tuple(i.user_set.all()[0].user_permissions.all())

        def test_accessing_multiple_prefetched_nonnested_relations_is_ok(self):
            # type: () -> None
            """
            Accessing more than 1 prefetch at the same level is OK.
            This was part of the difficulty in figuring this out, because by the
            time you get to the second prefetch selection you need to NOT prevent
            access to the queryset until ALL prefetching looks to have finished.
            """
            self.group.user_set.add(User.objects.create())
            with self.assertNumQueries(3):
                i = Group.objects.prefetch_related("user_set", "permissions").get(
                    pk=self.group.pk
                )
            with self.assertNumQueries(0):
                tuple(i.user_set.all())
                tuple(i.permissions.all())

        def test_accessing_relations_involving_prefetch_objects_is_ok(self):
            # type: () -> None
            """
            Make sure using a Prefetch object doesn't throw a spanner in the works.
            """
            self.group.user_set.add(User.objects.create())
            with self.assertNumQueries(3):
                i = Group.objects.prefetch_related(
                    Prefetch("user_set", User.objects.all()),
                    "user_set__user_permissions",
                ).get(pk=self.group.pk)
            with self.assertNumQueries(0):
                tuple(i.user_set.all())
                tuple(i.user_set.all()[0].user_permissions.all())

        def test_accessing_relations_involving_prefetch_objects_is_ok2(self):
            # type: () -> None
            """
            Make sure using a Prefetch object doesn't throw a spanner in the works.
            """
            self.group.user_set.add(User.objects.create())
            with self.assertNumQueries(3):
                i = Group.objects.prefetch_related(
                    "user_set",
                    Prefetch("user_set__user_permissions", Permission.objects.all()),
                ).get(pk=self.group.pk)
            with self.assertNumQueries(0):
                tuple(i.user_set.all())
                tuple(i.user_set.all()[0].user_permissions.all())

    class ForwardManyToOneDescriptorTestCase(TestCase):  # type: ignore
        def setUp(self):
            # type: () -> None
            # Have to import the exceptions here to avoid __main__.ExceptionCls
            # not being the same as shoutyorm.ExceptionCls, otherwise the test
            # cases have to be outside the __main__ block.
            # noinspection PyUnresolvedReferences
            from shoutyorm import MissingRelationField, MissingLocalField

            self.MissingLocalField = MissingLocalField
            self.MissingRelationField = MissingRelationField

        # noinspection PyStatementEffect
        def test_accessing_fks_on_this_side_fails_if_not_prefetched(self):
            # type: () -> None
            from django.contrib.admin.models import LogEntry
            from django.contrib.auth.models import User
            from django.contrib.contenttypes.models import ContentType

            example = LogEntry.objects.create(
                user=User.objects.create(),
                content_type=ContentType.objects.get_for_model(User),
                object_id="",
                object_repr="",
                action_flag=1,
                change_message="",
            )
            with self.assertNumQueries(1):
                i = LogEntry.objects.get(pk=example.pk)
            with self.assertNumQueries(0):
                i.object_id
                i.object_repr
                i.action_flag
                i.change_message
                with self.assertRaisesMessage(
                    self.MissingRelationField,
                    "Access to 'user' attribute on LogEntry was prevented because it was not selected; probably missing from prefetch_related() or select_related()",
                ):
                    i.user.pk
                with self.assertRaisesMessage(
                    self.MissingRelationField,
                    "Access to 'content_type' attribute on LogEntry was prevented because it was not selected; probably missing from prefetch_related() or select_related()",
                ):
                    i.content_type.pk

        # noinspection PyStatementEffect
        def test_accessing_fks_on_this_side_ok_if_selected(self):
            # type: () -> None
            from django.contrib.admin.models import LogEntry
            from django.contrib.auth.models import User
            from django.contrib.contenttypes.models import ContentType

            example = LogEntry.objects.create(
                user=User.objects.create(),
                content_type=ContentType.objects.get_for_model(User),
                object_id="",
                object_repr="",
                action_flag=1,
                change_message="",
            )
            with self.assertNumQueries(1):
                i = LogEntry.objects.select_related("content_type", "user").get(
                    pk=example.pk
                )
            with self.assertNumQueries(0):
                i.object_id
                i.object_repr
                i.action_flag
                i.change_message
                i.user.pk
                i.content_type.pk

        # noinspection PyStatementEffect
        def test_accessing_fks_on_this_side_ok_if_prefetched(self):
            # type: () -> None
            from django.contrib.admin.models import LogEntry
            from django.contrib.auth.models import User
            from django.contrib.contenttypes.models import ContentType

            example = LogEntry.objects.create(
                user=User.objects.create(),
                content_type=ContentType.objects.get_for_model(User),
                object_id="",
                object_repr="",
                action_flag=1,
                change_message="",
            )
            with self.assertNumQueries(3):
                i = LogEntry.objects.prefetch_related("content_type", "user").get(
                    pk=example.pk
                )
            with self.assertNumQueries(0):
                i.object_id
                i.object_repr
                i.action_flag
                i.change_message
                i.user.pk
                i.content_type.pk

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
            # type: () -> None
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

        def test_manytomany_in_form_is_ok_if_prefetched(self):
            # type: () -> None
            """
            Prove that modelform generation IS effected on a model's local
            manytomany field.
            """
            instance = User.objects.create()

            class UserForm(forms.ModelForm):  # type: ignore
                class Meta:
                    model = User
                    fields = "__all__"

            with self.assertNumQueries(3):
                obj = User.objects.prefetch_related("groups", "user_permissions").get(
                    pk=instance.pk
                )
            with self.assertNumQueries(0):
                UserForm(data=None, instance=obj)

        def test_manytomany_in_form_fails_if_not_prefetched(self):
            # type: () -> None
            """
            Prove that modelform generation IS effected on a model's local
            manytomany field.
            """
            instance = User.objects.create()

            class UserForm(forms.ModelForm):  # type: ignore
                class Meta:
                    model = User
                    fields = "__all__"

            with self.assertNumQueries(1):
                obj = User.objects.get(pk=instance.pk)
                with self.assertRaisesMessage(
                    self.MissingRelationField,
                    "Access to 'groups' ManyToMany manager attribute on User was prevented because it was not selected; probably missing from prefetch_related()",
                ):
                    UserForm(data=None, instance=obj)

    class TemplateTestCase(TestCase):  # type: ignore
        """
        Got to check that the exceptions
        """

        def setUp(self):
            # type: () -> None
            from shoutyorm import MissingLocalField, MissingRelationField

            self.MissingLocalField = MissingLocalField
            self.MissingRelationField = MissingRelationField

        def test_local(self):
            # type: () -> None
            u = User.objects.create(
                first_name="test",
                last_name="test",
                username="testu",
                email="test@test.com",
            )
            u = User.objects.only("pk", "first_name", "date_joined").get(pk=u.pk)
            tmpl = Template(
                """
            {{ u.pk }}, {{ u.first_name }}, {{ u.date_joined }}, {{ u.last_name }}
            """
            )
            with self.assertRaisesMessage(
                self.MissingLocalField,
                "Access to 'last_name' attribute on User was prevented because it was not selected; probably defer() or only() were used.",
            ):
                tmpl.render(Context({"u": u,}))

        def test_local_foreignkey(self):
            # type: () -> None
            p = Permission.objects.all()[0]
            tmpl = Template(
                """
            {{ p.pk }}, {{ p.codename }}, {{ p.content_type_id }}, {{ p.content_type.pk }}
            """
            )
            with self.assertRaisesMessage(
                self.MissingRelationField,
                "Access to 'content_type' attribute on Permission was prevented because it was not selected; probably missing from prefetch_related() or select_related()",
            ):
                tmpl.render(Context({"p": p,}))

        def test_reverse_foreignkey(self):
            # type: () -> None
            ct = ContentType.objects.all()[0]
            tmpl = Template(
                """
            {{ ct.pk }}, {{ ct.app_label }}, {{ ct.model }}, {% for p in ct.permission_set.all %}{{ p }}{% endfor %}
            """
            )
            with self.assertRaisesMessage(
                self.MissingRelationField,
                "Access to reverse manager 'permission_set' on ContentType was prevented because it was not selected; probably missing from prefetch_related()",
            ):
                tmpl.render(Context({"ct": ct,}))

        def test_local_m2m(self):
            # type: () -> None
            u = User.objects.create(
                first_name="test",
                last_name="test",
                username="testu",
                email="test@test.com",
            )
            tmpl = Template(
                """
            {{ u.pk }}, {{ u.username }}, {% for g in u.groups.all %}{{ g }}{% endfor %}
            """
            )
            with self.assertRaisesMessage(
                self.MissingRelationField,
                "Access to 'groups' ManyToMany manager attribute on User was prevented because it was not selected; probably missing from prefetch_related()",
            ):
                tmpl.render(Context({"u": u,}))

        def test_reverse_m2m(self):
            # type: () -> None
            g = Group.objects.create()
            tmpl = Template(
                """
            {{ g.pk }}, {% for u in g.user_set.all %}{{ u }}{% endfor %}
            """
            )
            with self.assertRaisesMessage(
                self.MissingRelationField,
                "Access to 'user_set' ManyToMany manager attribute on Group was prevented because it was not selected; probably missing from prefetch_related()",
            ):
                tmpl.render(Context({"g": g,}))

    class MyPyTestCase(TestCase):  # type: ignore
        def test_for_types(self):
            # type: () -> None
            try:
                from mypy import api as mypy
            except ImportError:
                return
            else:
                here = os.path.abspath(__file__)
                report, errors, exit_code = mypy.run(
                    ["--strict", "--ignore-missing-imports", here]
                )
                if errors:
                    self.fail(errors)
                elif exit_code > 0:
                    self.fail(report)

    test_runner = DiscoverRunner(interactive=False, verbosity=2)
    failures = test_runner.run_tests(
        test_labels=(),
        extra_tests=(
            test_runner.test_loader.loadTestsFromTestCase(LocalFieldsTestCase),
            test_runner.test_loader.loadTestsFromTestCase(NormalRelationFieldsTestCase),
            test_runner.test_loader.loadTestsFromTestCase(
                MostlyM2MPrefetchRelatedTestCase
            ),
            test_runner.test_loader.loadTestsFromTestCase(
                PrefetchReverseRelatedTestCase
            ),
            test_runner.test_loader.loadTestsFromTestCase(
                ReverseRelationFieldsTestCase
            ),
            test_runner.test_loader.loadTestsFromTestCase(FormTestCase),
            test_runner.test_loader.loadTestsFromTestCase(TemplateTestCase),
            test_runner.test_loader.loadTestsFromTestCase(
                ForwardManyToOneDescriptorTestCase
            ),
            test_runner.test_loader.loadTestsFromTestCase(MyPyTestCase),
        ),
    )
