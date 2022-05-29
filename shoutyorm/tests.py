import os

from django.test import TestCase
from django.db.models import Prefetch
from django.contrib.auth.models import User, Group, Permission
from django.contrib.contenttypes.models import ContentType
from django import forms
from django.template import Template, Context
from django import VERSION as DJANGO_VERSION


# noinspection PyStatementEffect
from shoutyorm.errors import MissingForeignKeyField


class MostlyM2MPrefetchRelatedTestCase(TestCase):  # type: ignore
    def setUp(self):
        # type: () -> None
        # Have to import the exceptions here to avoid __main__.ExceptionCls
        # not being the same as shoutyorm.ExceptionCls, otherwise the test
        # cases have to be outside the __main__ block.
        # noinspection PyUnresolvedReferences
        from shoutyorm import MissingRelationField

        self.MissingRelationField = MissingRelationField
        self.user = User.objects.create()

    def test_accessing_nonprefetched_m2m_works_when_trying_to_add(self):
        # type: () -> None
        """
        There are certain methods you want to access on an m2m which disregard
        the prefetch cache and should specifically not error.
        """
        with self.assertNumQueries(1):
            i = User.objects.get(pk=self.user.pk)
        q = 2
        if DJANGO_VERSION[0:2] < (3, 0):
            q = 3
        with self.assertNumQueries(q):
            i.groups.add(Group.objects.create(name="test"))

    def test_accessing_nonprefetched_m2m_fails_when_accessing_all(self):
        # type: () -> None
        """
        Normal use case - failure to prefetch should error loudly
        """
        with self.assertNumQueries(1):
            i = User.objects.get(pk=self.user.pk)
            with self.assertRaisesMessage(
                self.MissingRelationField,
                "Access to 'groups' ManyToMany manager attribute on User was prevented because it was not selected.\nProbably missing from prefetch_related()",
            ):
                i.groups.all()
            with self.assertRaisesMessage(
                self.MissingRelationField,
                "Access to 'user_permissions' ManyToMany manager attribute on User was prevented because it was not selected.\nProbably missing from prefetch_related()",
            ):
                i.user_permissions.all()

    def test_accessing_nonprefetched_nested_relations_fails(self):
        # type: () -> None
        """
        It's OK to access groups because we prefetched it, but accessing
        the group's permissions is NOT ok.
        """
        self.user.groups.add(Group.objects.create(name="test"))
        with self.assertNumQueries(2):
            i = User.objects.prefetch_related("groups").get(pk=self.user.pk)
        with self.assertNumQueries(0):
            tuple(i.groups.all())
            with self.assertRaisesMessage(
                self.MissingRelationField,
                "Access to 'permissions' ManyToMany manager attribute on Group was prevented because it was not selected.\nProbably missing from prefetch_related()",
            ):
                i.groups.all()[0].permissions.all()

    def test_accessing_prefetched_nested_relations_is_ok(self):
        # type: () -> None
        """
        If we've pre-selected groups and the permissions on those groups,
        it should be fine to access any permissions in any index of the
        groups queryset.
        """
        self.user.groups.add(Group.objects.create(name="test"))
        with self.assertNumQueries(3):
            i = User.objects.prefetch_related("groups", "groups__permissions").get(pk=self.user.pk)
        with self.assertNumQueries(0):
            tuple(i.groups.all())
            tuple(i.groups.all()[0].permissions.all())
            with self.assertRaisesMessage(
                self.MissingRelationField,
                "Access to 'user_permissions' ManyToMany manager attribute on User was prevented because it was not selected.\nProbably missing from prefetch_related()",
            ):
                tuple(i.user_permissions.all())

    def test_accessing_multiple_prefetched_nonnested_relations_is_ok(self):
        # type: () -> None
        """
        Accessing more than 1 prefetch at the same level is OK.
        This was part of the difficulty in figuring this out, because by the
        time you get to the second prefetch selection you need to NOT prevent
        access to the queryset until ALL prefetching looks to have finished.
        """
        self.user.groups.add(Group.objects.create(name="test"))
        with self.assertNumQueries(3):
            i = User.objects.prefetch_related("groups", "user_permissions").get(pk=self.user.pk)
        with self.assertNumQueries(0):
            tuple(i.groups.all())
            tuple(i.user_permissions.all())

    def test_accessing_relations_involving_prefetch_objects_is_ok(self):
        # type: () -> None
        """
        Make sure using a Prefetch object doesn't throw a spanner in the works.
        """
        self.user.groups.add(Group.objects.create(name="test"))
        with self.assertNumQueries(4):
            i = User.objects.prefetch_related(
                Prefetch("groups", Group.objects.all()),
                "groups__permissions",
                "user_permissions",
            ).get(pk=self.user.pk)
        with self.assertNumQueries(0):
            tuple(i.groups.all())
            tuple(i.user_permissions.all())
            tuple(i.groups.all()[0].permissions.all())

    def test_accessing_relations_involving_prefetch_objects_is_ok2(self):
        # type: () -> None
        """
        Make sure using a Prefetch object doesn't throw a spanner in the works.
        """
        self.user.groups.add(Group.objects.create(name="test"))
        with self.assertNumQueries(4):
            i = User.objects.prefetch_related(
                "groups",
                Prefetch("groups__permissions", Permission.objects.all()),
                "user_permissions",
            ).get(pk=self.user.pk)
        with self.assertNumQueries(0):
            tuple(i.groups.all())
            tuple(i.user_permissions.all())
            tuple(i.groups.all()[0].permissions.all())


