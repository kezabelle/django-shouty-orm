from django.test.runner import DiscoverRunner
import django
from django.conf import settings

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

# from shoutyorm.test_onetoone import (
#     ForwardOneToOneDescriptorTestCase,
#     ReverseOneToOneDescriptorTestCase,
# )
# from shoutyorm.test_foreignkey import (
#     ForwardForeignKeyDescriptorTestCase,
#     ReverseForeignKeyDescriptorTestCase,
# )
# from shoutyorm.test_manytomany import (
#     ManyToManyTestCase,
#     NestedManyToManyTestCase,
#     MultipleManyToManyTestCase,
# )
# from shoutyorm.test_only_defer import OnlyDeferTestCase
# from shoutyorm.test_forms import FormTestCase
# from shoutyorm.test_templates import TemplateTestCase


test_runner = DiscoverRunner(interactive=False, verbosity=2)
failures = test_runner.run_tests(
    test_labels=[],
    extra_tests=[],
)
