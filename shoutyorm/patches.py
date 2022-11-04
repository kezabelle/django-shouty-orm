from __future__ import annotations

import logging
from functools import wraps

try:
    from typing import Optional, Text, Any, NoReturn, Iterable, Type, TypedDict, Callable
except ImportError:  # pragma: no cover
    pass

from django import VERSION as DJANGO_VERSION
from django.db.models import Model, Manager
from django.db.models.fields.related_descriptors import (
    ReverseManyToOneDescriptor,
    ManyToManyDescriptor,
    ReverseOneToOneDescriptor,
    ForwardManyToOneDescriptor,
)
from django.db.models.query_utils import DeferredAttribute

from shoutyorm.errors import (
    MissingReverseRelationField,
    MissingLocalField,
    MissingRelationField,
    NoMoreFilteringAllowed,
    ShoutyAttributeError,
)

# Hide the patch stacks from unittest output?
__unittest = True


logger = logging.getLogger(__name__)


def exception_raising(func: Callable, exception: ShoutyAttributeError):
    __traceback_hide__ = True  # django
    __tracebackhide__ = True  # pytest (+ipython?)
    __debuggerskip__ = True  # (ipython+ipdb?)

    @wraps(func)
    def wrapper(*args, **kwargs):
        __traceback_hide__ = True  # django
        __tracebackhide__ = True  # pytest (+ipython?)
        __debuggerskip__ = True  # (ipython+ipdb?)
        exception.__cause__ = None
        raise exception

    return wrapper