class PrefetchReverseRelatedTestCase(TestCase):  # type: ignore
    """
    Demonstrate how
    - new_manytomany_descriptor_get
    - new_modeliterable_iter
    interact with things.
    """

    def setUp(self):
        # type: () -> None
        # Have to import the exceptions here to avoid __main__.ExceptionCls
        # not being the same as shoutyorm.ExceptionCls, otherwise the test
        # cases have to be outside the __main__ block.
        # noinspection PyUnresolvedReferences
        from shoutyorm import MissingRelationField

        self.MissingRelationField = MissingRelationField
        self.group = Group.objects.create()

    def test_accessing_nonprefetched_m2m_works_when_trying_to_add(self):
        # type: () -> None
        """
        There are certain methods you want to access on an m2m which disregard
        the prefetch cache and should specifically not error.
        """
        with self.assertNumQueries(1):
            i = Group.objects.get(pk=self.group.pk)
        q = 2
        if DJANGO_VERSION[0:2] < (3, 0):
            q = 3
        with self.assertNumQueries(q):
            i.user_set.add(User.objects.create())

    def test_accessing_nonprefetched_m2m_fails_when_accessing_all(self):
        # type: () -> None
        """
        Normal use case - failure to prefetch should error loudly
        """
        with self.assertNumQueries(1):
            i = Group.objects.get(pk=self.group.pk)
            with self.assertRaisesMessage(
                self.MissingRelationField,
                "Access to 'user_set' ManyToMany manager attribute on Group was prevented because it was not selected.\nProbably missing from prefetch_related()",
            ):
                i.user_set.all()

    def test_accessing_nonprefetched_nested_relations_fails(self):
        # type: () -> None
        """
        It's OK to access groups because we prefetched it, but accessing
        the group's permissions is NOT ok.
        """
        self.group.user_set.add(User.objects.create())
        with self.assertNumQueries(2):
            i = Group.objects.prefetch_related("user_set").get(pk=self.group.pk)
        with self.assertNumQueries(0):
            tuple(i.user_set.all())
            with self.assertRaisesMessage(
                self.MissingRelationField,
                "Access to 'user_permissions' ManyToMany manager attribute on User was prevented because it was not selected.\nProbably missing from prefetch_related()",
            ):
                i.user_set.all()[0].user_permissions.all()

    def test_accessing_prefetched_nested_relations_is_ok(self):
        # type: () -> None
        """
        If we've pre-selected groups and the permissions on those groups,
        it should be fine to access any permissions in any index of the
        groups queryset.
        """
        self.group.user_set.add(User.objects.create())
        with self.assertNumQueries(3):
            i = Group.objects.prefetch_related("user_set", "user_set__user_permissions").get(
                pk=self.group.pk
            )
        with self.assertNumQueries(0):
            tuple(i.user_set.all())
            tuple(i.user_set.all()[0].user_permissions.all())

    def test_accessing_multiple_prefetched_nonnested_relations_is_ok(self):
        # type: () -> None
        """
        Accessing more than 1 prefetch at the same level is OK.
        This was part of the difficulty in figuring this out, because by the
        time you get to the second prefetch selection you need to NOT prevent
        access to the queryset until ALL prefetching looks to have finished.
        """
        self.group.user_set.add(User.objects.create())
        with self.assertNumQueries(3):
            i = Group.objects.prefetch_related("user_set", "permissions").get(pk=self.group.pk)
        with self.assertNumQueries(0):
            tuple(i.user_set.all())
            tuple(i.permissions.all())

    def test_accessing_relations_involving_prefetch_objects_is_ok(self):
        # type: () -> None
        """
        Make sure using a Prefetch object doesn't throw a spanner in the works.
        """
        self.group.user_set.add(User.objects.create())
        with self.assertNumQueries(3):
            i = Group.objects.prefetch_related(
                Prefetch("user_set", User.objects.all()),
                "user_set__user_permissions",
            ).get(pk=self.group.pk)
        with self.assertNumQueries(0):
            tuple(i.user_set.all())
            tuple(i.user_set.all()[0].user_permissions.all())

    def test_accessing_relations_involving_prefetch_objects_is_ok2(self):
        # type: () -> None
        """
        Make sure using a Prefetch object doesn't throw a spanner in the works.
        """
        self.group.user_set.add(User.objects.create())
        with self.assertNumQueries(3):
            i = Group.objects.prefetch_related(
                "user_set",
                Prefetch("user_set__user_permissions", Permission.objects.all()),
            ).get(pk=self.group.pk)
        with self.assertNumQueries(0):
            tuple(i.user_set.all())
            tuple(i.user_set.all()[0].user_permissions.all())


