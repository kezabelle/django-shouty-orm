from django.db import models, connection, DatabaseError
from django.test import TestCase
from shoutyorm.errors import MissingForeignKeyField, MissingReverseRelationField


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
