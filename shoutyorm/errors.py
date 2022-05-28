class ShoutyAttributeError(AttributeError):
    pass


class MissingLocalField(ShoutyAttributeError):
    pass


class MissingRelationField(ShoutyAttributeError):
    pass


class MissingReverseRelationField(MissingRelationField):
    pass