class FormTestCase(TestCase):  # type: ignore
    """
    Auto generated modelforms are super common, so let's
    demonstrate how all the behaviours link together
    to cause issues or corrections.
    """

    def setUp(self):
        # type: () -> None
        # Have to import the exceptions here to avoid __main__.ExceptionCls
        # not being the same as shoutyorm.ExceptionCls, otherwise the test
        # cases have to be outside the __main__ block.
        # noinspection PyUnresolvedReferences
        from shoutyorm import MissingRelationField, MissingLocalField

        self.MissingLocalField = MissingLocalField
        self.MissingRelationField = MissingRelationField

    def test_foreignkey_in_form(self):
        # type: () -> None
        """
        Prove that the patch doesn't affect modelform generation.
        """

        class PermissionForm(forms.ModelForm):  # type: ignore
            class Meta:
                model = Permission
                fields = "__all__"

        with self.assertNumQueries(1):
            obj = Permission.objects.all()[0]  # type: Permission
        with self.assertNumQueries(3):
            form = PermissionForm(
                data={
                    "name": obj.name,
                    "content_type": obj.content_type_id,
                    "codename": obj.codename,
                },
                instance=obj,
            )
            form.is_valid()
            self.assertEqual(form.errors, {})
        with self.assertNumQueries(1):
            form.save()

    def test_local_in_form(self):
        # type: () -> None
        instance = User.objects.create()

        class UserForm(forms.ModelForm):  # type: ignore
            class Meta:
                model = User
                fields = ("first_name", "password")

        with self.assertNumQueries(1):
            obj = User.objects.only("pk", "first_name").get(pk=instance.pk)
            with self.assertRaisesMessage(
                self.MissingLocalField,
                "Access to 'password' attribute on User was prevented because it was not selected.\nProbably defer() or only() were used.",
            ):
                UserForm(data=None, instance=obj)

    def test_manytomany_in_form_is_ok_if_prefetched(self):
        # type: () -> None
        """
        Prove that modelform generation IS effected on a model's local
        manytomany field.
        """
        instance = User.objects.create()

        class UserForm(forms.ModelForm):  # type: ignore
            class Meta:
                model = User
                fields = "__all__"

        with self.assertNumQueries(3):
            obj = User.objects.prefetch_related("groups", "user_permissions").get(pk=instance.pk)
        with self.assertNumQueries(0):
            UserForm(data=None, instance=obj)

    def test_manytomany_in_form_fails_if_not_prefetched(self):
        # type: () -> None
        """
        Prove that modelform generation IS effected on a model's local
        manytomany field.
        """
        instance = User.objects.create()

        class UserForm(forms.ModelForm):  # type: ignore
            class Meta:
                model = User
                fields = "__all__"

        with self.assertNumQueries(1):
            obj = User.objects.get(pk=instance.pk)
            with self.assertRaisesMessage(
                self.MissingRelationField,
                "Access to 'groups' ManyToMany manager attribute on User was prevented because it was not selected.\nProbably missing from prefetch_related()",
            ):
                UserForm(data=None, instance=obj)


