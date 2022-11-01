import django
from django.conf import settings
from django.test import TestCase
from django.db import models, connection, DatabaseError

from django import VERSION as DJANGO_VERSION
from shoutyorm import MissingRelationField
from shoutyorm.errors import MissingManyToManyField

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
    def setUpClass(cls):
        # type: () -> None
        class RelatedGroup(models.Model):
            title = models.CharField(max_length=100)

            # class Meta:
            #     app_label = "shoutyorm"
            #     db_table = "shoutyorm_{file}_{testcase}".format(file=__name__.replace('.', '_'), testcase=cls.__qualname__.lower())

        class M2MItem(models.Model):
            title = models.CharField(max_length=100)
            groups = models.ManyToManyField(RelatedGroup)

            # class Meta:
            #     app_label = "shoutyorm"
            #     db_table = "shoutyorm_{file}_{testcase}".format(file=__name__.replace('.', '_'), testcase=cls.__qualname__.lower())

        try:
            with connection.schema_editor() as editor:
                editor.create_model(RelatedGroup)
                editor.create_model(M2MItem)
        except DatabaseError as exc:
            raise cls.failureException("Unable to create the table (%s)" % exc)

        cls.Item = M2MItem
        cls.Group = RelatedGroup
        super().setUpClass()

    def test_accessing_nonprefetched_m2m_works_when_trying_to_add(self):
        # type: () -> None
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

    def test_accessing_nonprefetched_m2m_fails_when_accessing_all(self):
        # type: () -> None
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
    def setUpClass(cls):
        # type: () -> None

        class NestedGroup(models.Model):
            title = models.CharField(max_length=100)

            # class Meta:
            #     app_label = "shoutyorm"
            #     db_table = "shoutyorm_{file}_{testcase}".format(
            #         file=__name__.replace(".", "_"), testcase=cls.__qualname__.lower()
            #     )

        class RelatedGroupForNesting(models.Model):
            title = models.CharField(max_length=100)
            nested = models.ManyToManyField(NestedGroup)

            # class Meta:
            #     app_label = "shoutyorm"
            #     db_table = "shoutyorm_{file}_{testcase}".format(
            #         file=__name__.replace(".", "_"), testcase=cls.__qualname__.lower()
            #     )

        class NestedItem(models.Model):
            title = models.CharField(max_length=100)
            groups = models.ManyToManyField(RelatedGroupForNesting)

            # class Meta:
            #     app_label = "shoutyorm"
            #     db_table = "shoutyorm_{file}_{testcase}".format(
            #         file=__name__.replace(".", "_"), testcase=cls.__qualname__.lower()
            #     )

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

            # class Meta:
            #     app_label = "shoutyorm"
            #     db_table = "shoutyorm_{file}_{testcase}".format(
            #         file=__name__.replace(".", "_"), testcase=cls.__qualname__.lower()
            #     )

        class RelatedThing1(models.Model):
            title = models.CharField(max_length=100)

            # class Meta:
            #     app_label = "shoutyorm"
            #     db_table = "shoutyorm_{file}_{testcase}".format(
            #         file=__name__.replace(".", "_"), testcase=cls.__qualname__.lower()
            #     )

        class Thing(models.Model):
            title = models.CharField(max_length=100)
            relatable = models.ManyToManyField(RelatedThing1)
            unrelatable = models.ManyToManyField(RelatedThing2)

            # class Meta:
            #     app_label = "shoutyorm"
            #     db_table = "shoutyorm_{file}_{testcase}".format(
            #         file=__name__.replace(".", "_"), testcase=cls.__qualname__.lower()
            #     )

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
            tuple(i.relatable.all())
            tuple(i.unrelatable.all())