def rebind_related_manager_via_descriptor(
    manager: Manager,
    instance: Model,
    model: Type[Model],
    remote_model: Type[Model],
    attr_name: str,
    related_name: str,
) -> Manager:
    escape_hatch_key = f"_shoutyorm_allow_{attr_name}"
    logger.debug("Checking for %s on %r instance", escape_hatch_key, instance)
    # Leave the manager alone, the user knows better.
    if getattr(instance, escape_hatch_key, False):
        logger.debug("escape hatch %s used for %r instance", escape_hatch_key, instance)
        return manager

    # There's no prefetch_related() call at all.
    if not hasattr(instance, "_prefetched_objects_cache"):
        manager.all = exception_raising(
            manager.all,
            MissingReverseRelationField(
                "Access to `{cls}.{attr}.all()` was prevented.\n"
                "To fetch the `{remote_cls}` objects, add `prefetch_related({attr!r})` to the query where `{cls}` objects are selected.\n"
                "You can allow access to `{attr}` on this `{cls}` instance by using `{cls_lower}.{escape_hatch} = True`",
                attr=attr_name,
                cls=model.__name__,
                cls_lower=model._meta.model_name,
                escape_hatch=escape_hatch_key,
                related_name=related_name,
                remote_cls=remote_model.__name__,
            ),
        )
    # There is a prefetch_related() call, but it doesn't include this reverse
    # model.
    elif (
        instance._prefetched_objects_cache
        and related_name not in instance._prefetched_objects_cache
    ):
        manager.all = exception_raising(
            manager.all,
            MissingReverseRelationField(
                "Access to `{cls}.{attr}.all()` was prevented.\n"
                "To fetch the `{remote_cls}` objects, add {related_name!r} to the existing `prefetch_related({existing_prefetch!s})` part of the query where `{cls}` objects are selected.\n"
                "You can allow access to `{attr}` on this `{cls}` instance by using `{cls_lower}.{escape_hatch} = True`",
                attr=attr_name,
                cls=model.__name__,
                cls_lower=model._meta.model_name,
                escape_hatch=escape_hatch_key,
                related_name=related_name,
                remote_cls=remote_model.__name__,
                existing_prefetch=", ".join(
                    "'{}'".format(key) for key in sorted(instance._prefetched_objects_cache.keys())
                ),
            ),
        )

    elif instance._prefetched_objects_cache and related_name in instance._prefetched_objects_cache:
        manager.exclude = exception_raising(
            manager.exclude,
            NoMoreFilteringAllowed(
                "Access to `{attr}.exclude(...)` via `{cls}` instance was prevented because of previous `prefetch_related({x_related_name!r})`\n"
                "Exclude existing objects in memory with:\n"
                "`[{remote_class_var} for {remote_class_var} in {cls_var}.{attr}.all() if {remote_class_var} != ...]`\n"
                "Exclude new objects from the database with:\n"
                "`{remote_cls}.objects.filter({cls_var}={cls_var}.pk).exclude(...)`\n"
                "You can allow access to `{attr}` on this `{cls}` instance by using `{cls_var}.{escape_hatch} = True`",
                attr=attr_name,
                cls=model.__name__,
                cls_var=model._meta.model_name,
                escape_hatch=escape_hatch_key,
                x_related_name=related_name,
                remote_cls=remote_model.__name__,
                remote_class_var=remote_model._meta.model_name,
            ),
        )
        manager.filter = exception_raising(
            manager.filter,
            NoMoreFilteringAllowed(
                "Access to `{attr}.filter(...)` via `{cls}` instance was prevented because of previous `prefetch_related({x_related_name!r})`\n"
                "Filter existing objects in memory with:\n"
                "`[{remote_class_var} for {remote_class_var} in {cls_var}.{attr}.all() if {remote_class_var} ...]`\n"
                "Filter new objects from the database with:\n"
                "`{remote_cls}.objects.filter({cls_var}={cls_var}.pk, ...)`\n"
                "You can allow access to `{attr}` on this `{cls}` instance by using `{cls_var}.{escape_hatch} = True`",
                attr=attr_name,
                cls=model.__name__,
                cls_var=model._meta.model_name,
                escape_hatch=escape_hatch_key,
                x_related_name=related_name,
                remote_cls=remote_model.__name__,
                remote_class_var=remote_model._meta.model_name,
            ),
        )

        manager.annotate = exception_raising(
            manager.annotate,
            NoMoreFilteringAllowed(
                "Access to `{attr}.annotate(...)` via `{cls}` instance was prevented because of previous `prefetch_related({x_related_name!r})`\n"
                "Annotate existing objects in memory with:\n"
                "`for {remote_class_var} in {cls_var}.{attr}.all(): {remote_class_var}.xyz = ...`\n"
                "Annotate new objects from the database with:\n"
                "`{remote_cls}.objects.filter({cls_var}={cls_var}.pk).annotate(...)`\n"
                "You can allow access to `{attr}` on this `{cls}` instance by using `{cls_var}.{escape_hatch} = True`",
                attr=attr_name,
                cls=model.__name__,
                cls_var=model._meta.model_name,
                escape_hatch=escape_hatch_key,
                x_related_name=related_name,
                remote_cls=remote_model.__name__,
                remote_class_var=remote_model._meta.model_name,
            ),
        )

        manager.earliest = exception_raising(
            manager.earliest,
            NoMoreFilteringAllowed(
                "Access to `{attr}.earliest(...)` via `{cls}` instance was prevented because of previous `prefetch_related({x_related_name!r})`\n"
                "Fetch the earliest existing `{remote_cls}` in memory with:\n"
                "`sorted({cls_var}.{attr}.all(), key=itertools.attrgetter(...))[0]`\n"
                "Fetch the earliest `{remote_cls}` from the database with:\n"
                "`{remote_cls}.objects.order_by(...).get({cls_var}={cls_var}.pk)`\n"
                "You can allow access to `{attr}` on this `{cls}` instance by using `{cls_var}.{escape_hatch} = True`",
                attr=attr_name,
                cls=model.__name__,
                cls_var=model._meta.model_name,
                escape_hatch=escape_hatch_key,
                x_related_name=related_name,
                remote_cls=remote_model.__name__,
                remote_class_var=remote_model._meta.model_name,
            ),
        )
        manager.latest = exception_raising(
            manager.latest,
            NoMoreFilteringAllowed(
                "Access to `{attr}.latest(...)` via `{cls}` instance was prevented because of previous `prefetch_related({x_related_name!r})`\n"
                "Fetch the latest existing `{remote_cls}` in memory with:\n"
                "`sorted({cls_var}.{attr}.all(), reverse=True, key=itertools.attrgetter(...))[0]`\n"
                "Fetch the latest `{remote_cls}` from the database with:\n"
                "`{remote_cls}.objects.order_by(...).get({cls_var}={cls_var}.pk)`\n"
                "You can allow access to `{attr}` on this `{cls}` instance by using `{cls_var}.{escape_hatch} = True`",
                attr=attr_name,
                cls=model.__name__,
                cls_var=model._meta.model_name,
                escape_hatch=escape_hatch_key,
                x_related_name=related_name,
                remote_cls=remote_model.__name__,
                remote_class_var=remote_model._meta.model_name,
            ),
        )
        manager.in_bulk = exception_raising(
            manager.in_bulk,
            NoMoreFilteringAllowed(
                "Access to `{attr}.in_bulk(...)` via `{cls}` instance was prevented because of previous `prefetch_related({x_related_name!r})`\n"
                "Convert the existing in memory `{remote_cls}` instances with:\n"
                "`{{{remote_class_var}.pk: {remote_class_var} for {remote_class_var} in {cls_var}.{attr}.all()}}`\n"
                "Fetch the latest `{remote_cls}` from the database with:\n"
                "`{remote_cls}.objects.filter({cls_var}={cls_var}.pk).in_bulk()`\n"
                "You can allow access to `{attr}` on this `{cls}` instance by using `{cls_var}.{escape_hatch} = True`",
                attr=attr_name,
                cls=model.__name__,
                cls_var=model._meta.model_name,
                escape_hatch=escape_hatch_key,
                x_related_name=related_name,
                remote_cls=remote_model.__name__,
                remote_class_var=remote_model._meta.model_name,
            ),
        )
        # This is just an early warning. Attempting to use any of the instances
        # should hopefully raise a MissingLocalField exception anyway:
        # Access to `Model.attr_id` was prevented.\n"
        # Remove the `only(...)` or remove the `defer(...)` where `Model` objects are selected
        manager.defer = exception_raising(
            manager.defer,
            NoMoreFilteringAllowed(
                "Access to `{attr}.defer(...)` via `{cls}` instance was prevented because of previous `prefetch_related({x_related_name!r})`\n"
                "You already have `{remote_cls}` instances in-memory.\n"
                "You can allow access to `{attr}` on this `{cls}` instance by using `{cls_var}.{escape_hatch} = True`",
                attr=attr_name,
                cls=model.__name__,
                cls_var=model._meta.model_name,
                escape_hatch=escape_hatch_key,
                x_related_name=related_name,
                remote_cls=remote_model.__name__,
                remote_class_var=remote_model._meta.model_name,
            ),
        )
        # This is just an early warning. Attempting to use any of the instances
        # should hopefully raise a MissingLocalField exception anyway:
        # Access to `Model.attr_id` was prevented.\n"
        # Remove the `only(...)` or remove the `defer(...)` where `Model` objects are selected
        manager.only = exception_raising(
            manager.only,
            NoMoreFilteringAllowed(
                "Access to `{attr}.only(...)` via `{cls}` instance was prevented because of previous `prefetch_related({x_related_name!r})`\n"
                "You already have `{remote_cls}` instances in-memory.\n"
                "You can allow access to `{attr}` on this `{cls}` instance by using `{cls_var}.{escape_hatch} = True`",
                attr=attr_name,
                cls=model.__name__,
                cls_var=model._meta.model_name,
                escape_hatch=escape_hatch_key,
                x_related_name=related_name,
                remote_cls=remote_model.__name__,
                remote_class_var=remote_model._meta.model_name,
            ),
        )
        manager.reverse = exception_raising(
            manager.reverse,
            NoMoreFilteringAllowed(
                "Access to `{attr}.reverse()` via `{cls}` instance was prevented because of previous `prefetch_related({x_related_name!r})`\n"
                "Convert the existing in memory `{remote_cls}` instances with:\n"
                "`tuple(reversed({cls_var}.{attr}.all()))`\n"
                "Fetch the latest `{remote_cls}` from the database with:\n"
                "`{remote_cls}.objects.filter({cls_var}={cls_var}.pk).order_by(...)`\n"
                "You can allow access to `{attr}` on this `{cls}` instance by using `{cls_var}.{escape_hatch} = True`",
                attr=attr_name,
                cls=model.__name__,
                cls_var=model._meta.model_name,
                escape_hatch=escape_hatch_key,
                x_related_name=related_name,
                remote_cls=remote_model.__name__,
                remote_class_var=remote_model._meta.model_name,
            ),
        )
        manager.distinct = exception_raising(
            manager.distinct,
            NoMoreFilteringAllowed(
                "Access to `{attr}.distinct(...)` via `{cls}` instance was prevented because of previous `prefetch_related({x_related_name!r})`\n"
                "You can allow access to `{attr}` on this `{cls}` instance by using `{cls_var}.{escape_hatch} = True`",
                attr=attr_name,
                cls=model.__name__,
                cls_var=model._meta.model_name,
                escape_hatch=escape_hatch_key,
                x_related_name=related_name,
                remote_cls=remote_model.__name__,
                remote_class_var=remote_model._meta.model_name,
            ),
        )
        manager.values = exception_raising(
            manager.values,
            NoMoreFilteringAllowed(
                "Access to `{attr}.values(...)` via `{cls}` instance was prevented because of previous `prefetch_related({x_related_name!r})`\n"
                "Convert the existing in memory `{remote_cls}` instances with:\n"
                '`[{{"attr1": {remote_class_var}.attr1, "attr2": {remote_class_var}.attr2, ...}} for {remote_class_var} in {cls_var}.{attr}.all()]`\n'
                "Fetch the latest `{remote_cls}` from the database with:\n"
                "`{remote_cls}.objects.filter({cls_var}={cls_var}.pk).values(...)`\n"
                "You can allow access to `{attr}` on this `{cls}` instance by using `{cls_var}.{escape_hatch} = True`",
                attr=attr_name,
                cls=model.__name__,
                cls_var=model._meta.model_name,
                escape_hatch=escape_hatch_key,
                x_related_name=related_name,
                remote_cls=remote_model.__name__,
                remote_class_var=remote_model._meta.model_name,
            ),
        )
        manager.values_list = exception_raising(
            manager.values_list,
            NoMoreFilteringAllowed(
                "Access to `{attr}.values_list(...)` via `{cls}` instance was prevented because of previous `prefetch_related({x_related_name!r})`\n"
                "Convert the existing in memory `{remote_cls}` instances with:\n"
                '`[({remote_class_var}.attr1, "attr2": {remote_class_var}.attr2, ...) for {remote_class_var} in {cls_var}.{attr}.all()]`\n'
                "Fetch the latest `{remote_cls}` from the database with:\n"
                "`{remote_cls}.objects.filter({cls_var}={cls_var}.pk).values_list(...)`\n"
                "You can allow access to `{attr}` on this `{cls}` instance by using `{cls_var}.{escape_hatch} = True`",
                attr=attr_name,
                cls=model.__name__,
                cls_var=model._meta.model_name,
                escape_hatch=escape_hatch_key,
                x_related_name=related_name,
                remote_cls=remote_model.__name__,
                remote_class_var=remote_model._meta.model_name,
            ),
        )
        manager.order_by = exception_raising(
            manager.order_by,
            NoMoreFilteringAllowed(
                "Access to `{attr}.order_by(...)` via `{cls}` instance was prevented because of previous `prefetch_related({x_related_name!r})`\n"
                "Convert the existing in memory `{remote_cls}` instances with:\n"
                "`sorted({cls_var}.{attr}.all(), key=itertools.attrgetter(...))`\n"
                "Fetch the latest `{remote_cls}` from the database with:\n"
                "`{remote_cls}.objects.filter({cls_var}={cls_var}.pk).order_by(...)`\n"
                "You can allow access to `{attr}` on this `{cls}` instance by using `{cls_var}.{escape_hatch} = True`",
                attr=attr_name,
                cls=model.__name__,
                cls_var=model._meta.model_name,
                escape_hatch=escape_hatch_key,
                x_related_name=related_name,
                remote_cls=remote_model.__name__,
                remote_class_var=remote_model._meta.model_name,
            ),
        )
        manager.extra = exception_raising(
            manager.extra,
            NoMoreFilteringAllowed(
                "Access to `{attr}.extra(...)` via `{cls}` instance was prevented because of previous `prefetch_related({x_related_name!r})`\n"
                "Update your `prefetch_related` to use `prefetch_related(Prefetch({x_related_name!r}, {remote_cls}.objects.extra(...)))`\n"
                "You can allow access to `{attr}` on this `{cls}` instance by using `{cls_var}.{escape_hatch} = True`",
                attr=attr_name,
                cls=model.__name__,
                cls_var=model._meta.model_name,
                escape_hatch=escape_hatch_key,
                x_related_name=related_name,
                remote_cls=remote_model.__name__,
                remote_class_var=remote_model._meta.model_name,
            ),
        )
        manager.select_related = exception_raising(
            manager.select_related,
            NoMoreFilteringAllowed(
                "Access to `{attr}.select_related(...)` via `{cls}` instance was prevented because of previous `prefetch_related({x_related_name!r})`\n"
                "Update your `prefetch_related` to use `prefetch_related(Prefetch({x_related_name!r}, {remote_cls}.objects.select_related(...)))`\n"
                "You can allow access to `{attr}` on this `{cls}` instance by using `{cls_var}.{escape_hatch} = True`",
                attr=attr_name,
                cls=model.__name__,
                cls_var=model._meta.model_name,
                escape_hatch=escape_hatch_key,
                x_related_name=related_name,
                remote_cls=remote_model.__name__,
                remote_class_var=remote_model._meta.model_name,
            ),
        )
        manager.alias = exception_raising(
            manager.alias,
            NoMoreFilteringAllowed(
                "Access to `{attr}.alias(...)` via `{cls}` instance was prevented because of previous `prefetch_related({x_related_name!r})`\n"
                "You can allow access to `{attr}` on this `{cls}` instance by using `{cls_var}.{escape_hatch} = True`",
                attr=attr_name,
                cls=model.__name__,
                cls_var=model._meta.model_name,
                escape_hatch=escape_hatch_key,
                x_related_name=related_name,
                remote_cls=remote_model.__name__,
                remote_class_var=remote_model._meta.model_name,
            ),
        )
        manager.prefetch_related = exception_raising(
            manager.alias,
            NoMoreFilteringAllowed(
                "Access to `{attr}.prefetch_related(...)` via `{cls}` instance was prevented because of previous `prefetch_related({x_related_name!r})`\n"
                "Update your `prefetch_related` to use `prefetch_related({x_related_name!r}, '{x_related_name!s}__attr')`\n"
                "You can allow access to `{attr}` on this `{cls}` instance by using `{cls_var}.{escape_hatch} = True`",
                attr=attr_name,
                cls=model.__name__,
                cls_var=model._meta.model_name,
                escape_hatch=escape_hatch_key,
                x_related_name=related_name,
                remote_cls=remote_model.__name__,
                remote_class_var=remote_model._meta.model_name,
            ),
        )
    return manager


