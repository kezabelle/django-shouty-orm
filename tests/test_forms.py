import django
from django.conf import settings
from django.db import models, connection, DatabaseError
from django.test import TestCase, override_settings
from django import forms
from shoutyorm.errors import MissingLocalField, MissingManyToManyField

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


class FormTestCase(TestCase):  # type: ignore
    """
    Auto generated modelforms are super common, so let's
    demonstrate how all the behaviours link together
    to cause issues or corrections.
    """

    @classmethod
    def setUpClass(cls):
        # type: () -> None
        class FakeContentType(models.Model):
            title = models.CharField(max_length=100)

            class Meta:
                app_label = "shoutyorm"

        class FakePermission(models.Model):
            title = models.CharField(max_length=100)
            related_thing = models.ForeignKey(FakeContentType, on_delete=models.CASCADE)

            class Meta:
                app_label = "shoutyorm"

        try:
            with connection.schema_editor() as editor:
                editor.create_model(FakeContentType)
                editor.create_model(FakePermission)
        except DatabaseError as exc:
            raise cls.failureException("Unable to create the table (%s)" % exc)

        cls.FakePermission = FakePermission
        cls.FakeContentType = FakeContentType
        super().setUpClass()

    def test_foreignkey_in_form(self):
        # type: () -> None
        """
        Prove that the patch doesn't affect modelform generation.
        """

        class PermissionForm(forms.ModelForm):  # type: ignore
            class Meta:
                model = self.FakePermission
                fields = "__all__"

        obj = self.FakePermission.objects.create(
            title="fake permission",
            related_thing=self.FakeContentType.objects.create(title="fake content-type"),
        )

        with self.assertNumQueries(2):
            form = PermissionForm(
                data={
                    "title": obj.title,
                    "related_thing": obj.related_thing_id,
                },
                instance=obj,
            )
            form.is_valid()
            self.assertEqual(form.errors, {})
        with self.assertNumQueries(1):
            form.save()

    def test_local_in_form(self):
        # type: () -> None
        instance = self.FakePermission.objects.create(
            title="fake permission",
            related_thing=self.FakeContentType.objects.create(title="fake content-type"),
        )

        class UserForm(forms.ModelForm):  # type: ignore
            class Meta:
                model = instance
                fields = ("title",)

        with self.assertNumQueries(1):
            obj = self.FakePermission.objects.only("pk").get(pk=instance.pk)
            with self.assertRaisesMessage(
                MissingLocalField,
                "Access to `FakePermission.title` was prevented.\n"
                "Add `title` to `only('id')` or remove `title` from `defer('related_thing_id', 'title')` where `FakePermission` objects are selected`",
            ):
                UserForm(data=None, instance=obj)
