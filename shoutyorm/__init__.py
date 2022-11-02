# -*- coding: utf-8 -*-
from __future__ import annotations
"""
A series of monkeypatches to apply to Django's various ORM methods to force it
to error loudly when another query would be triggered, rather than silently
backfill the requested data causing N+1 queries.

Alternative options include:
 - django-seal <https://github.com/charettes/django-seal>
 - django-eraserhead <https://github.com/dizballanze/django-eraserhead>
 - nplusone <https://github.com/jmcarp/nplusone>

The expected public API usage is simply to include `shoutyorm` or `shoutyorm.Shout`
in your django project's INSTALLED_APPS, and set
SHOUTY_LOCAL_FIELDS / SHOUTY_RELATION_FIELDS / SHOUTY_RELATION_REVERSE_FIELDS
to True/False as desired.

If for whatever reason the patches aren't applied soon enough, you should be
able to manually call shoutyorm.patch(...) to set them up.

Patches are expected to work on Django 2.2 (LTS) onwards.

Settings
--------

SHOUTY_LOCAL_FIELDS = True
Accessing fields which have been deferred via `.only()` and `.defer()` at
the QuerySet level will error loudly.

SHOUTY_RELATION_FIELDS = True
Accessing OneToOnes which have not been `.select_related()` at the QuerySet
level will error loudly.
Accessing local foreignkeys which have not been `prefetch_related()` or
`select_related()` at the queryset level will error loudly.

SHOUTY_RELATION_REVERSE_FIELDS = True
Accessing foreignkeys from the "other" side (that is, via the reverse relation
manager) which have not been `.prefetch_related()` at the QuerySet level will error loudly.

Problems?
---------

There are likely to be both false positives and false negatives.
If you encounter a situation where an exception IS raised to prevent a query when
one shouldn't be (because it wouldn't do a query) please report it via the URL
below.
Likewise if you find it NOT raising an exception and letting a query silently
happen, please report it.

<https://github.com/kezabelle/django-shouty-orm/issues/new>
"""
from shoutyorm.errors import ShoutyAttributeError, MissingLocalField

try:
    from typing import Text
except ImportError:  # pragma: no cover
    pass

from .apps import Shout
from .patches import patch
from .errors import (
    ShoutyAttributeError,
    MissingLocalField,
    MissingRelationField,
    MissingReverseRelationField,
)

__version_info__ = "0.1.1"
__version__ = "0.1.1"
version = "0.1.1"
VERSION = "0.1.1"


def get_version() -> Text:
    return version


default_app_config = "shoutyorm.Shout"


__all__ = [
    "patch",
    "Shout",
    "default_app_config",
    "get_version",
    "ShoutyAttributeError",
    "MissingLocalField",
    "MissingRelationField",
    "MissingReverseRelationField",
]
