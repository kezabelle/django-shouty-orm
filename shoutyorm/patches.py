try:
    from typing import Optional, Text, Any
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


_TMPL_MISSING_M2M_PREFETCH = "Access to '{attr}' ManyToMany manager attribute on {cls} was prevented because it was not selected.\nProbably missing from prefetch_related()"


# This is used so that when .only() and .defer() are used, I can prevent the
# bit which would cause a query for unselected fields.
# noinspection PyProtectedMember
from shoutyorm.errors import (
    MissingReverseRelationField,
    MissingLocalField,
    MissingRelationField,
    MissingOneToOneField,
    MissingForeignKeyField,
)
from wrapt import CallableObjectProxy

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


def new_reverse_relatedmanager_all(self, *args, **kwargs):
    # type: (Manager, *Any, **Any) -> Any
    __traceback_hide__ = True  # django
    __tracebackhide__ = True  # pytest (+ipython?)
    __debuggerskip__ = True  # (ipython+ipdb?)
    if not hasattr(self.instance, "_prefetched_objects_cache"):
        exception = MissingReverseRelationField(
            "Access to `{cls}.{attr}.all()` was prevented.\n"
            "To fetch the `{remote_cls}` objects, add `prefetch_related({x_related_name!r})` to the query where `{cls}` objects are selected.".format(
                attr=self.field.remote_field.get_accessor_name(),
                cls=self.field.remote_field.model.__name__,
                x_related_name=self.field.remote_field.get_cache_name() or "...",
                remote_cls=self.model.__name__,
            )
        )
        exception.__cause__ = None
        raise exception
    elif (
        self.instance._prefetched_objects_cache
        and self.field.remote_field.get_cache_name() not in self.instance._prefetched_objects_cache
    ):
        exception = MissingReverseRelationField(
            "Access to `{cls}.{attr}.all()` was prevented.\n"
            "To fetch the `{remote_cls}` objects, add {x_related_name!r} to the existing `prefetch_related({existing_prefetch!s})` part of the query where `{cls}` objects are selected.".format(
                attr=self.field.remote_field.get_accessor_name(),
                cls=self.field.remote_field.model.__name__,
                x_related_name=self.field.remote_field.get_cache_name() or "...",
                remote_cls=self.model.__name__,
                existing_prefetch=", ".join(
                    "'{}'".format(key)
                    for key in sorted(self.instance._prefetched_objects_cache.keys())
                ),
            )
        )
        exception.__cause__ = None
        raise exception
    return self._shouty_all(*args, **kwargs)


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
    __traceback_hide__ = True  # django
    __tracebackhide__ = True  # pytest (+ipython?)
    __debuggerskip__ = True  # (ipython+ipdb?)

    if instance is None:
        return self

    manager = old_reverse_foreignkey_descriptor_get(self, instance, cls)
    manager._shouty_all = manager.all
    manager.all = new_reverse_relatedmanager_all.__get__(manager)
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
    __traceback_hide__ = True  # django
    __tracebackhide__ = True  # pytest (+ipython?)
    __debuggerskip__ = True  # (ipython+ipdb?)

    if instance is None:
        return self
    try:
        self.related.get_cached_value(instance)
    except KeyError:
        exception = MissingOneToOneField(
            "Access to `{cls}.{attr}` was prevented.\n"
            "To fetch the `{remote_cls}` object, add `prefetch_related({x_related_name!r})` or `select_related({x_related_name!r})` to the query where `{cls}` objects are selected.".format(
                attr=self.related.get_accessor_name(),
                cls=instance.__class__.__name__,
                # x_related_name=other_side.get_accessor_name() or "...",
                x_related_name=self.related.get_accessor_name() or "...",
                remote_cls=self.related.remote_field.model.__name__,
            )
        )
        # supress KeyError from chain
        exception.__cause__ = None
        raise exception
    return old_reverse_onetoone_descriptor_get(self, instance, cls)