# This is used so that when .only() and .defer() are used, I can prevent the
# bit which would cause a query for unselected fields.
old_deferredattribute_check_parent_chain = DeferredAttribute._check_parent_chain


def new_deferredattribute_check_parent_chain(
    self: DeferredAttribute, instance: Model, name: Optional[Text] = None
) -> Any:
    """

    When using .only("x") or .defer("y"), access to "y" should be prohibited.
    """
    __traceback_hide__ = True  # django
    __tracebackhide__ = True  # pytest (+ipython?)
    __debuggerskip__ = True  # (ipython+ipdb?)
    # In Django 3.0, DeferredAttribute was refactored somewhat so that
    # _check_parent_chain no longer requires passing a name instance.
    if DJANGO_VERSION[0:2] < (3, 0):
        # noinspection PyArgumentList
        val = old_deferredattribute_check_parent_chain(self, instance, name=name)
    else:
        val = old_deferredattribute_check_parent_chain(self, instance)
        assert name is None, "Unexpected name value"
    escape_hatch_key = f"_shoutyorm_allow_{self.field.attname}"
    logger.debug("Checking for %s on %r instance", escape_hatch_key, instance)
    if not hasattr(instance, escape_hatch_key):
        setattr(instance, escape_hatch_key, False)

    if val is None and getattr(instance, escape_hatch_key) is False:
        deferred_fields = instance.get_deferred_fields()
        selected_fields = {
            f.attname for f in instance._meta.concrete_fields if f.attname in instance.__dict__
        }
        defer_msg = "remove `{attr}` from `defer({deferred!s})`"
        only_msg = "Add `{attr}` to `only({selected!s})`"
        if deferred_fields == {self.field.attname}:
            defer_msg = "remove the `defer({deferred!s})`"
            only_msg = "Remove the `only(...)`"
        escape_hatch_msg = "You can allow access to `{attr}` on this `{cls}` instance by using `{cls_lower}._shouty_allow_{attr} = True`"
        exception = MissingLocalField(
            (
                "Access to `{cls}.{attr}` was prevented.\n"
                + only_msg
                + " or "
                + defer_msg
                + " where `{cls}` objects are selected`\n"
                + escape_hatch_msg
            ).format(
                attr=self.field.attname,
                cls=instance.__class__.__name__,
                cls_lower=instance._meta.model_name,
                selected=", ".join("'{}'".format(key) for key in sorted(selected_fields)),
                deferred=", ".join("'{}'".format(key) for key in sorted(deferred_fields)),
            )
        )
        # Hide KeyError from get_cached_value
        exception.__cause__ = None
        raise exception
    return val


