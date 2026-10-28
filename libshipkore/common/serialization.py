def to_jsonable(model):
    """A model as plain JSON-safe data: datetimes and enums become strings."""
    return model.model_dump(mode="json")
