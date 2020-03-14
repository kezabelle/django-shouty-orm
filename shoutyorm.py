# -*- coding: utf-8 -*-
from __future__ import absolute_import, unicode_literals

import logging
from django import VERSION as django_version
from django.core.exceptions import ValidationError
from django.db.models.query import ModelIterable, QuerySet, Prefetch
from django.db.models.query_utils import DeferredAttribute

try:
    # noinspection PyUnresolvedReferences
    from typing import Text, Any, Dict
except ImportError:  # pragma: no cover
    pass

from django.apps import AppConfig
from django.conf import settings
from django.db.models import Model

from django.db.models.fields.related_descriptors import (
    ReverseOneToOneDescriptor,
    ReverseManyToOneDescriptor,
    ForwardManyToOneDescriptor,
    ForwardOneToOneDescriptor,
    ManyToManyDescriptor,
    create_forward_many_to_many_manager,
)

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

# Used to attach additional variables onto each model instance in a normal
# queryset. It's necessary for early knowledge of what might've been requested
# in terms of prefetch_related() usages on the queryset.
old_modeliterable_iter = ModelIterable.__iter__

# Used to ensure that certain variables are copied when cloning a queryset so
# that they travel with the new copy.
# TODO: remove?
old_queryset_clone = QuerySet._clone

# Used to attach a variable indicating whether or not any prefetch has been
# requested, or if it's been reset.
# TODO: remove?
old_queryset_prefetch_related = QuerySet.prefetch_related

# Used to reset certain variables on the queryset once all prefetches have finished.
# TODO: remove?
old_queryset_prefetch_related_objects = QuerySet._prefetch_related_objects

# This is used so that when .only() and .defer() are used, I can prevent the
# bit which would cause a query for unselected fields.
old_deferredattribute_check_parent_chain = DeferredAttribute._check_parent_chain

# This is when you do "mymodel.myfield" where "myfield" is a OneToOneField
# on MyOtherModel which points back to MyModel
#
# In an ideal world I'd patch get_queryset() directly, but that's used by
# the get_prefetch_queryset() implementations and I don't know the ramifications
# of doing so, so instead we're going to proxy the "public" API.
old_reverse_onetoone_descriptor_get = ReverseOneToOneDescriptor.__get__

# This is when you do "mymodel.myothermodel_set.all()" where the foreignkey
# exists on "MyOtherModel" and POINTS to "MyModel"
#
# In an ideal world I'd patch get_queryset() directly, but that's used by
# the get_prefetch_queryset() implementations and I don't know the ramifications
# of doing so, so instead we're going to proxy the "public" API.
old_reverse_foreignkey_descriptor_get = ReverseManyToOneDescriptor.__get__

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


def new_modeliterable_iter(self):
    """
    This patch is necessary for early knowledge of what might've been requested
    in terms of prefetch_related() usages on the queryset.
    It has to be here so that during the getattribute calls involving an m2m
    I know whether or not we're doing a prefetch, and whether it's finished.
    """
    qs = self.queryset
    for obj in old_modeliterable_iter(self):
        obj._shouty_prefetch_done = qs._prefetch_done
        obj._shouty_prefetch_related_lookups = qs._prefetch_related_lookups
        obj._shouty_known_related_objects = qs._known_related_objects
        obj._shouty_is_prefetching = getattr(qs, "_shouty_is_prefetching", None)
        obj._shouty_sealed = True
        yield obj


# TODO: remove?
def new_queryset_clone(self):
    clone = old_queryset_clone(self)
    clone._shouty_is_prefetching = getattr(self, "_shouty_is_prefetching", None)
    return clone


# TODO: remove?
def new_queryset_prefetch_related(self, *lookups):
    clone = old_queryset_prefetch_related(self, *lookups)
    clone._shouty_is_prefetching = lookups != (None,)
    return clone


# TODO: remove?
def new_queryset_prefetch_related_objects(self):
    old_queryset_prefetch_related_objects(self)
    self._shouty_is_prefetching = False


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
            "Access to '{attr}' relation attribute on {cls} was prevented because it was not selected; probably missing from select_related()".format(
                attr=attr, cls=instance.__class__.__name__,
            )
        )
    return old_reverse_onetoone_descriptor_get(self, instance, cls)