# This is when you do "mymodel.myothermodel_set.all()" where the foreignkey
# exists on "MyOtherModel" and POINTS to "MyModel"
#
# In an ideal world I'd patch get_queryset() directly, but that's used by
# the get_prefetch_queryset() implementations and I don't know the ramifications
# of doing so, so instead we're going to proxy the "public" API.
old_reverse_foreignkey_descriptor_get = ReverseManyToOneDescriptor.__get__


def new_reverse_foreignkey_descriptor_get(
    self: ReverseManyToOneDescriptor, instance: Model, cls: Optional[Type[Model]] = None
) -> Any:
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
    __traceback_hide__ = True  # django
    __tracebackhide__ = True  # pytest (+ipython?)
    __debuggerskip__ = True  # (ipython+ipdb?)

    if instance is None:
        return self

    manager = old_reverse_foreignkey_descriptor_get(self, instance, cls)

    rebind_related_manager_via_descriptor(
        manager=manager,
        instance=instance,
        model=self.field.remote_field.model,
        remote_model=self.field.model,
        attr_name=self.field.remote_field.get_accessor_name(),
        related_name=self.field.remote_field.get_cache_name(),
    )
    return manager


# This is when you do "mymodel.myfield" where "myfield" is a OneToOneField
# on MyOtherModel which points back to MyModel
#
# In an ideal world I'd patch get_queryset() directly, but that's used by
# the get_prefetch_queryset() implementations and I don't know the ramifications
# of doing so, so instead we're going to proxy the "public" API.
old_reverse_onetoone_descriptor_get = ReverseOneToOneDescriptor.__get__


