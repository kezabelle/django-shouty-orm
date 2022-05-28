from django.db import models, connection, DatabaseError
from django.test import TestCase
from shoutyorm.errors import MissingOneToOneField


class ForwardOneToOneDescriptorTestCase(TestCase):
    @classmethod
    def setUpClass(cls):
        # type: () -> None
        class CassetteSideB(models.Model):
            title = models.CharField(max_length=100)

        class CassetteSideA(models.Model):
            title = models.CharField(max_length=100)
            side_b = models.OneToOneField(
                CassetteSideB,
                on_delete=models.CASCADE,
                db_column="yay_side_b",
                related_name="woo_side_b",
            )

        try:
            with connection.schema_editor() as editor:
                editor.create_model(CassetteSideB)
                editor.create_model(CassetteSideA)
        except DatabaseError as exc:
            raise cls.failureException("Unable to create the table (%s)" % exc)

        cls.CassetteSideB = CassetteSideB
        cls.CassetteSideA = CassetteSideA
        super().setUpClass()

    def test_forward_one_to_one_not_selected(self):
        """myobject.myrelation is a OneToOneField which has not been fetched"""
        self.CassetteSideA.objects.create(
            title="Side A!", side_b=self.CassetteSideB.objects.create(title="Side B!")
        )
        with self.assertNumQueries(1):
            (side_a,) = self.CassetteSideA.objects.all()
            with self.assertNumQueries(0):
                self.assertEqual(side_a.title, "Side A!")
                side_a.pk
                side_a.side_b_id
                with self.assertRaisesMessage(
                    MissingOneToOneField,
                    "Access to `CassetteSideA.side_b` was prevented.\n"
                    "If you only need access to the column identifier, use `CassetteSideA.side_b_id` instead.\n"
                    "To fetch the `CassetteSideB` object, add `prefetch_related('side_b')` or `select_related('side_b')` to the query where `CassetteSideA` objects are selected.",
                ):
                    side_a.side_b

    def test_forward_one_to_one_prefetch_related(self):
        """myobject.myrelation is a OneToOneField which has prefetched (for ... reasons)"""
        self.CassetteSideA.objects.create(
            title="Side A!", side_b=self.CassetteSideB.objects.create(title="Side B!")
        )

        with self.assertNumQueries(2):
            (side_a,) = self.CassetteSideA.objects.prefetch_related("side_b").all()
            self.assertEqual(side_a.side_b.title, "Side B!")

    def test_forward_one_to_one_select_relatd(self):
        """myobject.myrelation is a OneToOneField which has been joined"""
        self.CassetteSideA.objects.create(
            title="Side A!", side_b=self.CassetteSideB.objects.create(title="Side B!")
        )
        with self.assertNumQueries(1):
            (side_a,) = self.CassetteSideA.objects.select_related("side_b").all()
            self.assertEqual(side_a.side_b.title, "Side B!")
