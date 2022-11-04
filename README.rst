django-shouty-orm
=================

:author: Keryn Knight
:version: 0.1.1

Rationale
---------

I want to use ``MyModel.objects.only()`` and ``.defer()`` because that's the
**correct** thing to do, even if it's not the default thing Django does. But
using ``.only()`` and ``.defer()`` in Django is an absolute footgun because any
attempt to subsequently access the missing fields will ... **do another query**

Similarly, I don't want Django to silently allow me to do N+1 queries for related
managers/querysets. But it does, so there's another footgun.

This module then, is my terrible attempt to fix the footguns automatically, by
forcing them to raise exceptions where possible, rather than do the query. This
flies in the face of some other proposed solutions over the years on the mailing list,
such as automatically doing  ``prefetch_related`` or ``select_related``.

I think/hope that the package pairs well with `django-shouty-templates`_ to try
and surface some of the small pains I've had over the years.

What it does
------------

All of the following examples should raise an exception because they pose a probable
additional +1 (or more) queries.

Accessing fields intentionally not selected
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

When using ``only()`` or ``defer()``, attempts to use attributes not selected will
raise an exception instead of doing **+1 query**.

Using ``only``::

    >>> u = User.objects.only('pk').get(pk=1)
    >>> u.username
    MissingLocalField("Access to `User.username` was prevented [...]")

Using ``defer``::

    >>> u = User.objects.defer('username').get(pk=1)
    >>> u.email
    >>> u.username
    MissingLocalField("Access to `User.username` was prevented [...]")

Accessing ``OneToOneField`` relations
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

When selecting a model instance which has a ``OneToOne`` relationship with another
model, trying to access that attribute will raise an exception instead of doing **1 query**::

    >>> event = Event.objects.get(pk=1)
    >>> assert event.type == "add"
    >>> event.user.pk
    MissingRelationField("Access to user [...]")

Access to reverse relationships that have not been selected::

    >>> u = User.objects.only('pk').get(pk=1)
    >>> u.logentry_set.all()
    MissingReverseRelationField("Access to logentry_set [...]")


Accessing ``ForeignKey`` and ``ManyToManyField`` relations
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Pretty much all relationship access (normal or reverse, ``OneToOne`` or
``ForeignKey`` or ``ManyToMany``) should be blocked unless ``select_related`` or
``prefetch_related`` were used to include them.


Methods which are blocked when ``prefetch_related`` data exists.
-------------------------

- ``RelatedManager.filter``
- ``RelatedManager.exclude``
- ``RelatedManager.annotate``
- ``RelatedManager.earliest``
- ``RelatedManager.latest``
- ``RelatedManager.in_bulk``
- ``RelatedManager.defer``
- ``RelatedManager.only``
- ``RelatedManager.reverse``
- ``RelatedManager.distinct``
- ``RelatedManager.values``
- ``RelatedManager.values_list`
- ``RelatedManager.order_by``
- ``RelatedManager.extra``
- ``RelatedManager.select_related``
- ``RelatedManager.alias``
- ``RelatedManager.prefetch_related```

Methods which aren't yet blocked
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

- ``RelatedManager.first``
- ``RelatedManager.last``

Methods which probably won't ever be blocked
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

- ``RelatedManager.select_for_update``
- ``RelatedManager.dates``
- ``RelatedManager.datetimes``
- ``RelatedManager.intersection``
- ``RelatedManager.difference``
- ``RelatedManager.union``


Setup
-----

Add ``shoutyorm`` or ``shoutyorm.Shout`` to your ``settings.INSTALLED_APPS``

I'd certainly suggest that you should only enable it when ``DEBUG`` is ``True`` or
during your test suite.

Escape hatches
--------------

In some scenarios, you may wish to allow a relationship to be traversed anyway, perhaps
after using `Model.objects.create` and fetching related data, for such scenarios
there's a complete hack available::



Dependencies
^^^^^^^^^^^^

- Django 2.2+ (obviously)
- `wrapt`_ 1.11+ (for proxying managers/querysets transparently)


Optional configuration
^^^^^^^^^^^^^^^^^^^^^^


- ``settings.SHOUTY_LOCAL_FIELDS`` may be ``True|False``

  Accessing fields which have been deferred via ``.only()`` and ``.defer()`` at the
  QuerySet level will error loudly.
- ``settings.SHOUTY_RELATION_FIELDS`` may be ``True|False``

  Accessing OneToOnes which have not been ``.select_related()`` at the QuerySet
  level will error loudly.
  Accessing local foreignkeys which have not been ``prefetch_related()`` or
  ``select_related()`` at the queryset level will error loudly.
- ``settings.SHOUTY_RELATION_REVERSE_FIELDS`` may be ``True|False``

  Accessing foreignkeys from the "other" side (that is, via the reverse relation
  manager) which have not been ``.prefetch_related()`` at the QuerySet level will error loudly.

Tests
-----

Just run ``python3 -m shoutyorm`` and hope for the best. I usually do.


Alternatives
------------

A similar similar approach is taken by `django-seal`_ but without the
onus/burden of subclassing from specific models. I've not looked at the
implementation details of how seal works, but I expect I could've saved myself
quite a lot of headache by seeing what steps it takes in what circumstances,
rather than constantly hitting breakpoints and inspecting state.

A novel idea is presented in `django-eraserhead`_ of specifically calling out
when you might be able to use ``defer()`` and ``only()`` to reduce your selections,
but introducing those optimisations still poses a danger of regression without a
test suite and this module.

Having started writing this list of alternatives, I am reminded of `nplusone`_
and it turns out that has Django support *and* a setting for raising exceptions...
So all of this patch may be moot, because I expect that covers a lot more? Again
I've not looked at their implementation but I'm sure it's miles better than this
abomination.


The license
-----------

It's `FreeBSD`_. There's should be a ``LICENSE`` file in the root of the repository, and in any archives.

.. _FreeBSD: http://en.wikipedia.org/wiki/BSD_licenses#2-clause_license_.28.22Simplified_BSD_License.22_or_.22FreeBSD_License.22.29
.. _django-seal: https://github.com/charettes/django-seal
.. _django-eraserhead: https://github.com/dizballanze/django-eraserhead
.. _nplusone: https://github.com/jmcarp/nplusone
.. _django-shouty-templates: https://github.com/kezabelle/django-shouty-templates
.. _wrapt: https://wrapt.readthedocs.io/en/latest/index.html
