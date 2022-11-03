from __future__ import annotations

from unittest import skip

import django
from django.conf import settings
from django.db.models import F
from django.test import TestCase
from django.db import models, connection, DatabaseError

from django import VERSION as DJANGO_VERSION
from shoutyorm import MissingRelationField
from shoutyorm.errors import MissingManyToManyField, NoMoreFilteringAllowed

if not settings.configured:
    settings.configure(
        SECRET_KEY="shoutyorm-runtests" * 10,
        DATABASES={"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}},
        INSTALLED_APPS=("shoutyorm",),
        MIDDLEWARE=(),
        TEMPLATES=[
            {
                "BACKEND": "django.template.backends.django.DjangoTemplates",
                "DIRS": [],
                "APP_DIRS": True,
                "OPTIONS": {"context_processors": ()},
            },
        ],
        SHOUTY_LOCAL_FIELDS=True,
        SHOUTY_RELATION_FIELDS=True,
        SHOUTY_RELATION_REVERSE_FIELDS=True,
    )
    django.setup()


class ManyToManyTestCase(TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        class RelatedGroup(models.Model):
            title = models.CharField(max_length=100)

        class M2MItem(models.Model):
            title = models.CharField(max_length=100)
            groups = models.ManyToManyField(RelatedGroup)

        try:
            with connection.schema_editor() as editor:
                editor.create_model(RelatedGroup)
                editor.create_model(M2MItem)
        except DatabaseError as exc:
            raise cls.failureException("Unable to create the table (%s)" % exc)

        cls.Item = M2MItem
        cls.Group = RelatedGroup
        super().setUpClass()

    def test_accessing_nonprefetched_m2m_works_when_trying_to_add(self) -> None:
        """
        There are certain methods you want to access on an m2m which disregard
        the prefetch cache and should specifically not error.
        """
        with self.assertNumQueries(1):
            self.Item.objects.create(
                title="test item",
            )

        with self.assertNumQueries(1):
            group = self.Group.objects.create(title="group")

        q = 2
        if DJANGO_VERSION[0:2] < (3, 0):
            q = 3
        with self.assertNumQueries(q):
            group.m2mitem_set.add(self.Item.objects.create(title="item"))

    def test_accessing_nonprefetched_m2m_fails_when_accessing_all(self) -> None:
        """
        Normal use case - failure to prefetch should error loudly
        """
        with self.assertNumQueries(1):
            group = self.Group.objects.create(title="group")

        with self.assertNumQueries(0):
            with self.assertRaisesMessage(
                MissingManyToManyField,
                "Access to `RelatedGroup.m2mitem_set.all()` was prevented.\n"
                "To fetch the `M2MItem` objects, add `prefetch_related('m2mitem_set')` to the query where `RelatedGroup` objects are selected.",
            ):
                group.m2mitem_set.all()


class NestedManyToManyTestCase(TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        class NestedGroup(models.Model):
            title = models.CharField(max_length=100)

        class RelatedGroupForNesting(models.Model):
            title = models.CharField(max_length=100)
            nested = models.ManyToManyField(NestedGroup)

        class NestedItem(models.Model):
            title = models.CharField(max_length=100)
            groups = models.ManyToManyField(RelatedGroupForNesting)

        try:
            with connection.schema_editor() as editor:
                editor.create_model(NestedGroup)
                editor.create_model(RelatedGroupForNesting)
                editor.create_model(NestedItem)
        except DatabaseError as exc:
            raise cls.failureException("Unable to create the table (%s)" % exc)

        cls.Item = NestedItem
        cls.Group = RelatedGroupForNesting
        cls.NestedGroup = NestedGroup
        super().setUpClass()

    def test_accessing_nonprefetched_nested_relations_fails(self) -> None:
        """
        It's OK to access groups because we prefetched it, but accessing
        the group's nested set is NOT ok.
        """
        nested = self.NestedGroup.objects.create(title="nested")
        group = self.Group.objects.create(title="group")
        group.nested.add(nested)
        item = self.Item.objects.create(title="group")
        item.groups.add(group)

        with self.assertNumQueries(2):
            item2 = self.Item.objects.prefetch_related("groups").get(pk=item.pk)

        with self.assertNumQueries(0):
            (item_group,) = item2.groups.all()
            with self.assertRaisesMessage(
                MissingManyToManyField,
                "Access to `RelatedGroupForNesting.nested.all()` was prevented.\n"
                "To fetch the `NestedGroup` objects, add `prefetch_related('nested')` to the query where `RelatedGroupForNesting` objects are selected.",
            ):
                item_group.nested.all()

    def test_accessing_prefetched_nested_relations_is_ok(self) -> None:
        """
        It's OK to access groups because we prefetched it, but accessing
        the group's permissions is NOT ok.
        """
        nested = self.NestedGroup.objects.create(title="nested")
        group = self.Group.objects.create(title="group")
        group.nested.add(nested)
        item = self.Item.objects.create(title="group")
        item.groups.add(group)

        with self.assertNumQueries(3):
            item2 = self.Item.objects.prefetch_related("groups", "groups__nested").get(pk=item.pk)

        with self.assertNumQueries(0):
            (item_group,) = item2.groups.all()
            (item_group_nested,) = item_group.nested.all()

    def test_accessing_relations_involving_prefetch_objects_is_ok(self) -> None:
        """
        Make sure using a Prefetch object doesn't throw a spanner in the works.
        """
        nested = self.NestedGroup.objects.create(title="nested")
        group = self.Group.objects.create(title="group")
        group.nested.add(nested)
        item = self.Item.objects.create(title="group")
        item.groups.add(group)

        with self.assertNumQueries(3):
            item2 = self.Item.objects.prefetch_related(
                models.Prefetch("groups", self.Group.objects.filter(title="group")),
                "groups__nested",
            ).get(pk=item.pk)

        with self.assertNumQueries(0):
            (item_group,) = item2.groups.all()
            (item_group_nested,) = item_group.nested.all()

    def test_accessing_relations_involving_prefetch_objects_is_ok2(self) -> None:
        """
        Make sure using a Prefetch object doesn't throw a spanner in the works.
        """
        nested = self.NestedGroup.objects.create(title="nested")
        group = self.Group.objects.create(title="group")
        group.nested.add(nested)
        item = self.Item.objects.create(title="group")
        item.groups.add(group)

        with self.assertNumQueries(3):
            item2 = self.Item.objects.prefetch_related(
                "groups",
                models.Prefetch("groups__nested", self.NestedGroup.objects.filter(title="nested")),
            ).get(pk=item.pk)

        with self.assertNumQueries(0):
            (item_group,) = item2.groups.all()
            (item_group_nested,) = item_group.nested.all()

    def test_accessing_relations_involving_prefetch_objects_is_ok3(self) -> None:
        """
        Make sure using a Prefetch object doesn't throw a spanner in the works.
        """
        nested = self.NestedGroup.objects.create(title="nested")
        group = self.Group.objects.create(title="group")
        group.nested.add(nested)
        item = self.Item.objects.create(title="group")
        item.groups.add(group)

        with self.assertNumQueries(3):
            item2 = self.Item.objects.prefetch_related(
                models.Prefetch("groups__nested", self.NestedGroup.objects.filter(title="nested")),
            ).get(pk=item.pk)

        with self.assertNumQueries(0):
            (item_group,) = item2.groups.all()
            (item_group_nested,) = item_group.nested.all()


class MultipleManyToManyTestCase(TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        class AnotherRelatedThing(models.Model):
            title = models.CharField(max_length=100)

        class RelatedThing1(models.Model):
            title = models.CharField(max_length=100)

        class Thing(models.Model):
            title = models.CharField(max_length=100)
            relatable = models.ManyToManyField(RelatedThing1)
            unrelatable = models.ManyToManyField(AnotherRelatedThing)

        try:
            with connection.schema_editor() as editor:
                editor.create_model(AnotherRelatedThing)
                editor.create_model(RelatedThing1)
                editor.create_model(Thing)
        except DatabaseError as exc:
            raise cls.failureException("Unable to create the table (%s)" % exc)

        cls.Thing = Thing
        cls.RelatedThing1 = RelatedThing1
        cls.RelatedThing2 = AnotherRelatedThing
        super().setUpClass()

    def test_accessing_multiple_prefetched_nonnested_relations_is_ok(self) -> None:
        """
        Accessing more than 1 prefetch at the same level is OK.
        This was part of the difficulty in figuring this out, because by the
        time you get to the second prefetch selection you need to NOT prevent
        access to the queryset until ALL prefetching looks to have finished.
        """
        thing = self.Thing.objects.create(title="thing")
        thing.relatable.add(self.RelatedThing1.objects.create(title="relatable"))
        thing.unrelatable.add(self.RelatedThing2.objects.create(title="unrelatable"))

        with self.assertNumQueries(3):
            i = self.Thing.objects.prefetch_related("relatable", "unrelatable").get(pk=thing.pk)
        with self.assertNumQueries(0):
            tuple(i.relatable.all())
            tuple(i.unrelatable.all())


class ManyToManyMethodsTestCase(TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        class RelatedThing2(models.Model):
            title = models.CharField(max_length=100)

        class Thing2(models.Model):
            title = models.CharField(max_length=100)
            relatable = models.ManyToManyField(RelatedThing2)

        try:
            with connection.schema_editor() as editor:
                editor.create_model(RelatedThing2)
                editor.create_model(Thing2)
        except DatabaseError as exc:
            raise cls.failureException("Unable to create the table (%s)" % exc)

        cls.Thing = Thing2
        cls.RelatedThing = RelatedThing2
        super().setUpClass()

    def test_count_when_prefetched(self) -> None:
        thing = self.Thing.objects.create(title="thing")
        thing.relatable.add(self.RelatedThing.objects.create(title="relatable"))

        with self.assertNumQueries(2):
            (thing,) = self.Thing.objects.prefetch_related("relatable").all()

        with self.assertNumQueries(0):
            self.assertEqual(thing.relatable.count(), 1)

    def test_filter_when_prefetched(self) -> None:
        thing = self.Thing.objects.create(title="thing")
        thing.relatable.add(self.RelatedThing.objects.create(title="relatable"))

        with self.assertNumQueries(2):
            (thing,) = self.Thing.objects.prefetch_related("relatable").all()

        with self.subTest("Manager filter"), self.assertNumQueries(0), self.assertRaisesMessage(
            NoMoreFilteringAllowed,
            "Access to `relatable.filter(...)` via `Thing2` instance was prevented because of previous `prefetch_related('relatable')`\n"
            "Filter existing objects in memory with:\n"
            "`[relatedthing2 for relatedthing2 in thing2.relatable.all() if relatedthing2 ...]`\n"
            "Filter new objects from the database with:\n"
            "`RelatedThing2.objects.filter(thing2=thing2.pk, ...)`",
        ):
            (relatable_thing,) = thing.relatable.filter(title="Bert")

    def test_exclude_when_prefetched(self) -> None:
        thing = self.Thing.objects.create(title="thing")
        thing.relatable.add(self.RelatedThing.objects.create(title="relatable"))

        with self.assertNumQueries(2):
            (thing,) = self.Thing.objects.prefetch_related("relatable").all()

        with self.subTest("Manager exclude"), self.assertNumQueries(0), self.assertRaisesMessage(
            NoMoreFilteringAllowed,
            "Access to `relatable.exclude(...)` via `Thing2` instance was prevented because of previous `prefetch_related('relatable')`\n"
            "Exclude existing objects in memory with:\n"
            "`[relatedthing2 for relatedthing2 in thing2.relatable.all() if relatedthing2 != ...]`\n"
            "Exclude new objects from the database with:\n"
            "`RelatedThing2.objects.filter(thing2=thing2.pk).exclude(...)`",
        ):
            (relatable_thing,) = thing.relatable.exclude(title="Bert")

    def test_annotate_when_prefetched(self) -> None:
        thing = self.Thing.objects.create(title="thing")
        thing.relatable.add(self.RelatedThing.objects.create(title="relatable"))

        with self.assertNumQueries(2):
            (thing,) = self.Thing.objects.prefetch_related("relatable").all()

        with self.subTest("Manager annotate"), self.assertNumQueries(0), self.assertRaisesMessage(
            NoMoreFilteringAllowed,
            "Access to `relatable.annotate(...)` via `Thing2` instance was prevented because of previous `prefetch_related('relatable')`\n"
            "Annotate existing objects in memory with:\n"
            "`for relatedthing2 in thing2.relatable.all(): relatedthing2.xyz = ...`\n"
            "Annotate new objects from the database with:\n"
            "`RelatedThing2.objects.filter(thing2=thing2.pk).annotate(...)`",
        ):
            (relatable_thing,) = thing.relatable.annotate(
                title2=models.Value(True, output_field=models.BooleanField())
            )

    def test_earliest_when_prefetched(self) -> None:
        thing = self.Thing.objects.create(title="thing")
        thing.relatable.add(self.RelatedThing.objects.create(title="relatable"))

        with self.assertNumQueries(2):
            (thing,) = self.Thing.objects.prefetch_related("relatable").all()

        with self.subTest("Manager earliest"), self.assertNumQueries(0), self.assertRaisesMessage(
            NoMoreFilteringAllowed,
            "Access to `relatable.earliest(...)` via `Thing2` instance was prevented because of previous `prefetch_related('relatable')`\n"
            "Fetch the earliest existing `RelatedThing2` in memory with:\n"
            "`sorted(thing2.relatable.all(), key=itertools.attrgetter(...))[0]`\n"
            "Fetch the earliest `RelatedThing2` from the database with:\n"
            "`RelatedThing2.objects.order_by(...).get(thing2=thing2.pk)`",
        ):
            (relatable_thing,) = thing.relatable.earliest("title")

    def test_latest_when_prefetched(self) -> None:
        thing = self.Thing.objects.create(title="thing")
        thing.relatable.add(self.RelatedThing.objects.create(title="relatable"))

        with self.assertNumQueries(2):
            (thing,) = self.Thing.objects.prefetch_related("relatable").all()

        with self.subTest("Manager latest"), self.assertNumQueries(0), self.assertRaisesMessage(
            NoMoreFilteringAllowed,
            "Access to `relatable.latest(...)` via `Thing2` instance was prevented because of previous `prefetch_related('relatable')`\n"
            "Fetch the latest existing `RelatedThing2` in memory with:\n"
            "`sorted(thing2.relatable.all(), reverse=True, key=itertools.attrgetter(...))[0]`\n"
            "Fetch the latest `RelatedThing2` from the database with:\n"
            "`RelatedThing2.objects.order_by(...).get(thing2=thing2.pk)`",
        ):
            (relatable_thing,) = thing.relatable.latest("title")

    @skip("TODO: Not implemented")
    def test_first_when_prefetched(self) -> None:
        pass

    @skip("TODO: Not implemented")
    def test_last_when_prefetched(self) -> None:
        pass

    def test_in_bulk_when_prefetched(self) -> None:
        thing = self.Thing.objects.create(title="thing")
        thing.relatable.add(self.RelatedThing.objects.create(title="relatable"))

        with self.assertNumQueries(2):
            (thing,) = self.Thing.objects.prefetch_related("relatable").all()

        with self.subTest("Manager in_bulk"), self.assertNumQueries(0), self.assertRaisesMessage(
            NoMoreFilteringAllowed,
            "Access to `relatable.in_bulk(...)` via `Thing2` instance was prevented because of previous `prefetch_related('relatable')`\n"
            "Convert the existing in memory `RelatedThing2` instances with:\n"
            "`{relatedthing2.pk: relatedthing2 for relatedthing2 in thing2.relatable.all()}`\n"
            "Fetch the latest `RelatedThing2` from the database with:\n"
            "`RelatedThing2.objects.filter(thing2=thing2.pk).in_bulk()`",
        ):
            (relatable_thing,) = thing.relatable.in_bulk()

    def test_defer_only_when_prefetched(self) -> None:
        thing = self.Thing.objects.create(title="thing")
        thing.relatable.add(self.RelatedThing.objects.create(title="relatable"))

        with self.assertNumQueries(2):
            (thing,) = self.Thing.objects.prefetch_related("relatable").all()

        with self.subTest("Manager defer"), self.assertNumQueries(0), self.assertRaisesMessage(
            NoMoreFilteringAllowed,
            "Access to `relatable.defer(...)` via `Thing2` instance was prevented because of previous `prefetch_related('relatable')`\n"
            "You already have `RelatedThing2` instances in-memory.",
        ):
            (relatable_thing,) = thing.relatable.defer("title")

        # This exception will suppress `MissingLocalField`
        # Access to `Model.attr_id` was prevented.\n"
        # Remove the `only(...)` or remove the `defer(...)` where `Model` objects are selected
        with self.subTest("Manager only"), self.assertNumQueries(0), self.assertRaisesMessage(
            NoMoreFilteringAllowed,
            "Access to `relatable.only(...)` via `Thing2` instance was prevented because of previous `prefetch_related('relatable')`\n"
            "You already have `RelatedThing2` instances in-memory.",
        ):
            (relatable_thing,) = thing.relatable.only("title")

    def test_reverse_when_prefetched(self) -> None:
        thing = self.Thing.objects.create(title="thing")
        thing.relatable.add(self.RelatedThing.objects.create(title="relatable"))

        with self.assertNumQueries(2):
            (thing,) = self.Thing.objects.prefetch_related("relatable").all()

        with self.subTest("Manager reversed"), self.assertNumQueries(0), self.assertRaisesMessage(
            NoMoreFilteringAllowed,
            "Access to `relatable.reverse()` via `Thing2` instance was prevented because of previous `prefetch_related('relatable')`\n"
            "Convert the existing in memory `RelatedThing2` instances with:\n"
            "`tuple(reversed(thing2.relatable.all()))`\n"
            "Fetch the latest `RelatedThing2` from the database with:\n"
            "`RelatedThing2.objects.filter(thing2=thing2.pk).order_by(...)`",
        ):
            (relatable_thing,) = thing.relatable.reverse()

    def test_distinct_when_prefetched(self) -> None:
        thing = self.Thing.objects.create(title="thing")
        thing.relatable.add(self.RelatedThing.objects.create(title="relatable"))

        with self.assertNumQueries(2):
            (thing,) = self.Thing.objects.prefetch_related("relatable").all()

        with self.subTest("Manager distinct"), self.assertNumQueries(0), self.assertRaisesMessage(
            NoMoreFilteringAllowed,
            "Access to `relatable.distinct(...)` via `Thing2` instance was prevented because of previous `prefetch_related('relatable')`",
        ):
            (relatable_thing,) = thing.relatable.distinct()

    def test_values_when_prefetched(self) -> None:
        thing = self.Thing.objects.create(title="thing")
        thing.relatable.add(self.RelatedThing.objects.create(title="relatable"))

        with self.assertNumQueries(2):
            (thing,) = self.Thing.objects.prefetch_related("relatable").all()

        with self.subTest("Manager values"), self.assertNumQueries(0), self.assertRaisesMessage(
            NoMoreFilteringAllowed,
            "Access to `relatable.values(...)` via `Thing2` instance was prevented because of previous `prefetch_related('relatable')`\n"
            "Convert the existing in memory `RelatedThing2` instances with:\n"
            '`[{"attr1": relatedthing2.attr1, "attr2": relatedthing2.attr2, ...} for relatedthing2 in thing2.relatable.all()]`\n'
            "Fetch the latest `RelatedThing2` from the database with:\n"
            "`RelatedThing2.objects.filter(thing2=thing2.pk).values(...)`",
        ):
            (relatable_thing,) = thing.relatable.values("title")

    def test_values_list_list_when_prefetched(self) -> None:
        thing = self.Thing.objects.create(title="thing")
        thing.relatable.add(self.RelatedThing.objects.create(title="relatable"))

        with self.assertNumQueries(2):
            (thing,) = self.Thing.objects.prefetch_related("relatable").all()

        with self.subTest("Manager values_list"), self.assertNumQueries(
            0
        ), self.assertRaisesMessage(
            NoMoreFilteringAllowed,
            "Access to `relatable.values_list(...)` via `Thing2` instance was prevented because of previous `prefetch_related('relatable')`\n"
            "Convert the existing in memory `RelatedThing2` instances with:\n"
            '`[(relatedthing2.attr1, "attr2": relatedthing2.attr2, ...) for relatedthing2 in thing2.relatable.all()]`\n'
            "Fetch the latest `RelatedThing2` from the database with:\n"
            "`RelatedThing2.objects.filter(thing2=thing2.pk).values_list(...)`",
        ):
            (relatable_thing,) = thing.relatable.values_list("title")

    def test_order_by_list_when_prefetched(self) -> None:
        thing = self.Thing.objects.create(title="thing")
        thing.relatable.add(self.RelatedThing.objects.create(title="relatable"))

        with self.assertNumQueries(2):
            (thing,) = self.Thing.objects.prefetch_related("relatable").all()

        with self.subTest("Manager order_by"), self.assertNumQueries(0), self.assertRaisesMessage(
            NoMoreFilteringAllowed,
            "Access to `relatable.order_by(...)` via `Thing2` instance was prevented because of previous `prefetch_related('relatable')`\n"
            "Convert the existing in memory `RelatedThing2` instances with:\n"
            "`sorted(thing2.relatable.all(), key=itertools.attrgetter(...))`\n"
            "Fetch the latest `RelatedThing2` from the database with:\n"
            "`RelatedThing2.objects.filter(thing2=thing2.pk).order_by(...)`",
        ):
            (relatable_thing,) = thing.relatable.order_by("title")

    def test_extra_when_prefetched(self) -> None:
        thing = self.Thing.objects.create(title="thing")
        thing.relatable.add(self.RelatedThing.objects.create(title="relatable"))

        with self.assertNumQueries(2):
            (thing,) = self.Thing.objects.prefetch_related("relatable").all()

        with self.subTest("Manager extra"), self.assertNumQueries(0), self.assertRaisesMessage(
            NoMoreFilteringAllowed,
            "Access to `relatable.extra(...)` via `Thing2` instance was prevented because of previous `prefetch_related('relatable')`\n"
            "Update your `prefetch_related` to use `prefetch_related(Prefetch('relatable', RelatedThing2.objects.extra(...)))",
        ):
            (relatable_thing,) = thing.relatable.extra()

    def test_select_related_when_prefetched(self) -> None:
        thing = self.Thing.objects.create(title="thing")
        thing.relatable.add(self.RelatedThing.objects.create(title="relatable"))

        with self.assertNumQueries(2):
            (thing,) = self.Thing.objects.prefetch_related("relatable").all()

        with self.subTest("Manager select_related"), self.assertNumQueries(
            0
        ), self.assertRaisesMessage(
            NoMoreFilteringAllowed,
            "Access to `relatable.select_related(...)` via `Thing2` instance was prevented because of previous `prefetch_related('relatable')`\n"
            "Update your `prefetch_related` to use `prefetch_related(Prefetch('relatable', RelatedThing2.objects.select_related(...)))",
        ):
            (relatable_thing,) = thing.relatable.select_related()

    def test_alias_when_prefetched(self) -> None:
        thing = self.Thing.objects.create(title="thing")
        thing.relatable.add(self.RelatedThing.objects.create(title="relatable"))

        with self.assertNumQueries(2):
            (thing,) = self.Thing.objects.prefetch_related("relatable").all()

        with self.subTest("Manager alias"), self.assertNumQueries(0), self.assertRaisesMessage(
            NoMoreFilteringAllowed,
            "Access to `relatable.alias(...)` via `Thing2` instance was prevented because of previous `prefetch_related('relatable')`",
        ):
            (relatable_thing,) = thing.relatable.alias(title2=F("title"))

    def test_prefetch_related_when_prefetched(self) -> None:
        thing = self.Thing.objects.create(title="thing")
        thing.relatable.add(self.RelatedThing.objects.create(title="relatable"))

        with self.assertNumQueries(2):
            (thing,) = self.Thing.objects.prefetch_related("relatable").all()

        with self.subTest("Manager prefetch_related"), self.assertNumQueries(
            0
        ), self.assertRaisesMessage(
            NoMoreFilteringAllowed,
            "Access to `relatable.prefetch_related(...)` via `Thing2` instance was prevented because of previous `prefetch_related('relatable')`\n"
            "Update your `prefetch_related` to use `prefetch_related('relatable', 'relatable__attr')`",
        ):
            (relatable_thing,) = thing.relatable.prefetch_related("thing")
