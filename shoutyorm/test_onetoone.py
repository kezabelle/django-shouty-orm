from __future__ import annotations
import django
from django.conf import settings
from django.db import models, connection, DatabaseError
from django.test import TestCase
from shoutyorm.errors import MissingRelationField

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


class ForwardOneToOneDescriptorTestCase(TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        class CassetteNullRelation(models.Model):
            pass

        class CassetteSideB(models.Model):
            title = models.CharField(max_length=100)

        class CassetteSideA(models.Model):
            title = models.CharField(max_length=100)
            side_b = models.OneToOneField(
                CassetteSideB,
                on_delete=models.CASCADE,
                db_column="yay_side_b",
                related_name="woo_side_a",
            )
            nullable_thing = models.OneToOneField(
                CassetteNullRelation,
                on_delete=models.SET_NULL,
                null=True,
            )

        try:
            with connection.schema_editor() as editor:
                editor.create_model(CassetteNullRelation)
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
                    MissingRelationField,
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
        with self.assertNumQueries(0):
            self.assertEqual(side_a.side_b.title, "Side B!")
            self.assertEqual(side_a.title, "Side A!")

    def test_forward_one_to_one_select_relatd(self):
        """myobject.myrelation is a OneToOneField which has been joined"""
        self.CassetteSideA.objects.create(
            title="Side A!", side_b=self.CassetteSideB.objects.create(title="Side B!")
        )
        with self.assertNumQueries(1):
            (side_a,) = self.CassetteSideA.objects.select_related("side_b").all()
        with self.assertNumQueries(0):
            self.assertEqual(side_a.side_b.title, "Side B!")
            self.assertEqual(side_a.title, "Side A!")

    def test_objects_create(self):
        """
        Creating with .create(<field>_id) and then using <field> later is OK

        Required patching Model.save_base to track whether an instance was freshly
        minted or not.
        """
        side_a1 = self.CassetteSideA.objects.create(
            title="Side A!", side_b=self.CassetteSideB.objects.create(title="Side B!")
        )
        # Already cached, no query
        with self.assertNumQueries(0):
            self.assertEqual(side_a1.side_b.title, "Side B!")

        side_b2 = self.CassetteSideB.objects.create(title="Side B!")
        side_a2 = self.CassetteSideA.objects.create(
            title="Side A!",
            side_b_id=side_b2.pk,
            nullable_thing_id=None,
        )
        # Not cached, set via <field>_id, needs fetching
        with self.assertNumQueries(1):
            self.assertEqual(side_a2.side_b.title, "Side B!")
            self.assertIsNone(side_a2.nullable_thing)

    def test_model_create(self):
        """
        Creating with Model(<field>_id).save() and then using <field> later is OK

        Required patching Model.save_base to track whether an instance was freshly
        minted or not.
        """
        side_a1 = self.CassetteSideA(
            title="Side A!", side_b=self.CassetteSideB.objects.create(title="Side B!")
        )
        side_a1.save()
        # Already cached, no query
        with self.assertNumQueries(0):
            self.assertEqual(side_a1.side_b.title, "Side B!")

        side_b2 = self.CassetteSideB.objects.create(title="Side B!")
        side_a2 = self.CassetteSideA(
            title="Side A!",
            side_b_id=side_b2.pk,
            nullable_thing_id=None,
        )
        side_a2.save()
        # Not cached, set via <field>_id, needs fetching
        with self.assertNumQueries(1):
            self.assertEqual(side_a2.side_b.title, "Side B!")
            self.assertIsNone(side_a2.nullable_thing)

    def test_get_or_create_by_instance(self):
        side_b = self.CassetteSideB.objects.create(title="Side B!")
        # This goes through the create path.
        # SELECT shoutyorm_cassettesidea + shoutyorm_cassettesideb
        # SAVEPOINT
        # INSERT shoutyorm_cassettesidea
        # RELEASE
        with self.assertNumQueries(4):
            side_a, created = self.CassetteSideA.objects.select_related("side_b").get_or_create(
                title="Side A!", defaults={"side_b": side_b}
            )
        self.assertTrue(created)
        with self.assertNumQueries(0):
            side_a.side_b

        # This will force going through the get path.
        # SELECT shoutyorm_cassettesidea + shoutyorm_cassettesideb
        with self.assertNumQueries(1):
            side_a, created = self.CassetteSideA.objects.select_related("side_b").get_or_create(
                title="Side A!", defaults={"side_b": side_b}
            )
        self.assertFalse(created)
        with self.assertNumQueries(0):
            side_a.side_b

    def test_get_or_create_by_id(self):
        side_b = self.CassetteSideB.objects.create(title="Side B!")
        # This goes through the create path.
        # SELECT shoutyorm_cassettesidea + shoutyorm_cassettesideb
        # SAVEPOINT
        # INSERT shoutyorm_cassettesidea
        # RELEASE
        with self.assertNumQueries(4):
            side_a, created = self.CassetteSideA.objects.select_related("side_b").get_or_create(
                title="Side A!", defaults={"side_b_id": side_b.pk}
            )
        self.assertTrue(created)
        # SELECT shoutyorm_cassettesideb
        # This is allowed to do a query because we cannot avoid one; see
        # the new_foreignkey_descriptor_get_object comments.
        with self.assertNumQueries(1):
            side_a.side_b

        # This will force going through the get path, and doesn't error.
        # SELECT shoutyorm_cassettesidea + shoutyorm_cassettesideb
        with self.assertNumQueries(1):
            side_a, created = self.CassetteSideA.objects.select_related("side_b").get_or_create(
                title="Side A!", defaults={"side_b_id": side_b.pk}
            )
        self.assertFalse(created)
        with self.assertNumQueries(0):
            side_a.side_b


class ReverseOneToOneDescriptorTestCase(TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        class RewindingCassetteSideB(models.Model):
            title = models.CharField(max_length=100)

        class RewindingCassetteSideA(models.Model):
            title = models.CharField(max_length=100)
            side_b = models.OneToOneField(
                RewindingCassetteSideB,
                on_delete=models.CASCADE,
                db_column="yay_side_b",
                related_name="woo_side_a",
            )

        try:
            with connection.schema_editor() as editor:
                editor.create_model(RewindingCassetteSideB)
                editor.create_model(RewindingCassetteSideA)
        except DatabaseError as exc:
            raise cls.failureException("Unable to create the table (%s)" % exc)

        cls.CassetteSideB = RewindingCassetteSideB
        cls.CassetteSideA = RewindingCassetteSideA
        super().setUpClass()

    def test_reverse_one_to_one_not_selected(self):
        """myobject.myrelation is a OneToOneField which has not been fetched"""
        self.CassetteSideA.objects.create(
            title="Side A!", side_b=self.CassetteSideB.objects.create(title="Side B!")
        )
        with self.assertNumQueries(1):
            (side_b,) = self.CassetteSideB.objects.all()
            with self.assertNumQueries(0):
                self.assertEqual(side_b.title, "Side B!")
                side_b.pk
                side_b.title
                with self.assertRaisesMessage(
                    MissingRelationField,
                    "Access to `RewindingCassetteSideB.woo_side_a` was prevented.\n"
                    "To fetch the `RewindingCassetteSideA` object, add `prefetch_related('woo_side_a')` or `select_related('woo_side_a')` to the query where `RewindingCassetteSideB` objects are selected.",
                ):
                    side_b.woo_side_a

    def test_reverse_one_to_one_prefetch_related(self):
        """myobject.myrelation is the other end of a OneToOneField which has been prefetched"""
        self.CassetteSideA.objects.create(
            title="Side A!", side_b=self.CassetteSideB.objects.create(title="Side B!")
        )

        with self.assertNumQueries(2):
            (side_b,) = self.CassetteSideB.objects.prefetch_related("woo_side_a").all()
        with self.assertNumQueries(0):
            self.assertEqual(side_b.woo_side_a.title, "Side A!")
            self.assertEqual(side_b.title, "Side B!")
            side_b.pk
            side_b.woo_side_a.pk

    def test_reverse_one_to_one_select_relatd(self):
        """myobject.myrelation is the other end of a OneToOneField which has been joined"""
        self.CassetteSideA.objects.create(
            title="Side A!", side_b=self.CassetteSideB.objects.create(title="Side B!")
        )

        with self.assertNumQueries(1):
            (side_b,) = self.CassetteSideB.objects.select_related("woo_side_a").all()
        with self.assertNumQueries(0):
            self.assertEqual(side_b.woo_side_a.title, "Side A!")
            self.assertEqual(side_b.title, "Side B!")
            side_b.pk
            side_b.woo_side_a.pk

    def test_objects_create(self):
        """
        If you have the remote side of a onetoone, and the related object (here cassette side A)
        is filled in after the fact, whether it's OK or raises is dependent.

        Or do I just wish it to always raise if given by ID? IDK.
        """
        side_b1 = self.CassetteSideB.objects.create(title="Side B!")
        self.CassetteSideA.objects.create(title="Side A!", side_b=side_b1)
        # Already cached, no query
        with self.assertNumQueries(0):
            self.assertEqual(side_b1.woo_side_a.title, "Side A!")

        side_b2 = self.CassetteSideB.objects.create(title="Side B!")
        self.CassetteSideA.objects.create(
            title="Side A!",
            side_b_id=side_b2.pk,
        )
        # Not cached, set via <field>_id, needs fetching
        with self.assertNumQueries(1):
            self.assertEqual(side_b2.woo_side_a.title, "Side A!")

    def test_model_create(self):
        """
        If you have the remote side of a onetoone, and the related object (here cassette side A)
        is filled in after the fact, whether it's OK or raises is dependent.

        Or do I just wish it to always raise if given by ID? IDK.
        """
        side_b1 = self.CassetteSideB(title="Side B!")
        side_b1.save()
        self.CassetteSideA.objects.create(title="Side A!", side_b=side_b1)
        # Already cached, no query
        with self.assertNumQueries(0):
            self.assertEqual(side_b1.woo_side_a.title, "Side A!")

        side_b2 = self.CassetteSideB(title="Side B!")
        side_b2.save()
        self.CassetteSideA.objects.create(
            title="Side A!",
            side_b_id=side_b2.pk,
        )
        # Not cached, set via <field>_id, needs fetching
        with self.assertNumQueries(1):
            self.assertEqual(side_b2.woo_side_a.title, "Side A!")


class OneToOneEscapeHatchDescriptorTestCase(TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        class ModelB(models.Model):
            title = models.CharField(max_length=100)

        class ModelA(models.Model):
            title = models.CharField(max_length=100)
            b = models.OneToOneField(
                ModelB,
                on_delete=models.CASCADE,
            )

        try:
            with connection.schema_editor() as editor:
                editor.create_model(ModelB)
                editor.create_model(ModelA)
        except DatabaseError as exc:
            raise cls.failureException("Unable to create the table (%s)" % exc)

        cls.ModelB = ModelB
        cls.ModelA = ModelA
        super().setUpClass()

    def test_forward_one_to_one_not_selected(self):
        """myobject.myrelation is a OneToOneField which has not been fetched"""
        self.ModelA.objects.create(title="Side A!", b=self.ModelB.objects.create(title="Side B!"))
        with self.assertNumQueries(1):
            (side_a,) = self.ModelA.objects.all()
        with self.assertNumQueries(0):
            self.assertEqual(side_a.title, "Side A!")
            side_a.pk
            side_a.b_id
        with self.assertNumQueries(1):
            side_a._shoutyorm_allow_b = True
            side_a.b

    def test_reverse_one_to_one_not_selected(self):
        """myobject.myrelation is a OneToOneField which has not been fetched"""
        self.ModelA.objects.create(title="Side A!", b=self.ModelB.objects.create(title="Side B!"))
        with self.assertNumQueries(1):
            (side_b,) = self.ModelB.objects.all()
        with self.assertNumQueries(0):
            self.assertEqual(side_b.title, "Side B!")
            side_b.pk
            side_b.title
        with self.assertNumQueries(1):
            side_b._shoutyorm_allow_modela = True
            side_b.modela
