from django.test import TestCase
from django.db import models, connection, DatabaseError
from shoutyorm.errors import MissingForeignKeyField, MissingLocalField


class OnlyDeferTestCase(TestCase):
    @classmethod
    def setUpClass(cls):
        # type: () -> None
        class RelatedThing(models.Model):
            title = models.CharField(max_length=100)

        class Item(models.Model):
            title = models.CharField(max_length=100)
            created = models.DateTimeField(auto_now_add=True)
            modified = models.DateTimeField(auto_now=True)
            related_thing = models.ForeignKey(
                RelatedThing,
                on_delete=models.CASCADE,
                db_column="related_thingie",
                related_name="related_things",
            )

        try:
            with connection.schema_editor() as editor:
                editor.create_model(RelatedThing)
                editor.create_model(Item)
        except DatabaseError as exc:
            raise cls.failureException("Unable to create the table (%s)" % exc)

        cls.Item = Item
        cls.RelatedThing = RelatedThing
        super().setUpClass()

    def test_normal_behaviour(self):
        # type: () -> None
        with self.assertNumQueries(2):
            self.Item.objects.create(
                title="test item",
                related_thing=self.RelatedThing.objects.create(title="test related thing"),
            )
        with self.assertNumQueries(1):
            (item,) = self.Item.objects.all()
        with self.assertNumQueries(0):
            item.pk
            item.title
            item.created
            item.modified
        with self.assertRaises(MissingForeignKeyField):
            item.related_thing

    def test_only(self):
        """columns not selected via .only() will error"""

        self.Item.objects.create(
            title="test item",
            related_thing=self.RelatedThing.objects.create(title="test related thing"),
        )
        with self.assertNumQueries(1):
            (item,) = self.Item.objects.only("title", "created").all()
        with self.assertNumQueries(0):
            self.assertEqual(item.title, "test item")
            item.pk
            item.created
            with self.assertRaisesMessage(
                MissingLocalField,
                "Access to `Item.modified` was prevented.\n"
                "Add `modified` to `only('created', 'id', 'title')` or remove `modified` from `defer('modified', 'related_thing_id')` where `Item` objects are selected`",
            ):
                item.modified
            # TODO: fix this to be MissingForeignKeyField preferrably
            with self.assertRaises(
                MissingLocalField,
            ):
                item.related_thing

    def test_defer(self):
        """columns not selected via .defer() will error"""

        self.Item.objects.create(
            title="test item",
            related_thing=self.RelatedThing.objects.create(title="test related thing"),
        )
        with self.assertNumQueries(1):
            (item,) = self.Item.objects.defer("created", "modified").all()
        with self.assertNumQueries(0):
            self.assertEqual(item.title, "test item")
            item.pk
            with self.assertRaisesMessage(
                MissingLocalField,
                "Access to `Item.modified` was prevented.\n"
                "Add `modified` to `only('id', 'related_thing_id', 'title')` or remove `modified` from `defer('created', 'modified')` where `Item` objects are selected`",
            ):
                item.modified
            # TODO: this returns the correct thing (weirdly!) but is inconsistent with only() above.
            with self.assertRaises(
                MissingForeignKeyField,
            ):
                item.related_thing

    def test_annotations(self):
        """Annotations work OK even with only()/defer()"""

        self.Item.objects.create(
            title="test item",
            related_thing=self.RelatedThing.objects.create(title="test related thing"),
        )
        with self.assertNumQueries(1):
            (item,) = self.Item.objects.defer("created", "modified").annotate(
                testing=models.Value(True, output_field=models.BooleanField()),
                testing_aliasing=models.F("title"),
            )
        with self.assertNumQueries(0):
            self.assertEqual(item.title, "test item")
            item.pk
            # noinspection PyUnresolvedReferences
            self.assertTrue(item.testing)
            # noinspection PyUnresolvedReferences
            self.assertEqual(item.testing_aliasing, item.title)
            with self.assertRaisesMessage(
                MissingLocalField,
                "Access to `Item.modified` was prevented.\n"
                "Add `modified` to `only('id', 'related_thing_id', 'title')` or remove `modified` from `defer('created', 'modified')` where `Item` objects are selected`",
            ):
                item.modified