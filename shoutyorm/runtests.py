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
    LocalFieldsTestCase,
    NormalRelationFieldsTestCase,
    MostlyM2MPrefetchRelatedTestCase,
    PrefetchReverseRelatedTestCase,
    ReverseRelationFieldsTestCase,
    FormTestCase,
    TemplateTestCase,
    ForwardManyToOneDescriptorTestCase,
    MyPyTestCase,
)

test_runner = DiscoverRunner(interactive=False, verbosity=2)
failures = test_runner.run_tests(
    test_labels=[],
    extra_tests=[
        test_runner.test_loader.loadTestsFromTestCase(LocalFieldsTestCase),
        test_runner.test_loader.loadTestsFromTestCase(NormalRelationFieldsTestCase),
        test_runner.test_loader.loadTestsFromTestCase(MostlyM2MPrefetchRelatedTestCase),
        test_runner.test_loader.loadTestsFromTestCase(PrefetchReverseRelatedTestCase),
        test_runner.test_loader.loadTestsFromTestCase(ReverseRelationFieldsTestCase),
        test_runner.test_loader.loadTestsFromTestCase(FormTestCase),
        test_runner.test_loader.loadTestsFromTestCase(TemplateTestCase),
        test_runner.test_loader.loadTestsFromTestCase(ForwardManyToOneDescriptorTestCase),
        test_runner.test_loader.loadTestsFromTestCase(MyPyTestCase),
    ],
)
