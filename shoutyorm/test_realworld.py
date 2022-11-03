import django
from django.conf import settings
from django.db import models, connection, DatabaseError
from django.test import TestCase

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


class RealworldCreationTestCase(TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        class Rectangle(models.Model):
            title = models.CharField(max_length=100)

        class Circle(models.Model):
            title = models.CharField(max_length=100)
            rect = models.OneToOneField(Rectangle, on_delete=models.CASCADE)

        class Box(models.Model):
            title = models.CharField(max_length=100)
            related = models.ForeignKey(Rectangle, on_delete=models.CASCADE)

        try:
            with connection.schema_editor() as editor:
                editor.create_model(Rectangle)
                editor.create_model(Circle)
                editor.create_model(Box)
        except DatabaseError as exc:
            raise cls.failureException("Unable to create the table (%s)" % exc)

        cls.Box = Box
        cls.Rectangle = Rectangle
        cls.Circle = Circle
        super().setUpClass()

    def test_creation_of_item(self):
        existing_rectangle = self.Rectangle.objects.create(title="existing rectangle")
        existing_circle = self.Circle.objects.create(
            title="existing circle", rect=existing_rectangle
        )
        with self.subTest("plain create()"), self.assertNumQueries(1):
            new_box = self.Box.objects.create(title="new box", related=existing_rectangle)

        with self.subTest("get_or_create() with select_related()"), self.assertNumQueries(1):
            new_box2, created = self.Box.objects.select_related(
                "related", "related__circle"
            ).get_or_create(title="new box", defaults={"related": existing_rectangle})
            self.assertFalse(created)
            new_box2.related.circle

        with self.subTest("get_or_create() without select_related()"), self.assertNumQueries(4):
            new_box3, created = self.Box.objects.get_or_create(
                title="new box3", defaults={"related": existing_rectangle}
            )
            self.assertTrue(created)
            new_box3.related.circle

        with self.subTest("plain create() with select_related()"), self.assertNumQueries(1):
            new_box4 = self.Box.objects.select_related("related", "related__circle").create(
                title="new box", related=existing_rectangle
            )
            new_box4.related.circle