def new_reverse_onetoone_descriptor_get(
    self: ReverseOneToOneDescriptor, instance: Model, cls: Optional[Type[Model]] = None
) -> Any:
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
    __traceback_hide__ = True  # django
    __tracebackhide__ = True  # pytest (+ipython?)
    __debuggerskip__ = True  # (ipython+ipdb?)

    if instance is None:
        return self
    try:
        self.related.get_cached_value(instance)
    except KeyError:
        # Start to track how much has been lazily acquired. By default they should
        # all be False.
        escape_hatch_key = f"_shoutyorm_allow_{self.related.get_accessor_name()}"
        logger.debug("Checking for %s on %r instance", escape_hatch_key, instance)
        if not hasattr(instance, escape_hatch_key):
            setattr(instance, escape_hatch_key, False)

        # This ties in with `new_model_save_base`.
        # If we just created an instance via MyModel.objects.create() or MyModel(...).save()
        # we (by necessity) have to allow fetches for related data, at least until the next
        # Model.save()
        # Note that this is a special case for when <field>_id is passed instead of <field> itself.
        # In the latter case, the value will already be OK via is_cached() and won't hit this.
        #
        # Realistically, preventing the query that would follow doesn't achieve
        # anything in the <field>_id scenario anyway, because you'd just be shifting
        # to getting the object ahead of time. So it'd be +-0 queries changed in total.
        #
        # This additionally allows a query if you have the remote side of the onetoone,
        # create the 'other' side afterwards, and then try and access the 'other' side.
        just_created = getattr(instance, "_shoutyorm_just_added", False)
        if just_created:
            logger.debug(
                "Setting %s on %r instance because it was just created", escape_hatch_key, instance
            )
            setattr(instance, escape_hatch_key, True)

        # If we encounter an escape hatch of `_shouty_<field>` = 2 it means
        # we want to allow 2 lazy attribute requests to the field.
        if getattr(instance, escape_hatch_key) is False:
            exception = MissingReverseRelationField(
                "Access to `{cls}.{attr}` was prevented.\n"
                "To fetch the `{remote_cls}` object, add `prefetch_related({x_related_name!r})` or `select_related({x_related_name!r})` to the query where `{cls}` objects are selected.\n"
                "You can allow access to `{attr}` on this `{cls}` instance by using `{cls_lower}.{escape_hatch} = True".format(
                    attr=self.related.get_accessor_name(),
                    cls=instance.__class__.__name__,
                    cls_lower=instance._meta.model_name,
                    escape_hatch=escape_hatch_key,
                    x_related_name=self.related.get_accessor_name() or "...",
                    remote_cls=self.related.remote_field.model.__name__,
                )
            )
            # supress KeyError from chain
            exception.__cause__ = None
            raise exception
        # We didn't raise, so lets fetch and disable it subsequently.
        if just_created:
            logger.debug(
                "Resetting %s on %r instance because it was just created",
                escape_hatch_key,
                instance,
            )
            setattr(instance, escape_hatch_key, False)
    return old_reverse_onetoone_descriptor_get(self, instance, cls)