class TemplateTestCase(TestCase):  # type: ignore
    """
    Got to check that the exceptions
    """

    def setUp(self):
        # type: () -> None
        from shoutyorm import MissingLocalField, MissingRelationField

        self.MissingLocalField = MissingLocalField
        self.MissingRelationField = MissingRelationField

    def test_local(self):
        # type: () -> None
        u = User.objects.create(
            first_name="test",
            last_name="test",
            username="testu",
            email="test@test.com",
        )
        u = User.objects.only("pk", "first_name", "date_joined").get(pk=u.pk)
        tmpl = Template(
            """
        {{ u.pk }}, {{ u.first_name }}, {{ u.date_joined }}, {{ u.last_name }}
        """
        )
        with self.assertRaisesMessage(
            self.MissingLocalField,
            "Access to 'last_name' attribute on User was prevented because it was not selected.\nProbably defer() or only() were used.",
        ):
            tmpl.render(
                Context(
                    {
                        "u": u,
                    }
                )
            )

    def test_local_foreignkey(self):
        # type: () -> None
        p = Permission.objects.all()[0]
        tmpl = Template(
            """
        {{ p.pk }}, {{ p.codename }}, {{ p.content_type_id }}, {{ p.content_type.pk }}
        """
        )
        with self.assertRaisesMessage(
            MissingForeignKeyField,
            "Access to `Permission.content_type` was prevented.\n"
            "If you only need access to the column identifier, use `Permission.content_type_id` instead.\n"
            "To fetch the `ContentType` object, add `prefetch_related('content_type')` or `select_related('content_type')` to the query where `Permission` objects are selected.",
        ):
            tmpl.render(
                Context(
                    {
                        "p": p,
                    }
                )
            )

    def test_reverse_foreignkey(self):
        # type: () -> None
        ct = ContentType.objects.all()[0]
        tmpl = Template(
            """
        {{ ct.pk }}, {{ ct.app_label }}, {{ ct.model }}, {% for p in ct.permission_set.all %}{{ p }}{% endfor %}
        """
        )
        with self.assertRaisesMessage(
            self.MissingRelationField,
            "Access to reverse manager 'permission_set' on ContentType was prevented because it was not selected.\nProbably missing from prefetch_related()",
        ):
            tmpl.render(
                Context(
                    {
                        "ct": ct,
                    }
                )
            )

    def test_local_m2m(self):
        # type: () -> None
        u = User.objects.create(
            first_name="test",
            last_name="test",
            username="testu",
            email="test@test.com",
        )
        tmpl = Template(
            """
        {{ u.pk }}, {{ u.username }}, {% for g in u.groups.all %}{{ g }}{% endfor %}
        """
        )
        with self.assertRaisesMessage(
            self.MissingRelationField,
            "Access to 'groups' ManyToMany manager attribute on User was prevented because it was not selected.\nProbably missing from prefetch_related()",
        ):
            tmpl.render(
                Context(
                    {
                        "u": u,
                    }
                )
            )

    def test_reverse_m2m(self):
        # type: () -> None
        g = Group.objects.create()
        tmpl = Template(
            """
        {{ g.pk }}, {% for u in g.user_set.all %}{{ u }}{% endfor %}
        """
        )
        with self.assertRaisesMessage(
            self.MissingRelationField,
            "Access to 'user_set' ManyToMany manager attribute on Group was prevented because it was not selected.\nProbably missing from prefetch_related()",
        ):
            tmpl.render(
                Context(
                    {
                        "g": g,
                    }
                )
            )


class MyPyTestCase(TestCase):  # type: ignore
    def test_for_types(self):
        # type: () -> None
        try:
            from mypy import api as mypy
        except ImportError:
            return
        else:
            here = os.path.dirname(os.path.abspath(__file__))
            report, errors, exit_code = mypy.run(["--strict", "--ignore-missing-imports", here])
            if errors:
                self.fail(errors)
            elif exit_code > 0:
                self.fail(report)
