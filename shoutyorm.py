# -*- coding: utf-8 -*-
from __future__ import absolute_import, unicode_literals

import logging

from django.test import TestCase

try:
    # noinspection PyUnresolvedReferences
    from typing import Text, Any
except ImportError:
    pass

from django.apps import AppConfig
from django.conf import settings
from django.db.models import Model

# noinspection PyUnresolvedReferences
from django.db.models.fields.related_descriptors import (
    ReverseOneToOneDescriptor,
    ReverseManyToOneDescriptor,
    ForwardManyToOneDescriptor,
    ForwardOneToOneDescriptor,  # noqa: F401
    ManyToManyDescriptor,  # noqa: F401
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


__all__ = [
    "get_version",
    "ShoutyAttributeError",
    "MissingLocalField",
    "MissingRelationField",
    "patch",
    "Shout",
    "default_app_config",
]


# This is when you try an access a local field on a model.
old_model_getattribute = Model.__getattribute__


def new_model_getattribute(self, name):
    # type: (Model, Text) -> Any
    """
    This should be invoked on eeeevery attribute access for a Model, looking at
    all the local fields on the Model (I think).

    If the requested name is something fieldish and isn't in the underlying
    class instance's secret dict, it's presumably been deselected via
    `.only()` or `.defer()` on the QuerySet.
    """
    fieldnames = frozenset(
        x.attname for x in old_model_getattribute(self, "_meta").fields
    )
    values = frozenset(old_model_getattribute(self, "__dict__"))
    if name in fieldnames and name not in values:
        cls_name = old_model_getattribute(self, "__class__").__name__
        raise MissingLocalField(
            "Access to '{attr}' attribute on {cls} was prevented because it was not selected; probably defer() or only() were used.".format(
                attr=name, cls=cls_name,
            )
        )
    return old_model_getattribute(self, name)


# This is when you do "mymodel.myfield" where "myfield" is a OneToOneField
# on MyOtherModel which points back to MyModel
#
# In an ideal world I'd patch get_queryset() directly, but that's used by
# the get_prefetch_queryset() implementations and I don't know the ramifications
# of doing so, so instead we're going to proxy the "public" API.
old_reverse_onetoone_descriptor_get = ReverseOneToOneDescriptor.__get__


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


# This is when you do "mymodel.myothermodel_set.all()" where the foreignkey
# exists on "MyOtherModel" and POINTS to "MyModel"
#
# In an ideal world I'd patch get_queryset() directly, but that's used by
# the get_prefetch_queryset() implementations and I don't know the ramifications
# of doing so, so instead we're going to proxy the "public" API.
old_reverse_foreignkey_descriptor_get = ReverseManyToOneDescriptor.__get__


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
        raise MissingRelationField(
            "Access to '{attr}' manager attribute on {cls} was prevented because it was not selected; probably missing from prefetch_related()".format(
                attr=related_name, cls=instance.__class__.__name__,
            )
        )
    elif (
        instance._prefetched_objects_cache
        and related_name not in instance._prefetched_objects_cache
    ):
        raise MissingRelationField(
            "Access to '{attr}' manager attribute on {cls} was prevented because it was not part of the prefetch_related() selection used".format(
                attr=related_name, cls=instance.__class__.__name__,
            )
        )
    return old_reverse_foreignkey_descriptor_get(self, instance, cls)


old_manytomany_descriptor_get = ManyToManyDescriptor.__get__


# noinspection PyProtectedMember
def new_manytomany_descriptor_get(self, instance, cls=None):
    # type: (ManyToManyDescriptor, Model, None) -> Any
    if instance is None:
        return self

    if self.reverse is True:
        related_name = self.field.remote_field.get_cache_name()
    else:
        related_name = self.field.get_cache_name()

    if not hasattr(instance, "_prefetched_objects_cache"):
        raise MissingRelationField(
            "Access to '{attr}' ManyToMany manager attribute on {cls} was prevented because it was not selected; probably missing from prefetch_related()".format(
                attr=related_name, cls=instance.__class__.__name__,
            )
        )
    elif (
        instance._prefetched_objects_cache
        and related_name not in instance._prefetched_objects_cache
    ):
        raise MissingRelationField(
            "Access to '{attr}' ManyToMany manager attribute on {cls} was prevented because it was not part of the prefetch_related() selection used".format(
                attr=related_name, cls=instance.__class__.__name__,
            )
        )
    return old_manytomany_descriptor_get(self, instance, cls)


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


def patch(invalid_locals, invalid_relations):
    # type: (bool, bool) -> bool
    """
    if invalid_locals is True, accessing fields which have been
    deferred via `.only()` and `.defer()` at the QuerySet level will error loudly.

    if invalid_relations is True, accessing OneToOnes which have not
    been `.select_related()` at the QuerySet level will error loudly.

    if invalid_relations is True, accessing foreignkeys from the "other"
    side (that is, via the reverse relation manager) which have not
    been `.prefetch_related()` at the QuerySet level will error loudly.


    if invalid_relations is turned on, accessing local foreignkeys
    which have not been `prefetch_related()` or `select_related()` at the queryset
    level will error loudly.
    """
    patched_getattribute = getattr(Model, "_shouty", False)
    if invalid_locals is True:
        if patched_getattribute is False:
            Model.__getattribute__ = new_model_getattribute
    patched_reverse_onetone = getattr(ReverseOneToOneDescriptor, "_shouty", False)
    patched_reverse_manytoone = getattr(ReverseManyToOneDescriptor, "_shouty", False)
    patched_manytoone = getattr(ForwardManyToOneDescriptor, "_shouty", False)
    patched_manytomany = getattr(ManyToManyDescriptor, "_shouty", False)
    if invalid_relations is True:
        if patched_reverse_onetone is False:
            ReverseOneToOneDescriptor.__get__ = new_reverse_onetoone_descriptor_get
        if patched_reverse_manytoone is False:
            ReverseManyToOneDescriptor.__get__ = new_reverse_foreignkey_descriptor_get
        if patched_manytoone is False:
            ForwardManyToOneDescriptor.get_object = new_foreignkey_descriptor_get_object
        if patched_manytomany is False:
            ManyToManyDescriptor.__get__ = new_manytomany_descriptor_get
    return True


class Shout(AppConfig):  # type: ignore
    """
    Applies the patch automatically if enabled by adding `shoutyorm` or
    `shoutyorm.Shout` to INSTALLED_APPS.

    if SHOUTY_LOCAL_FIELDS is turned on, accessing fields which have been
    deferred via `.only()` and `.defer()` at the QuerySet level will error loudly.

    if SHOUTY_RELATION_FIELDS is turned on, accessing OneToOnes which have not
    been `.select_related()` at the QuerySet level will error loudly.

    if SHOUTY_RELATION_FIELDS is turned on, accessing foreignkeys from the "other"
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
        )


default_app_config = "shoutyorm.Shout"


if __name__ == "__main__":
    # from django.conf import global_settings
    # from django.test.utils import get_runner
    from django.test.runner import DiscoverRunner
    import django

    settings.configure(
        DATABASES={
            "default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}
        },
        INSTALLED_APPS=(
            "django.contrib.contenttypes",
            "django.contrib.auth",
            "shoutyorm",
        ),
    )
    django.setup()
    from django.contrib.auth.models import User, Permission
    from django.contrib.contenttypes.models import ContentType
    from django import forms

    # noinspection PyStatementEffect
    class LocalFieldsTestCase(TestCase):  # type: ignore
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
                User.objects.get(pk=self.instance.pk)

        # noinspection PyStatementEffect
        def test_only_local(self):
            # type: () -> None
            with self.assertNumQueries(1):
                obj = User.objects.only("pk").get(pk=self.instance.pk)  # type: User
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
                obj.pk
                obj.id
                obj.first_name
                # noinspection PyUnresolvedReferences
                self.assertTrue(obj.testing)
                # noinspection PyUnresolvedReferences
                self.assertEqual(obj.testing_aliasing, obj.first_name)
                with self.assertRaises(self.MissingLocalField):
                    obj.last_name

    # noinspection PyStatementEffect
    class NormalRelationFieldsTestCase(TestCase):  # type: ignore
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
            with self.assertNumQueries(1):
                obj = Permission.objects.all()[0]  # type: Permission
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
            with self.assertNumQueries(1):
                obj = Permission.objects.select_related("content_type").all()[
                    0
                ]  # type: Permission
                obj.name
                obj.codename
                obj.content_type_id
                obj.content_type.pk

        def test_accessing_foreignkey_with_prefetch_related(self):
            # type: () -> None
            with self.assertNumQueries(2):
                obj = Permission.objects.prefetch_related("content_type").all()[
                    0
                ]  # type: Permission
                obj.name
                obj.codename
                obj.content_type_id
                obj.content_type.pk

    # noinspection PyStatementEffect
    class ReverseRelationFieldsTestCase(TestCase):  # type: ignore
        def setUp(self):
            # type: () -> None
            # Have to import the exceptions here to avoid __main__.ExceptionCls
            # not being the same as shoutyorm.ExceptionCls, otherwise the test
            # cases have to be outside the __main__ block.
            # noinspection PyUnresolvedReferences
            from shoutyorm import MissingRelationField

            self.MissingRelationField = MissingRelationField

        def test_accessing_other_side_of_foreignkey(self):
            # type: () -> None
            with self.assertNumQueries(1):
                obj = ContentType.objects.all()[0]  # type: ContentType
                obj.app_label
                obj.model
                with self.assertRaisesMessage(
                    self.MissingRelationField,
                    "Access to 'permission_set' manager attribute on ContentType was prevented because it was not selected; probably missing from prefetch_related()",
                ):
                    obj.permission_set.all()

        def test_accessing_other_side_of_foreignkey_with_prefetch_related(self):
            # type: () -> None
            with self.assertNumQueries(2):
                obj = ContentType.objects.prefetch_related("permission_set").all()[
                    0
                ]  # type: ContentType
                obj.app_label
                obj.model
                set(obj.permission_set.all())

    class FormTestCase(TestCase):  # type: ignore
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
            :return:
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

        def test_manytomany_in_form(self):
            # type: () -> None
            """
            Prove that modelform generation IS effected on a model's local
            manytomany field.
            :return:
            """
            instance = User.objects.create()

            class UserForm(forms.ModelForm):  # type: ignore
                class Meta:
                    model = User
                    fields = "__all__"

            with self.assertNumQueries(1):
                obj = User.objects.only("pk", "first_name").get(pk=instance.pk)
                with self.assertRaises(self.MissingLocalField):
                    UserForm(data=None, instance=obj)
            with self.assertNumQueries(1):
                obj = User.objects.get(pk=instance.pk)
                with self.assertRaisesMessage(
                    self.MissingRelationField,
                    "Access to 'groups' ManyToMany manager attribute on User was prevented because it was not selected; probably missing from prefetch_related()",
                ):
                    UserForm(data=None, instance=obj)

    test_runner = DiscoverRunner(interactive=False,)
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
