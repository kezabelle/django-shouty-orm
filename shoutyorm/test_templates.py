from __future__ import annotations
import django
from django.conf import settings
from django.db import models, connection, DatabaseError
from django.test import TestCase
from django.template import Template, Context
from shoutyorm import MissingLocalField
from shoutyorm.errors import (
    MissingRelationField,
    MissingReverseRelationField,
)

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


class TemplateTestCase(TestCase):  # type: ignore
    """
    Got to check that the exceptions
    """

    @classmethod
    def setUpClass(cls) -> None:
        # class RelatedGroup(models.Model):
        #     title = models.CharField(max_length=100)

        class FakeTemplateUser(models.Model):
            first_name = models.CharField(max_length=100)
            last_name = models.CharField(max_length=100)
            username = models.CharField(max_length=100)
            email = models.CharField(max_length=100)

        class FakeTemplateContentType(models.Model):
            title = models.CharField(max_length=100)

        class FakeTemplatePermission(models.Model):
            title = models.CharField(max_length=100)
            codename = models.CharField(max_length=100)
            content_type = models.ForeignKey(FakeTemplateContentType, on_delete=models.CASCADE)

        try:
            with connection.schema_editor() as editor:
                editor.create_model(FakeTemplateContentType)
                editor.create_model(FakeTemplatePermission)
                editor.create_model(FakeTemplateUser)
        except DatabaseError as exc:
            raise cls.failureException("Unable to create the table (%s)" % exc)

        cls.ContentType = FakeTemplateContentType
        cls.Permission = FakeTemplatePermission
        cls.User = FakeTemplateUser
        super().setUpClass()

    def test_local(self) -> None:
        u = self.User.objects.create(
            first_name="test",
            last_name="test",
            username="testu",
            email="test@test.com",
        )
        u = self.User.objects.only("pk", "first_name").get(pk=u.pk)
        tmpl = Template(
            """
        {{ u.pk }}, {{ u.first_name }}, {{ u.date_joined }}, {{ u.last_name }}
        """
        )
        with self.assertNumQueries(0), self.assertRaisesMessage(
            MissingLocalField,
            "Access to `FakeTemplateUser.last_name` was prevented.\n"
            "Add `last_name` to `only('first_name', 'id')` or remove `last_name` from `defer('email', 'last_name', 'username')` where `FakeTemplateUser` objects are selected`",
        ):
            tmpl.render(
                Context(
                    {
                        "u": u,
                    }
                )
            )

    def test_local_foreignkey(self) -> None:
        created = self.Permission.objects.create(
            title="test fake permission",
            codename="fake",
            content_type=self.ContentType.objects.create(title="fake ct"),
        )
        p = self.Permission.objects.get(pk=created.pk)
        tmpl = Template(
            """
        {{ p.pk }}, {{ p.codename }}, {{ p.content_type_id }}, {{ p.content_type.pk }}
        """
        )
        with self.assertRaisesMessage(
            MissingRelationField,
            "Access to `FakeTemplatePermission.content_type` was prevented.\n"
            "If you only need access to the column identifier, use `FakeTemplatePermission.content_type_id` instead.\n"
            "To fetch the `FakeTemplateContentType` object, add `prefetch_related('content_type')` or `select_related('content_type')` to the query where `FakeTemplatePermission` objects are selected.",
        ):
            tmpl.render(
                Context(
                    {
                        "p": p,
                    }
                )
            )

    def test_reverse_foreignkey(self) -> None:
        self.ContentType.objects.create(title="fake ct")
        (ct,) = self.ContentType.objects.all()
        tmpl = Template(
            """
        {{ ct.pk }}, {{ ct.title }}, {% for p in ct.faketemplatepermission_set.all %}{{ p }}{% endfor %}
        """
        )
        with self.assertNumQueries(0), self.assertRaisesMessage(
            MissingReverseRelationField,
            "Access to `FakeTemplateContentType.faketemplatepermission_set.all()` was prevented.\n"
            "To fetch the `FakeTemplatePermission` objects, add `prefetch_related('faketemplatepermission_set')` to the query where `FakeTemplateContentType` objects are selected.",
        ):
            tmpl.render(
                Context(
                    {
                        "ct": ct,
                    }
                )
            )
