import django
from django.conf import settings
from django.db import models, connection, DatabaseError
from django.test import TestCase
from shoutyorm import MissingRelationField

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
        class B(models.Model):
            title = models.CharField(max_length=100)

        class T(models.Model):
            title = models.CharField(max_length=100)
            b = models.OneToOneField(B, on_delete=models.CASCADE)

        class C(models.Model):
            title = models.CharField(max_length=100)
            t = models.ForeignKey(T, on_delete=models.CASCADE)

        try:
            with connection.schema_editor() as editor:
                editor.create_model(B)
                editor.create_model(T)
                editor.create_model(C)
        except DatabaseError as exc:
            raise cls.failureException("Unable to create the table (%s)" % exc)

        cls.B = B
        cls.T = T
        cls.C = C
        super().setUpClass()

    def test_realworld1(self):
        """
        This is a simplified example from a real world project where an exception
        has been raised, and how it needs to be handled.
        """
        existing_b = self.B.objects.create(title="B01")
        existing_t = self.T.objects.create(title="T01", b_id=existing_b.pk)
        existing_c = self.C.objects.create(title="C01", t_id=existing_t.pk)

        t = self.T.objects.get(pk=existing_t.pk)
        c = self.C.objects.get(pk=existing_c.pk)
        with self.assertNumQueries(0), self.assertRaises(MissingRelationField):
            c.t.b
