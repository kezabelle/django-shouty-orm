from django.db import models, connection, DatabaseError
from django.test import TestCase
from shoutyorm.errors import MissingForeignKeyField


class ForwardForeignKeyDescriptorTestCase(TestCase):  # type: ignore
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
        with self.assertRaisesMessage(
            MissingForeignKeyField,
            "Access to `User.role` was prevented.\n"
            "If you only need access to the column identifier, use `User.role_id` instead.\n"
            "To fetch the `Role` object, add `prefetch_related('role')` or `select_related('role')` to the query where `User` objects are selected.",
        ):
            (user,) = self.User.objects.all()
            with self.assertNumQueries(0):
                self.assertEqual(user.name, "Bert")
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
