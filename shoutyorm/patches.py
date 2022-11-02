from __future__ import annotations

try:
    from typing import Optional, Text, Any, NoReturn, Iterable, Type
except ImportError:  # pragma: no cover
    pass

from django import VERSION as DJANGO_VERSION
from django.db.models import Model, Manager, QuerySet
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
    MissingOneToOneField,
    MissingForeignKeyField,
    MissingManyToManyField,
    RedundantSelection,
    NoMoreFilteringAllowed,
)

# Hide the patch stacks from unittest output?
__unittest = True


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
    if val is None:
        deferred_fields = instance.get_deferred_fields()
        selected_fields = {
            f.attname for f in instance._meta.concrete_fields if f.attname in instance.__dict__
        }
        defer_msg = "remove `{attr}` from `defer({deferred!s})`"
        only_msg = "Add `{attr}` to `only({selected!s})`"
        if deferred_fields == {self.field.attname}:
            defer_msg = "remove the `defer({deferred!s})`"
            only_msg = "Remove the `only(...)`"
        exception = MissingLocalField(
            (
                "Access to `{cls}.{attr}` was prevented.\n"
                + only_msg
                + " or "
                + defer_msg
                + " where `{cls}` objects are selected`"
            ).format(
                attr=self.field.attname,
                cls=instance.__class__.__name__,
                selected=", ".join("'{}'".format(key) for key in sorted(selected_fields)),
                deferred=", ".join("'{}'".format(key) for key in sorted(deferred_fields)),
            )
        )
        # Hide KeyError from get_cached_value
        exception.__cause__ = None
        raise exception
    return val


# Because you can "escape" from the manager monkeypatch (see new_manytomany_descriptor_get and
# new_reverse_foreignkey_descriptor_get) by prefetching and then creating a new queryset from the
# manager, we need to block that queryset's filtering behaviour too.
#
# e.g. given:
# items = MyModel.objects.prefetch_related('x').all()
# you can escape it by doing:
# my_x = items[0].x_set.all().filter(...)
# the .all is allowed because of the prefetch, but it generates a QuerySet which doesn't know
# it shouldn't be allowed to filter etc.
old_queryset_filter_or_exclude = QuerySet._filter_or_exclude


