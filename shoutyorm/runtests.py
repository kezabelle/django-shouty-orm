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

test_runner = DiscoverRunner(interactive=False, verbosity=2)
failures = test_runner.run_tests(
    test_labels=[],
    extra_tests=[],
)
