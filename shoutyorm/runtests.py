from django.test.runner import DiscoverRunner
import django
from django.conf import settings

settings.configure(
    SECRET_KEY="shoutyorm-runtests" * 10,
    DATABASES={"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}},
    INSTALLED_APPS=(
        "django.contrib.contenttypes",
        "django.contrib.auth",
        "django.contrib.messages",
        "django.contrib.admin",
        "shoutyorm",
    ),
    MIDDLEWARE=(
        "django.contrib.auth.middleware.AuthenticationMiddleware",
        "django.contrib.messages.middleware.MessageMiddleware",
        "django.contrib.sessions.middleware.SessionMiddleware",
    ),
    TEMPLATES=[
        {
            "BACKEND": "django.template.backends.django.DjangoTemplates",
            "DIRS": [],
            "APP_DIRS": True,
            "OPTIONS": {
                "context_processors": (
                    "django.contrib.auth.context_processors.auth",
                    "django.contrib.messages.context_processors.messages",
                )
            },
        },
    ],
    SHOUTY_LOCAL_FIELDS=True,
    SHOUTY_RELATION_FIELDS=True,
    SHOUTY_RELATION_REVERSE_FIELDS=True,
)
django.setup()

from shoutyorm.tests import (
    MostlyM2MPrefetchRelatedTestCase,
    PrefetchReverseRelatedTestCase,
    FormTestCase,
    TemplateTestCase,
    MyPyTestCase,
)
from shoutyorm.test_onetoone import (
    ForwardOneToOneDescriptorTestCase,
    ReverseOneToOneDescriptorTestCase,
)
from shoutyorm.test_foreignkey import (
    ForwardForeignKeyDescriptorTestCase,
    ReverseForeignKeyDescriptorTestCase,
)
from shoutyorm.test_only_defer import OnlyDeferTestCase

test_runner = DiscoverRunner(interactive=False, verbosity=2)
failures = test_runner.run_tests(
    test_labels=[],
    extra_tests=[
        test_runner.test_loader.loadTestsFromTestCase(MostlyM2MPrefetchRelatedTestCase),
        test_runner.test_loader.loadTestsFromTestCase(PrefetchReverseRelatedTestCase),
        test_runner.test_loader.loadTestsFromTestCase(FormTestCase),
        test_runner.test_loader.loadTestsFromTestCase(TemplateTestCase),
        test_runner.test_loader.loadTestsFromTestCase(ForwardOneToOneDescriptorTestCase),
        test_runner.test_loader.loadTestsFromTestCase(ReverseOneToOneDescriptorTestCase),
        test_runner.test_loader.loadTestsFromTestCase(ForwardForeignKeyDescriptorTestCase),
        test_runner.test_loader.loadTestsFromTestCase(ReverseForeignKeyDescriptorTestCase),
        test_runner.test_loader.loadTestsFromTestCase(OnlyDeferTestCase),
        test_runner.test_loader.loadTestsFromTestCase(MyPyTestCase),
    ],
)