# This is used when you have mymodel.m2m.all() where m2m is a ManyToManyField
# because of the way this descriptor's related manager is set up, in combination
# with the way prefetching works (get_prefetch_queryset, get the manager, get_queryset, etc)
# This is the best entry point I could find.
old_manytomany_descriptor_get = ManyToManyDescriptor.__get__


def new_manytomany_descriptor_get(
    self: ManyToManyDescriptor, instance: Model, cls: Optional[Type[Model]] = None
) -> Any:
    """
    This is invoked when you're asking for mymodel.m2m.all() or more specifically
    asking for mymodel.m2m... accessing .all() in SOME scenarios will now
    raise an exception because we've proxied the manager due to prefetch_related
    usage (or lack thereof)
    """
    __traceback_hide__ = True  # django
    __tracebackhide__ = True  # pytest (+ipython?)
    __debuggerskip__ = True  # (ipython+ipdb?)
    if instance is None:
        return self

    manager = old_manytomany_descriptor_get(self, instance, cls)

    if self.reverse is True:
        related_name = self.field.remote_field.get_accessor_name()
        related_model = self.field.remote_field.model
    else:
        related_name = self.field.get_cache_name()
        related_model = self.field.model

    rebind_related_manager_via_descriptor(
        manager=manager,
        instance=instance,
        model=related_model,
        remote_model=manager.model,
        attr_name=related_name,
        related_name=manager.prefetch_cache_name,
    )

    return manager


