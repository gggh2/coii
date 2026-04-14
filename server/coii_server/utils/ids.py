from ulid import ULID

PREFIX_MAP = {
    "experiment": "ex",
    "exposure": "ep",
    "trace": "tr",
    "span": "sp",
    "outcome": "oc",
    "api_key": "ak",
}


def make_public_id(entity: str) -> str:
    prefix = PREFIX_MAP.get(entity, "xx")
    return f"{prefix}_{ULID()}"
