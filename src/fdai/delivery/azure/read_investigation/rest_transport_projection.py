"""Pure row projections for the bounded Azure REST read transport."""

from __future__ import annotations

from collections.abc import Mapping

from fdai.delivery.azure.read_investigation.transport import AzureRow


def joined_values(
    properties: Mapping[str, object],
    *,
    singular: str,
    plural: str,
) -> str:
    many = properties.get(plural)
    if isinstance(many, list):
        rendered = joined_strings(many)
        if rendered != "none":
            return rendered
    one = properties.get(singular)
    return one[:512] if isinstance(one, str) and one else "unknown"


def joined_strings(value: object) -> str:
    if not isinstance(value, list):
        return "none"
    rendered = ",".join(item for item in value if isinstance(item, str) and item)
    return rendered[:512] or "none"


def resource_name(value: object) -> str:
    if not isinstance(value, Mapping):
        return "unknown"
    resource_id = value.get("id")
    if not isinstance(resource_id, str) or not resource_id:
        return "unknown"
    return resource_id.rstrip("/").rsplit("/", maxsplit=1)[-1][:256]


def address_prefixes(value: object) -> str:
    if not isinstance(value, Mapping):
        return "none"
    return joined_strings(value.get("addressPrefixes"))


def network_associations(properties: Mapping[str, object]) -> str:
    associations: list[str] = []
    for collection, kind in (("networkInterfaces", "nic"), ("subnets", "subnet")):
        values = properties.get(collection)
        if not isinstance(values, list):
            continue
        for value in values:
            name = resource_name(value)
            if name != "unknown":
                associations.append(f"{kind}:{name}")
    return ",".join(associations)[:512] or "none"


def nested(row: Mapping[str, object], key: str) -> str | None:
    value = row.get(key)
    if isinstance(value, Mapping):
        nested_value = value.get("value")
        return nested_value if isinstance(nested_value, str) else None
    return value if isinstance(value, str) else None


def caller_kind(row: Mapping[str, object]) -> str:
    claims = row.get("claims")
    if not isinstance(claims, Mapping):
        return "unknown"
    if isinstance(claims.get("xms_mirid"), str):
        return "managed_identity"
    identity_type = str(claims.get("idtyp") or "").casefold()
    if identity_type == "user":
        return "user"
    if identity_type == "app":
        return "service_principal"
    if isinstance(claims.get("http://schemas.microsoft.com/identity/claims/objectidentifier"), str):
        return "user"
    if isinstance(claims.get("http://schemas.xmlsoap.org/ws/2005/05/identity/claims/upn"), str):
        return "user"
    if isinstance(claims.get("appid"), str):
        return "service_principal"
    return "unknown"


def log_rows(payload: Mapping[str, object]) -> tuple[AzureRow, ...]:
    tables = payload.get("tables")
    if not isinstance(tables, list) or not tables or not isinstance(tables[0], Mapping):
        return ()
    columns = tables[0].get("columns")
    rows = tables[0].get("rows")
    if not isinstance(columns, list) or not isinstance(rows, list):
        return ()
    names: list[str] = []
    for item in columns:
        name = item.get("name") if isinstance(item, Mapping) else None
        if not isinstance(name, str):
            return ()
        names.append(name)
    return tuple(
        dict(zip(names, row, strict=True))
        for row in rows
        if isinstance(row, list) and len(row) == len(names)
    )


__all__ = [
    "address_prefixes",
    "caller_kind",
    "joined_strings",
    "joined_values",
    "log_rows",
    "nested",
    "network_associations",
    "resource_name",
]