def new_reverse_relatedmanager_all(self, *args, **kwargs):
    # type: (Manager, *Any, **Any) -> Any
    __traceback_hide__ = True  # django
    __tracebackhide__ = True  # pytest (+ipython?)
    __debuggerskip__ = True  # (ipython+ipdb?)
    if not hasattr(self.instance, "_prefetched_objects_cache"):
        exception = MissingReverseRelationField(
            "Access to `{cls}.{attr}.all()` was prevented.\n"
            "To fetch the `{remote_cls}` objects, add `prefetch_related({x_related_name!r})` to the query where `{cls}` objects are selected.".format(
                attr=self.field.remote_field.get_accessor_name(),
                cls=self.field.remote_field.model.__name__,
                x_related_name=self.field.remote_field.get_cache_name() or "...",
                remote_cls=self.model.__name__,
            )
        )
        exception.__cause__ = None
        raise exception
    elif (
        self.instance._prefetched_objects_cache
        and self.field.remote_field.get_cache_name() not in self.instance._prefetched_objects_cache
    ):
        exception = MissingReverseRelationField(
            "Access to `{cls}.{attr}.all()` was prevented.\n"
            "To fetch the `{remote_cls}` objects, add {x_related_name!r} to the existing `prefetch_related({existing_prefetch!s})` part of the query where `{cls}` objects are selected.".format(
                attr=self.field.remote_field.get_accessor_name(),
                cls=self.field.remote_field.model.__name__,
                x_related_name=self.field.remote_field.get_cache_name() or "...",
                remote_cls=self.model.__name__,
                existing_prefetch=", ".join(
                    "'{}'".format(key)
                    for key in sorted(self.instance._prefetched_objects_cache.keys())
                ),
            )
        )
        exception.__cause__ = None
        raise exception
    return self._shouty_all(*args, **kwargs)


def new_manytomany_descriptor_get(self, instance, cls=None):
    # type: (ManyToManyDescriptor, Model, None) -> Any
    """
    This is invoked when you're asking for mymodel.m2m.all() or more specifically
    asking for mymodel.m2m... accessing .all() in SOME scenarios will now
    raise an exception because we've proxied the manager due to prefetch_related
    usage (or lack thereof)
    """
    __traceback_hide__ = True
    if instance is None:
        return self

    if self.reverse is True:
        related_name = self.field.remote_field.get_cache_name()
    else:
        related_name = self.field.get_cache_name()

    manager = old_manytomany_descriptor_get(self, instance, cls)
    import pdb

    pdb.set_trace()
    prefetch_name = manager.prefetch_cache_name

    # noinspection PyProtectedMember
    if not hasattr(instance, "_prefetched_objects_cache"):
        return MissingPrefetchRelatedManager(
            manager,
            error_message=_TMPL_MISSING_M2M_PREFETCH.format(
                attr=related_name,
                cls=instance.__class__.__name__,
            ),
        )
    elif (
        instance._prefetched_objects_cache
        and prefetch_name not in instance._prefetched_objects_cache
    ):
        return MissingPrefetchRelatedManager(
            manager,
            error_message=_TMPL_MISSING_M2M_PREFETCH.format(
                attr=related_name,
                cls=instance.__class__.__name__,
            ),
        )
    return manager


def new_foreignkey_descriptor_get_object(self, instance):
    # type: (ForwardManyToOneDescriptor, Model) -> None
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
    # TODO: this could fail and not be set, for non-persisted or non-autofields, right?
    # my_pk = getattr(instance, "pk", None)
    # TODO: this could fail too?
    # their_pk = getattr(instance, self.field.get_attname(), None)

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

    if invalid_reverse_relations is True:
        patched_reverse_onetone = getattr(ReverseOneToOneDescriptor, "_shouty", False)
        if patched_reverse_onetone is False:
            ReverseOneToOneDescriptor.__get__ = new_reverse_onetoone_descriptor_get
            ReverseOneToOneDescriptor._shouty = True

        patched_reverse_manytoone = getattr(ReverseManyToOneDescriptor, "_shouty", False)

        if patched_reverse_manytoone is False:
            ReverseManyToOneDescriptor.__get__ = new_reverse_foreignkey_descriptor_get
            ReverseManyToOneDescriptor._shouty = True

    return True