# This is when you do "mymodel.myfield" where "myfield" is a ForeignKey
# on the "MyModel" class
#
# As far as I can tell it's safe to patch get_object() directly here instead
# of __get__ as I have for the other ones, because get_object()
# solely does the database querying, and nothing else.
old_foreignkey_descriptor_get_object = ForwardManyToOneDescriptor.get_object


def new_foreignkey_descriptor_get_object(
    self: ForwardManyToOneDescriptor, instance: Model
) -> Model:
    """
    This covers both OneToOneField and ForeignKey forward references.

    This will be invoked when trying to access `mymodel_instance.myfk`
    or `mymodel_instance.myonetoone`  without having either used
    prefetch_related() or select_related().

    Note that for the OneToOne case, when `parent_link` is available (which is
    for concrete inheritance IIRC?) there won't be a query anyway, so this method
    won't get called.

    In the example::

        class Restaurant(Model):
            place = OneToOneField(Place, related_name='restaurant')

    ``Restaurant.place`` is a ``ForwardOneToOneDescriptor`` instance.

    In the example::

        class Child(Model):
            parent = ForeignKey(Parent, related_name='children')

    ``Child.parent`` is a ``ForwardManyToOneDescriptor`` instance.
    """
    __traceback_hide__ = True  # django
    __tracebackhide__ = True  # pytest (+ipython?)
    __debuggerskip__ = True  # (ipython+ipdb?)

    # Start tro track how much has been lazily acquired. By default they should
    # all be zero.
    escape_hatch_key = f"_shoutyorm_allow_{self.field.get_cache_name()}"
    logger.debug("Checking for %s on %r instance", escape_hatch_key, instance)
    if not hasattr(instance, escape_hatch_key):
        setattr(instance, escape_hatch_key, False)

    # This ties in with `new_model_save_base`.
    # If we just created an instance via MyModel.objects.create() or MyModel(...).save()
    # we (by necessity) have to allow fetches for related data, at least until the next
    # Model.save()
    # Note that this is a special case for when <field>_id is passed instead of <field> itself.
    # In the latter case, the value will already be OK via is_cached() and won't hit this.
    #
    # Realistically, preventing the query that would follow doesn't achieve
    # anything in the <field>_id scenario anyway, because you'd just be shifting
    # to getting the object ahead of time. So it'd be +-0 queries changed in total.
    just_created = getattr(instance, "_shoutyorm_just_added", False)
    if just_created:
        logger.debug(
            "Setting %s on %r instance because it was just created", escape_hatch_key, instance
        )
        setattr(instance, escape_hatch_key, True)

    if getattr(instance, escape_hatch_key) is False:
        exception = MissingRelationField(
            "Access to `{cls}.{attr}` was prevented.\n"
            "If you only need access to the column identifier, use `{cls}.{field_column}` instead.\n"
            "To fetch the `{remote_cls}` object, add `prefetch_related({x_related_name!r})` or `select_related({x_related_name!r})` to the query where `{cls}` objects are selected.\n"
            "You can allow access to `{attr}` on this `{cls}` instance by using `{cls_lower}.{escape_hatch} = True`".format(
                attr=self.field.get_cache_name(),
                cls=instance.__class__.__name__,
                cls_lower=instance._meta.model_name,
                escape_hatch=escape_hatch_key,
                field_column=self.field.get_attname(),
                # x_related_name=other_side.get_accessor_name() or "...",
                x_related_name=self.field.get_cache_name() or "...",
                remote_cls=self.field.remote_field.model.__name__,
            )
        )
        # supress KeyError from ForwardManyToOneDescriptor.__get__ via FieldCacheMixin.get_cached_value
        exception.__cause__ = None
        raise exception
    # OK we're allowing +1 lazy access, to account for <field>_id
    # Reduce our expected allowance again.
    if just_created:
        logger.debug(
            "Resetting %s on %r instance because it was just created", escape_hatch_key, instance
        )
        setattr(instance, escape_hatch_key, False)
    related_instance = old_foreignkey_descriptor_get_object(self, instance)
    return related_instance


