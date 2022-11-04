from __future__ import annotations


class ShoutyAttributeError(Exception):
    """
    Whilst this should technically be an AttributeError, there's more likelihood
    of people having done `try: ...lots of stuf ... except AttributeError: ...`
    than there is `try: ... except Exception: ...` and if they have done the latter
    well goodness there's nothing I can do to save them.
    """

    __slots__ = ("kwargs",)

    def __init__(self, /, text, **kwargs):
        super().__init__(text)
        self.kwargs = kwargs

    def __str__(self):
        return self.args[0].format(**self.kwargs)

    def __repr__(self):
        kws = ", ".join(f"{k}={v}" for k, v in self.kwargs.items())
        return f"{self.__class__.__qualname__}(text={self.args[0]}, {kws!r})"


class MissingLocalField(ShoutyAttributeError):
    __slots__ = ()


class MissingRelationField(ShoutyAttributeError):
    __slots__ = ()


class MissingReverseRelationField(MissingRelationField):
    __slots__ = ()


class NoMoreFilteringAllowed(ShoutyAttributeError):
    __slots__ = ()
