from django.db import models, connection, DatabaseError
from django.test import TestCase
from shoutyorm.errors import MissingForeignKeyField, MissingReverseRelationField

from django import VERSION as DJANGO_VERSION


class ForwardForeignKeyDescriptorTestCase(TestCase):
    @classmethod
    def setUpClass(cls):
        # type: () -> None
        class Role(models.Model):
            title = models.CharField(max_length=100)

        class User(models.Model):
            name = models.CharField(max_length=100)
            role = models.ForeignKey(
                Role, on_delete=models.CASCADE, db_column="role_reference", related_name="users"
            )

        try:
            with connection.schema_editor() as editor:
                editor.create_model(Role)
                editor.create_model(User)
        except DatabaseError as exc:
            raise cls.failureException("Unable to create the table (%s)" % exc)

        cls.User = User
        cls.Role = Role
        super().setUpClass()

    def test_foreignkey_not_selected(self):
        """myobject.myrelation is a ForeignKey which has not been fetched"""

        self.User.objects.create(
            name="Bert", role=self.Role.objects.create(title="Not quite admin")
        )
        with self.assertNumQueries(1):
            (user,) = self.User.objects.all()
            with self.assertNumQueries(0):
                self.assertEqual(user.name, "Bert")
                user.pk
                user.role_id
                with self.assertRaisesMessage(
                    MissingForeignKeyField,
                    "Access to `User.role` was prevented.\n"
                    "If you only need access to the column identifier, use `User.role_id` instead.\n"
                    "To fetch the `Role` object, add `prefetch_related('role')` or `select_related('role')` to the query where `User` objects are selected.",
                ):
                    user.role

    def test_foreignkey_prefetch_related(self):
        """myobject.myrelation is a ForeignKey which has not been prefetched"""

        self.User.objects.create(
            name="Bert", role=self.Role.objects.create(title="Not quite admin")
        )
        with self.assertNumQueries(2):
            (user,) = self.User.objects.prefetch_related("role").all()
            self.assertEqual(user.role.title, "Not quite admin")

    def test_foreignkey_select_related(self):
        """myobject.myrelation is a ForeignKey which has been joined"""

        self.User.objects.create(
            name="Bert", role=self.Role.objects.create(title="Not quite admin")
        )
        with self.assertNumQueries(1):
            (user,) = self.User.objects.select_related("role").all()
            self.assertEqual(user.role.title, "Not quite admin")

    def test_objects_create(self):
        """
        Creating with .create(<field>_id) and then using <field> later is OK

        Required patching Model.save_base to track whether an instance was freshly
        minted or not.
        """
        user = self.User.objects.create(name="user!", role=self.Role.objects.create(title="admin"))
        # Already cached, no query
        with self.assertNumQueries(0):
            self.assertEqual(user.role.title, "admin")

        role2 = self.Role.objects.create(title="admin 2")
        user2 = self.User.objects.create(
            name="user 2!",
            role_id=role2.pk,
        )
        # Not cached, set via <field>_id, needs fetching
        with self.assertNumQueries(1):
            self.assertEqual(user2.role.title, "admin 2")

    def test_model_create(self):
        """
        Creating with Model(<field>_id).save() and then using <field> later is OK

        Required patching Model.save_base to track whether an instance was freshly
        minted or not.
        """
        user = self.User(name="user!", role=self.Role.objects.create(title="admin"))
        user.save()
        # Already cached, no query
        with self.assertNumQueries(0):
            self.assertEqual(user.role.title, "admin")

        role2 = self.Role.objects.create(title="admin 2")
        user2 = self.User(
            name="user 2!",
            role_id=role2.pk,
        )
        user2.save()
        # Not cached, set via <field>_id, needs fetching
        with self.assertNumQueries(1):
            self.assertEqual(user2.role.title, "admin 2")


class ReverseForeignKeyDescriptorTestCase(TestCase):
    @classmethod
    def setUpClass(cls):
        # type: () -> None
        class ReversableRole(models.Model):
            title = models.CharField(max_length=100)

        class OtherThing(models.Model):
            role = models.ForeignKey(ReversableRole, on_delete=models.SET_NULL, null=True)

        class ReversableUser(models.Model):
            name = models.CharField(max_length=100)
            role = models.ForeignKey(
                ReversableRole,
                on_delete=models.CASCADE,
                db_column="role_reference",
                related_name="users",
                null=True,
            )

        try:
            with connection.schema_editor() as editor:
                editor.create_model(ReversableRole)
                editor.create_model(OtherThing)
                editor.create_model(ReversableUser)
        except DatabaseError as exc:
            raise cls.failureException("Unable to create the table (%s)" % exc)

        cls.User = ReversableUser
        cls.Role = ReversableRole
        super().setUpClass()

    def test_accessing_other_side_of_foreignkey_when_not_prefetched(self):
        # type: () -> None
        self.User.objects.create(
            name="Bert", role=self.Role.objects.create(title="Not quite admin")
        )
        with self.assertNumQueries(1):
            (role,) = self.Role.objects.all()
        with self.assertNumQueries(0):
            role.pk
            role.title
            with self.assertRaisesMessage(
                MissingReverseRelationField,
                "Access to `ReversableRole.users.all()` was prevented.\n"
                "To fetch the `ReversableUser` objects, add `prefetch_related('users')` to the query where `ReversableRole` objects are selected.",
            ):
                role.users.all()

    def test_accessing_other_side_of_foreignkey_when_not_part_of_prefetched(self):
        self.User.objects.create(
            name="Bert", role=self.Role.objects.create(title="Not quite admin")
        )
        with self.assertNumQueries(2):
            (role,) = self.Role.objects.prefetch_related("otherthing_set").all()
        with self.assertNumQueries(0):
            role.pk
            role.title
            with self.assertRaisesMessage(
                MissingReverseRelationField,
                "Access to `ReversableRole.users.all()` was prevented.\n"
                "To fetch the `ReversableUser` objects, add 'users' to the existing `prefetch_related('otherthing_set')` part of the query where `ReversableRole` objects are selected.",
            ):
                role.users.all()

    def test_adding_to_related_set(self):
        """Modifying the contents of the related manager should be fine"""
        with self.assertNumQueries(2):
            role = self.Role.objects.create(title="Not quite admin")
            user = self.User.objects.create(name="Bert", role=role)

        with self.assertNumQueries(1):
            role.users.clear()

        q = 1
        if DJANGO_VERSION[0:2] < (3, 0):
            q = 2
        with self.assertNumQueries(q):
            role.users.add(user)

        with self.assertNumQueries(1):
            role.users.remove(user)

        with self.assertNumQueries(2):
            self.assertIsNone(role.users.first())
            self.assertIsNone(role.users.last())

        q = 2
        if DJANGO_VERSION[0:2] < (3, 0):
            q = 3
        with self.assertNumQueries(q):
            role.users.set((user,))

        # Not sure why both of these are 0 queries? Neither uses the _result_cache
        # AFAIK, so surely they should always do one?
        with self.assertNumQueries(0):
            role.users.exclude(name__icontains="test")
        with self.assertNumQueries(0):
            role.users.filter(name__icontains="test")

        # Especially as the following all ... do a query?
        with self.assertNumQueries(1):
            self.assertEqual(role.users.count(), 1)
        with self.assertNumQueries(1):
            self.assertTrue(role.users.exists())
        with self.assertNumQueries(1):
            self.assertIsNotNone(role.users.first())
        with self.assertNumQueries(1):
            self.assertIsNotNone(role.users.last())
