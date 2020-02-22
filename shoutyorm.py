# -*- coding: utf-8 -*-
from __future__ import absolute_import, unicode_literals

import logging

try:
    # noinspection PyUnresolvedReferences
    from typing import Text, Any
except ImportError:
    pass

from django.apps import AppConfig
from django.conf import settings
from django.db.models import Model
from django.db.models.fields.related_descriptors import ReverseOneToOneDescriptor

logger = logging.getLogger(__name__)


__version_info__ = "0.1.0"
__version__ = "0.1.0"
version = "0.1.0"
VERSION = "0.1.0"


def get_version():
    # type: () -> Text
    return version


old_model_getattribute = Model.__getattribute__
old_onetoone_descriptor_get = ReverseOneToOneDescriptor.__get__


class ShoutyAttributeError(AttributeError):
    pass


class MissingLocalField(ShoutyAttributeError):
    pass


class MissingRelationField(ShoutyAttributeError):
    pass


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
    if "p1age" in name:
        import pdb

        pdb.set_trace()
    if name in fieldnames and name not in values:
        cls_name = old_model_getattribute(self, "__class__").__name__
        raise MissingLocalField(
            "Access to '{attr}' attribute on {cls} was prevented because it was not selected; probably defer() or only() were used.".format(
                attr=name, cls=cls_name,
            )
        )

    return old_model_getattribute(self, name)


def new_onetoone_descriptor_get(self, instance, cls=None):
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
    return old_onetoone_descriptor_get(self, instance, cls)


def patch(invalid_locals, invalid_relations):
    # type: (bool, bool) -> bool
    patched_getattribute = getattr(Model, "_shouty", False)
    if invalid_locals is True:
        if patched_getattribute is False:
            Model.__getattribute__ = new_model_getattribute
    patched_getattribute = getattr(ReverseOneToOneDescriptor, "_shouty", False)
    if invalid_relations is True:
        if patched_getattribute is False:
            ReverseOneToOneDescriptor.__get__ = new_onetoone_descriptor_get
    return True


class Shout(AppConfig):
    """
    Applies the patch automatically if enabled by adding `shoutyorm` or
    `shoutyorm.Shout` to INSTALLED_APPS.

    if SHOUTY_LOCAL_FIELDS is turned on, accessing fields which have been
    deferred via `.only()` and `.defer()` at the QuerySet level will error loudly.

    if SHOUTY_RELATION_FIELDS is turned on, accessing OneToOnes which have not
    been `.select_related()` at the QuerySet level will error loudly.
    """

    name = "shoutyorm"

    def ready(self):
        # type: () -> bool
        logger.info("Applying shouty templates patch")
        return patch(
            invalid_locals=getattr(settings, "SHOUTY_LOCAL_FIELDS", True),
            invalid_relations=getattr(settings, "SHOUTY_RELATION_FIELDS", True),
        )


default_app_config = "shoutyorm.Shout"