# noinspection PyProtectedMember
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

    if not hasattr(instance, "_prefetched_objects_cache"):
        raise MissingReverseRelationField(
            _TMPL_MISSING_ANY_PREFETCH_REVERSE.format(
                attr=related_name, cls=instance.__class__.__name__,
            )
        )
    elif (
        instance._prefetched_objects_cache
        and related_name not in instance._prefetched_objects_cache
    ):
        raise MissingReverseRelationField(
            _TMPL_MISSING_SPECIFIC_PREFETCH_REVERSE.format(
                attr=related_name, cls=instance.__class__.__name__,
            )
        )
    manager = old_reverse_foreignkey_descriptor_get(self, instance, cls)
    return manager


old_create_forward_many_to_many_manager = create_forward_many_to_many_manager


def new_create_forward_many_to_many_manager(superclass, rel, reverse):
    x = old_create_forward_many_to_many_manager(superclass, rel, reverse)
    #     .reverse is True:
    #     related_name = self.field.remote_field.get_cache_name()
    #
    # else:
    # related_name = self.field.get_cache_name()
    class PreventingManager(x):
        def __init__(self, instance=None):
            super().__init__(instance=instance)
            prefetch_name = self.prefetch_cache_name
            # If we hit this, we must either have either been through
            # refresh_from_db() or prefetch_related_objects() at some point.
            # It could be that we've subsequently been in _remove_prefetched_objects()
            # and the data has been manually emptied.
            if hasattr(instance, "_prefetched_objects_cache"):
                if instance._prefetched_objects_cache == {}:
                    pass
                elif hasattr(instance, "_shouty_prefetch_related_lookups"):
                    if (
                        # prefetch_name not in instance._shouty_prefetch_related_lookups
                        prefetch_name
                        not in instance._prefetched_objects_cache
                    ):
                        raise MissingRelationField(
                            "Access to '{attr}' ManyToMany manager attribute on {cls} was prevented because it was not selected; probably missing from prefetch_related()".format(
                                attr="fuck", cls=self.model,
                            )
                        )

    return PreventingManager


# noinspection PyProtectedMember
def new_manytomany_descriptor_get(self, instance, cls=None):
    # type: (ManyToManyDescriptor, Model, None) -> Any
    if instance is None:
        return self

    if self.reverse is True:
        related_name = self.field.remote_field.get_cache_name()
    else:
        related_name = self.field.get_cache_name()

    manager = old_manytomany_descriptor_get(self, instance, cls)
    prefetch_name = manager.prefetch_cache_name

    class PreventingManager(object):
        __slots__ = ("manager", "attr", "cls_name")

        def __init__(self, wrapped_manager, related_attr, related_clsname):
            self.manager = wrapped_manager
            self.attr = related_attr
            self.cls_name = related_clsname

        def get_prefetch_queryset(self, instances, queryset=None):
            return self.manager.get_prefetch_queryset(
                instances=instances, queryset=queryset
            )

        def get_queryset(self):
            return self.manager.get_queryset()

        def add(self, *objs, through_defaults=None):
            return self.manager.add(*objs, through_defaults=through_defaults)

        add.alters_data = True

        def remove(self, *objs):
            return self.manager.remove(*objs)

        remove.alters_data = True

        def clear(self):
            return self.manager.clear()

        clear.alters_data = True

        def set(self, objs, *, clear=False, through_defaults=None):
            return self.manager.set(
                objs, clear=clear, through_defaults=through_defaults
            )

        set.alters_data = True

        def create(self, *, through_defaults=None, **kwargs):
            return self.manager.create(through_defaults=through_defaults, **kwargs)

        create.alters_data = True

        def get_or_create(self, *, through_defaults=None, **kwargs):
            return self.manager.get_or_create(
                through_defaults=through_defaults, **kwargs
            )

        get_or_create.alters_data = True

        def update_or_create(self, *, through_defaults=None, **kwargs):
            return self.manager.update_or_create(
                through_defaults=through_defaults, **kwargs
            )

        update_or_create.alters_data = True

        def all(self):
            raise MissingRelationField(
                "Access to '{attr}' ManyToMany manager attribute on {cls} was prevented because it was not selected; probably missing from prefetch_related()".format(
                    attr=self.attr, cls=self.cls_name,
                )
            )

    class MaybePreventingManager(PreventingManager):
        def filter(self):
            raise ValueError(self.attr)

        def exclude(self):
            raise ValueError(self.attr)

        def aggregate(self):
            raise ValueError(self.attr)

        def get(self):
            raise ValueError(self.attr)

        def earliest(self):
            raise ValueError(self.attr)

        def latest(self):
            raise ValueError(self.attr)

        def exists(self):
            raise ValueError(self.attr)

    # If we hit this, we must either have either been through
    # refresh_from_db() or prefetch_related_objects() at some point.
    # It could be that we've subsequently been in _remove_prefetched_objects()
    # and the data has been manually emptied.
    if hasattr(instance, "_prefetched_objects_cache"):
        if instance._prefetched_objects_cache == {}:
            return manager
        elif hasattr(instance, "_shouty_prefetch_related_lookups"):

            if (
                # prefetch_name not in instance._shouty_prefetch_related_lookups
                prefetch_name
                not in instance._prefetched_objects_cache
            ):
                return PreventingManager(
                    manager, related_name, instance.__class__.__name__
                )
            return manager
    elif hasattr(instance, "_shouty_prefetch_done"):
        return PreventingManager(manager, related_name, instance.__class__.__name__)

    return manager


