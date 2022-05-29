class ShoutyAttributeError(AttributeError):
    pass


class MissingLocalField(ShoutyAttributeError):
    pass


class MissingRelationField(ShoutyAttributeError):
    pass


class MissingForeignKeyField(MissingRelationField):
    pass


class MissingManyToManyField(MissingRelationField):
    pass


class MissingOneToOneField(MissingRelationField):
    pass


class MissingReverseRelationField(MissingRelationField):
    pass