def new_queryset_filter_or_exclude(self: QuerySet, negate: bool, args: Any, kwargs: Any):
    print(self._known_related_objects)
    instance = self._hints.get("instance", None)
    if (
        instance is not None
        and hasattr(instance, "_prefetched_objects_cache")
        and instance._prefetched_objects_cache
    ):
        import pdb

        pdb.set_trace()
        # This is in the prefetched data...
        if 1:
            model_name = instance._meta.model_name
            model_cls_name = instance._meta.object_name
            raise NoMoreFilteringAllowed(
                "Access to `filter()` and `exclude()` is disabled because of an existing `prefetch_related()`\n"
                f"Filter existing objects in memory with `[{model_name} for {model_name} in ... if {model_name} ...]\n"
                f"Filter new objects from the database with `{model_cls_name}.objects.filter(pk={instance.pk!r}, ...) for clarity."
            )
    return old_queryset_filter_or_exclude(self, negate=negate, args=args, kwargs=kwargs)


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

    # There's no prefetch_related() call at all.
    if not hasattr(instance, "_prefetched_objects_cache"):
        all_exception = MissingReverseRelationField(
            "Access to `{cls}.{attr}.all()` was prevented.\n"
            "To fetch the `{remote_cls}` objects, add `prefetch_related({x_related_name!r})` to the query where `{cls}` objects are selected.".format(
                attr=self.field.remote_field.get_accessor_name(),
                cls=self.field.remote_field.model.__name__,
                x_related_name=self.field.remote_field.get_cache_name() or "...",
                remote_cls=self.field.model.__name__,
            )
        )
        all_exception.__cause__ = None

        def no_prefetched_all(self, *args, **kwargs):
            # type: (Manager, *Any, **Any) -> NoReturn
            __traceback_hide__ = True  # django
            __tracebackhide__ = True  # pytest (+ipython?)
            __debuggerskip__ = True  # (ipython+ipdb?)
            raise all_exception

        manager.all = no_prefetched_all.__get__(manager)
    # There is a prefetch_related() call, but it doesn't include this reverse
    # model.
    elif (
        instance._prefetched_objects_cache
        and self.field.remote_field.get_cache_name() not in instance._prefetched_objects_cache
    ):
        all_exception = MissingReverseRelationField(
            "Access to `{cls}.{attr}.all()` was prevented.\n"
            "To fetch the `{remote_cls}` objects, add {x_related_name!r} to the existing `prefetch_related({existing_prefetch!s})` part of the query where `{cls}` objects are selected.".format(
                attr=self.field.remote_field.get_accessor_name(),
                cls=self.field.remote_field.model.__name__,
                x_related_name=self.field.remote_field.get_cache_name() or "...",
                remote_cls=self.field.model.__name__,
                existing_prefetch=", ".join(
                    "'{}'".format(key) for key in sorted(instance._prefetched_objects_cache.keys())
                ),
            )
        )
        all_exception.__cause__ = None

        def partial_prefetched_all(self, *args, **kwargs):
            # type: (Manager, *Any, **Any) -> NoReturn
            __traceback_hide__ = True  # django
            __tracebackhide__ = True  # pytest (+ipython?)
            __debuggerskip__ = True  # (ipython+ipdb?)
            raise all_exception

        manager.all = partial_prefetched_all.__get__(manager)
    # elif (
    #     instance._prefetched_objects_cache
    #     and self.field.remote_field.get_cache_name() in instance._prefetched_objects_cache
    # ):
    #
    #     filter_exception = NoMoreFilteringAllowed(
    #         "Access to `{cls}.{attr}.filter(...)` was prevented because of previous `prefetch_related({x_related_name!r})`\n"
    #         "Filter existing objects in memory with `[{remote_class_var} for {remote_class_var} in {cls}.{attr}.all() if {remote_class_var} ...]\n"
    #         "Filter new objects from the database with `{remote_cls}.objects.filter(pk={cls_var}.pk, ...)` for clarity.".format(
    #             attr=self.field.remote_field.get_accessor_name(),
    #             cls=self.field.remote_field.model.__name__,
    #             cls_var=self.field.remote_field.model.__name__.lower(),
    #             x_related_name=self.field.remote_field.get_cache_name() or "...",
    #             remote_cls=self.field.model.__name__,
    #             remote_class_var=self.field.model.__name__.lower(),
    #         )
    #     )
    #
    #     def already_prefetched_filter(self, *args, **kwargs):
    #         # type: (Manager, *Any, **Any) -> NoReturn
    #         __traceback_hide__ = True  # django
    #         __tracebackhide__ = True  # pytest (+ipython?)
    #         __debuggerskip__ = True  # (ipython+ipdb?)
    #         raise filter_exception
    #
    #     exclude_exception = NoMoreFilteringAllowed(
    #         "Access to `{cls}.{attr}.exclude(...)` was prevented because of previous `prefetch_related({x_related_name!r})`\n"
    #         "Exclude existing objects in memory with `[{remote_class_var} for {remote_class_var} in {cls}.{attr}.all() if {remote_class_var} ...]\n"
    #         "Exclude new objects from the database with `{remote_cls}.objects.filter(pk={cls_var}.pk).exclude(...)` for clarity.".format(
    #             attr=self.field.remote_field.get_accessor_name(),
    #             cls=self.field.remote_field.model.__name__,
    #             cls_var=self.field.remote_field.model.__name__.lower(),
    #             x_related_name=self.field.remote_field.get_cache_name() or "...",
    #             remote_cls=self.field.model.__name__,
    #             remote_class_var=self.field.model.__name__.lower(),
    #         )
    #     )
    #
    #     def already_prefetched_exclude(self, *args, **kwargs):
    #         # type: (Manager, *Any, **Any) -> NoReturn
    #         __traceback_hide__ = True  # django
    #         __tracebackhide__ = True  # pytest (+ipython?)
    #         __debuggerskip__ = True  # (ipython+ipdb?)
    #         raise exclude_exception
    #
    #     annotate_exception = NoMoreFilteringAllowed(
    #         "Access to `{cls}.{attr}.annotate(...)` was prevented because of previous `prefetch_related({x_related_name!r})`\n"
    #         "Annotate existing objects in memory with `for {remote_class_var} in {cls}.{attr}.all(): {remote_class_var}.xyz = ...\n"
    #         "Annotate new objects from the database with `{remote_cls}.objects.filter(pk={cls_var}.pk).annotate(...)` for clarity.".format(
    #             attr=self.field.remote_field.get_accessor_name(),
    #             cls=self.field.remote_field.model.__name__,
    #             cls_var=self.field.remote_field.model.__name__.lower(),
    #             x_related_name=self.field.remote_field.get_cache_name() or "...",
    #             remote_cls=self.field.model.__name__,
    #             remote_class_var=self.field.model.__name__.lower(),
    #         )
    #     )
    #
    #     def already_prefetched_annotate(self, *args, **kwargs):
    #         # type: (Manager, *Any, **Any) -> NoReturn
    #         __traceback_hide__ = True  # django
    #         __tracebackhide__ = True  # pytest (+ipython?)
    #         __debuggerskip__ = True  # (ipython+ipdb?)
    #         raise annotate_exception
    #
    #     manager.filter = already_prefetched_filter.__get__(manager)
    #     manager.exclude = already_prefetched_exclude.__get__(manager)
    #     manager.annotate = already_prefetched_annotate.__get__(manager)
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
        escape_hatch_key = "allow_lazy:{}".format(self.related.get_accessor_name())
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
        just_created = getattr(instance._state, "_shouty_just_added", False)
        instance._state.fields_cache[escape_hatch_key] = just_created

        # If we encounter an escape hatch of `_shouty_<field>` = 2 it means
        # we want to allow 2 lazy attribute requests to the field.
        if instance._state.fields_cache[escape_hatch_key] is False:
            exception = MissingOneToOneField(
                "Access to `{cls}.{attr}` was prevented.\n"
                "To fetch the `{remote_cls}` object, add `prefetch_related({x_related_name!r})` or `select_related({x_related_name!r})` to the query where `{cls}` objects are selected.".format(
                    attr=self.related.get_accessor_name(),
                    cls=instance.__class__.__name__,
                    x_related_name=self.related.get_accessor_name() or "...",
                    remote_cls=self.related.remote_field.model.__name__,
                )
            )
            # supress KeyError from chain
            exception.__cause__ = None
            raise exception
        # We didn't raise, so lets fetch and disable it subsequently.
        instance._state.fields_cache[escape_hatch_key] = False
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

    # If there's no prefetch_related() usage at all, m2ms will be N+1
    if not hasattr(instance, "_prefetched_objects_cache"):
        exception = MissingManyToManyField(
            "Access to `{cls}.{attr}.all()` was prevented.\n"
            "To fetch the `{remote_cls}` objects, add `prefetch_related({x_related_name!r})` to the query where `{cls}` objects are selected.".format(
                attr=related_name,
                cls=related_model.__name__,
                x_related_name=related_name or "...",
                remote_cls=manager.model.__name__,
            )
        )
        exception.__cause__ = None

        def no_prefetched_all(self, *args, **kwargs):
            # type: (Manager, *Any, **Any) -> NoReturn
            __traceback_hide__ = True  # django
            __tracebackhide__ = True  # pytest (+ipython?)
            __debuggerskip__ = True  # (ipython+ipdb?)
            raise exception

        manager.all = no_prefetched_all.__get__(manager)
    # There is a prefetch_related() call, but it doesn't look like it includes
    # this model, so it should be added in...
    elif (
        instance._prefetched_objects_cache
        and related_name not in instance._prefetched_objects_cache
    ):
        exception = MissingManyToManyField(
            "Access to `{cls}.{attr}.all()` was prevented.\n"
            "To fetch the `{remote_cls}` objects, add {x_related_name!r} to the existing `prefetch_related({existing_prefetch!s})` part of the query where `{cls}` objects are selected.".format(
                attr=related_name,
                cls=related_model.__name__,
                x_related_name=related_name or "...",
                remote_cls=manager.model.__name__,
                existing_prefetch=", ".join(
                    "'{}'".format(key) for key in sorted(instance._prefetched_objects_cache.keys())
                ),
            )
        )
        exception.__cause__ = None

        def partial_prefetched_all(self, *args, **kwargs):
            # type: (Manager, *Any, **Any) -> NoReturn
            __traceback_hide__ = True  # django
            __tracebackhide__ = True  # pytest (+ipython?)
            __debuggerskip__ = True  # (ipython+ipdb?)
            raise exception

        manager.all = partial_prefetched_all.__get__(manager)
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
    exception_class = MissingOneToOneField if self.field.one_to_one else MissingForeignKeyField

    # Start tro track how much has been lazily acquired. By default they should
    # all be zero.
    escape_hatch_key = "allow_lazy:{}".format(self.field.get_cache_name())
    if escape_hatch_key not in instance._state.fields_cache:
        instance._state.fields_cache[escape_hatch_key] = False

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
    just_created = getattr(instance._state, "_shouty_just_added", False)
    instance._state.fields_cache[escape_hatch_key] = just_created

    if instance._state.fields_cache[escape_hatch_key] is False:
        exception = exception_class(
            "Access to `{cls}.{attr}` was prevented.\n"
            "If you only need access to the column identifier, use `{cls}.{field_column}` instead.\n"
            "To fetch the `{remote_cls}` object, add `prefetch_related({x_related_name!r})` or `select_related({x_related_name!r})` to the query where `{cls}` objects are selected.".format(
                attr=self.field.get_cache_name(),
                cls=instance.__class__.__name__,
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
    instance._state.fields_cache[escape_hatch_key] = False
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
    self._state._shouty_just_added = adding is True and added is True
    return result


def patch(invalid_locals: bool, invalid_relations: bool, invalid_reverse_relations: bool):
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
            DeferredAttribute._check_parent_chain = new_deferredattribute_check_parent_chain
            DeferredAttribute._shouty = True

    if invalid_relations is True:

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

    if invalid_reverse_relations is True:
        patched_reverse_onetone = getattr(ReverseOneToOneDescriptor, "_shouty", False)
        if patched_reverse_onetone is False:
            ReverseOneToOneDescriptor.__get__ = new_reverse_onetoone_descriptor_get
            ReverseOneToOneDescriptor._shouty = True

        patched_reverse_manytoone = getattr(ReverseManyToOneDescriptor, "_shouty", False)

        if patched_reverse_manytoone is False:
            ReverseManyToOneDescriptor.__get__ = new_reverse_foreignkey_descriptor_get
            ReverseManyToOneDescriptor._shouty = True

    QuerySet._filter_or_exclude = new_queryset_filter_or_exclude
    QuerySet._shouty = True
    return True