def new_foreignkey_descriptor_get_object(self, instance):
    # type: (ForwardManyToOneDescriptor, Model) -> None
    """
    This should be invoked when ...
    """
    raise MissingRelationField(
        "Access to '{attr}' attribute on {cls} was prevented because it was not selected; probably missing from prefetch_related() or select_related()".format(
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
    if any((invalid_locals, invalid_relations, invalid_reverse_relations)):
        patched_modeliter = getattr(ModelIterable, "_shouty", False)
        if patched_modeliter is False:
            ModelIterable.__iter__ = new_modeliterable_iter

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

        patched_manytomany = getattr(ManyToManyDescriptor, "_shouty", False)
        if patched_manytomany is False:
            #     create_forward_many_to_many_manager = (
            #         new_create_forward_many_to_many_manager
            #     )
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

        def test_accessing_foreignkey(self):
            # type: () -> None
            """ Triggers new_foreignkey_descriptor_get_object """
            with self.assertNumQueries(1):
                obj = Permission.objects.all()[0]  # type: Permission
            with self.assertNumQueries(0):
                obj.name
                obj.codename
                obj.content_type_id
                with self.assertRaisesMessage(
                    self.MissingRelationField,
                    "Access to 'content_type' attribute on Permission was prevented because it was not selected; probably missing from prefetch_related() or select_related()",
                ):
                    obj.content_type.pk

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

    class PrefetchRelatedTestCase(TestCase):
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
            self.user = User.objects.create()

        def test_accessing_nonprefetched_m2m_works_when_trying_to_add(self):
            """
            There are certain methods you want to access on an m2m which disregard
            the prefetch cache and should specifically not error.
            """
            with self.assertNumQueries(1):
                i = User.objects.get(pk=self.user.pk)
            with self.assertNumQueries(2):
                i.groups.add(Group.objects.create(name="test"))

        def test_accessing_nonprefetched_m2m_fails_when_accessing_all(self):
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

        @expectedFailure
        def test_attempting_to_filter_prefetched_data_fails(self):
            """
            Don't allow a user to accidentally cause additional queries by
            ignoring the fact that somewhere up the qs chain a prefetch was done
            """
            self.user.groups.add(Group.objects.create(name="test"))
            with self.assertNumQueries(3):
                i = User.objects.prefetch_related("groups", "user_permissions").get(
                    pk=self.user.pk
                )
            with self.assertNumQueries(0):
                tuple(i.groups.filter(pk=1))

    class PrefetchReverseRelatedTestCase(TestCase):
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
            """
            There are certain methods you want to access on an m2m which disregard
            the prefetch cache and should specifically not error.
            """
            with self.assertNumQueries(1):
                i = Group.objects.get(pk=self.group.pk)
            with self.assertNumQueries(2):
                i.user_set.add(User.objects.create())

        def test_accessing_nonprefetched_m2m_fails_when_accessing_all(self):
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

        # @expectedFailure
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

    test_runner = DiscoverRunner(interactive=False, verbosity=2)
    failures = test_runner.run_tests(
        test_labels=(),
        extra_tests=(
            test_runner.test_loader.loadTestsFromTestCase(LocalFieldsTestCase),
            test_runner.test_loader.loadTestsFromTestCase(NormalRelationFieldsTestCase),
            test_runner.test_loader.loadTestsFromTestCase(PrefetchRelatedTestCase),
            test_runner.test_loader.loadTestsFromTestCase(
                PrefetchReverseRelatedTestCase
            ),
            test_runner.test_loader.loadTestsFromTestCase(
                ReverseRelationFieldsTestCase
            ),
            test_runner.test_loader.loadTestsFromTestCase(FormTestCase),
        ),
    )
