from django.test import TestCase
from django.db import models, connection, DatabaseError

from django import VERSION as DJANGO_VERSION
from shoutyorm import MissingRelationField


class ManyToManyTestCase(TestCase):
    @classmethod
    def setUpClass(cls):
        # type: () -> None
        class RelatedGroup(models.Model):
            title = models.CharField(max_length=100)

        class Item(models.Model):
            title = models.CharField(max_length=100)
            groups = models.ManyToManyField(RelatedGroup)

        try:
            with connection.schema_editor() as editor:
                editor.create_model(RelatedGroup)
                editor.create_model(Item)
        except DatabaseError as exc:
            raise cls.failureException("Unable to create the table (%s)" % exc)

        cls.Item = Item
        cls.Group = RelatedGroup
        super().setUpClass()

    def test_accessing_nonprefetched_m2m_works_when_trying_to_add(self):
        # type: () -> None
        """
        There are certain methods you want to access on an m2m which disregard
        the prefetch cache and should specifically not error.
        """
        with self.assertNumQueries(2):
            self.Item.objects.create(
                title="test item",
                related_thing=self.RelatedThing.objects.create(title="test related thing"),
            )

        with self.assertNumQueries(1):
            group = self.Group.objects.create(title="group")

        q = 2
        if DJANGO_VERSION[0:2] < (3, 0):
            q = 3
        with self.assertNumQueries(q):
            group.item_set.add(self.Item.objects.create(title="item"))

    def test_accessing_nonprefetched_m2m_fails_when_accessing_all(self):
        # type: () -> None
        """
        Normal use case - failure to prefetch should error loudly
        """
        with self.assertNumQueries(1):
            group = self.Group.objects.create(title="group")

        with self.assertNumQueries(1):
            with self.assertRaisesMessage(
                MissingRelationField,
                "Access to 'user_set' ManyToMany manager attribute on Group was prevented because it was not selected.\nProbably missing from prefetch_related()",
            ):
                group.item_set.all()


class NestedManyToManyTestCase(TestCase):
    @classmethod
    def setUpClass(cls):
        # type: () -> None

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

    def test_accessing_nonprefetched_nested_relations_fails(self):
        # type: () -> None
        """
        It's OK to access groups because we prefetched it, but accessing
        the group's permissions is NOT ok.
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
                MissingRelationField,
                "Access to 'user_permissions' ManyToMany manager attribute on User was prevented because it was not selected.\nProbably missing from prefetch_related()",
            ):
                item_group.nested.all()

    def test_accessing_prefetched_nested_relations_is_ok(self):
        # type: () -> None
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

    def test_accessing_relations_involving_prefetch_objects_is_ok(self):
        # type: () -> None
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

    def test_accessing_relations_involving_prefetch_objects_is_ok2(self):
        # type: () -> None
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

    def test_accessing_relations_involving_prefetch_objects_is_ok3(self):
        # type: () -> None
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
    def setUpClass(cls):
        # type: () -> None

        class RelatedThing2(models.Model):
            title = models.CharField(max_length=100)

        class RelatedThing1(models.Model):
            title = models.CharField(max_length=100)

        class Thing(models.Model):
            title = models.CharField(max_length=100)
            relatable = models.ManyToManyField(RelatedThing1)
            unrelatable = models.ManyToManyField(RelatedThing2)

        try:
            with connection.schema_editor() as editor:
                editor.create_model(RelatedThing2)
                editor.create_model(RelatedThing1)
                editor.create_model(Thing)
        except DatabaseError as exc:
            raise cls.failureException("Unable to create the table (%s)" % exc)

        cls.Thing = Thing
        cls.RelatedThing1 = RelatedThing1
        cls.RelatedThing2 = RelatedThing2
        super().setUpClass()

    def test_accessing_multiple_prefetched_nonnested_relations_is_ok(self):
        # type: () -> None
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
            tuple(i.user_set.all())
            tuple(i.permissions.all())