# This is used to establish whether we've just created a model via
# MyModel.objects.create() or MyModel(...).save()
old_model_save_base = Model.save_base


def new_model_save_base(
    self: Model,
    raw: bool = False,
    force_insert: bool = False,
    force_update: bool = False,
    using: Optional[str] = None,
    update_fields: Optional[Iterable[str]] = None,
) -> None:
    """
    This is used to establish whether we've just created a model via
    MyModel.objects.create() or MyModel(...).save()
    This is necessary because we may have passed in a group_id (or whatever)
    instead of a group instance, but would then like to use the related object
    subsequently without getting an exception (we literally cannot fetch it as
    a select_related/prefetch_related call, because the INSERT won't include
    the related data during RETURNING).

    Realistically, preventing the query that would follow doesn't achieve
    anything in the <field>_id scenario anyway, because you'd just be shifting
    to getting the object ahead of time. So it'd be +-0 queries changed in total.
    """
    adding = self._state.adding is True
    result = old_model_save_base(
        self,
        raw=raw,
        force_insert=force_insert,
        force_update=force_update,
        using=using,
        update_fields=update_fields,
    )
    added = self._state.adding is False
    # On the second save (after the first for creation), this should fall back
    # to False, at which point further related attribute access may be prevented again.
    self._shoutyorm_just_added = adding is True and added is True
    return result


def patch():
    """
    Apply monkeypatches to various Django methods.

    Patches are applied to cover:
    a) defer() and only() usage
    b) OneToOneFields (and their reverse relations)
    c) ForeignKeys (and their reverse relations)
    d) ManyToManyFields (from both ends)
    e) Model saving (so that after *creation* things don't become problematic)
    """
    patched_deferredattr = getattr(DeferredAttribute, "_shouty", False)
    if patched_deferredattr is False:
        DeferredAttribute._check_parent_chain = new_deferredattribute_check_parent_chain
        DeferredAttribute._shouty = True

    # This patches `mymodel.myrelation` where `myrelation` is either
    # myrelation = ForeignKey(...)
    # myrelation = OneToOneField(...)
    patched_manytoone = getattr(ForwardManyToOneDescriptor, "_shouty", False)
    if patched_manytoone is False:
        ForwardManyToOneDescriptor.get_object = new_foreignkey_descriptor_get_object
        ForwardManyToOneDescriptor._shouty = True

    patched_manytomany = getattr(ManyToManyDescriptor, "_shouty", False)
    if patched_manytomany is False:
        ManyToManyDescriptor.__get__ = new_manytomany_descriptor_get
        ManyToManyDescriptor._shouty = True

    patched_save_base = getattr(Model, "_shouty", False)
    if patched_save_base is False:
        Model.save_base = new_model_save_base
        Model._shouty = True

    patched_reverse_onetone = getattr(ReverseOneToOneDescriptor, "_shouty", False)
    if patched_reverse_onetone is False:
        ReverseOneToOneDescriptor.__get__ = new_reverse_onetoone_descriptor_get
        ReverseOneToOneDescriptor._shouty = True

    patched_reverse_manytoone = getattr(ReverseManyToOneDescriptor, "_shouty", False)

    if patched_reverse_manytoone is False:
        ReverseManyToOneDescriptor.__get__ = new_reverse_foreignkey_descriptor_get
        ReverseManyToOneDescriptor._shouty = True

    return True
