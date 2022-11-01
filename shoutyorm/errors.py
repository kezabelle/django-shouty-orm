class ShoutyAttributeError(Exception):
    """
    Whilst this should technically be an AttributeError, there's more likelihood
    of people having done `try: ...lots of stuf ... except AttributeError: ...`
    than there is `try: ... except Exception: ...` and if they have done the latter
    well goodness there's nothing I can do to save them.
    """

    __slots__ = ()


class MissingLocalField(ShoutyAttributeError):
    __slots__ = ()


class MissingRelationField(ShoutyAttributeError):
    __slots__ = ()


class MissingForeignKeyField(MissingRelationField):
    __slots__ = ()


class MissingManyToManyField(MissingRelationField):
    __slots__ = ()


class MissingOneToOneField(MissingRelationField):
    __slots__ = ()


class MissingReverseRelationField(MissingRelationField):
    __slots__ = ()


class RedundantSelection(ShoutyAttributeError):
    __slots__ = ("selected_name",)

    def __init__(self, *args, selected_name):
        super().__init__(*args)
        self.selected_name = selected_name


class NoMoreFilteringAllowed(ShoutyAttributeError):
    __slots__ = ()
