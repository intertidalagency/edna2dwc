from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
import json

from edna2dwc.common.table import Table, column, internal, is_json_object, literal

COLUMN = "dynamicProperties"
BLOB = internal("blob")


def value_column(index: int) -> str:
    return internal(f"dynamic{index}")


def json_path(key: str) -> str:
    return literal(f"$.{json.dumps(key)}")


def members_without(blob: str, keys: str) -> str:
    entries = f"""map_entries(json_transform({blob}, '"MAP(VARCHAR, JSON)"'))"""
    kept = f"list_filter({entries}, lambda e: NOT list_contains({keys}, e.key))"
    return f"nullif((to_json(map_from_entries({kept}))::VARCHAR)[2:-2], '')"


@dataclass(frozen=True)
class DynamicProperties:
    columns: tuple[str, ...] = ()
    blob: str = BLOB

    @classmethod
    def published_in(cls, table: Table) -> DynamicProperties:
        return cls(blob=table.text(COLUMN))

    def hidden(self) -> list[str]:
        return [BLOB, *(value_column(i) for i in range(len(self.columns)))]

    def keys_set_on_the_row(self, *also: str) -> str:
        keys = [
            *(
                f"CASE WHEN {value_column(i)} <> '' THEN {literal(name)} END"
                for i, name in enumerate(self.columns)
            ),
            *map(literal, also),
        ]
        return f"[{', '.join(keys)}]::VARCHAR[]"

    def sets_no_column(self) -> str:
        return " AND ".join(
            [f"coalesce({value_column(i)}, '') = ''" for i in range(len(self.columns))] or ["TRUE"]
        )

    def json(self, removed: Collection[str] = ()) -> str:
        source = (
            f"CASE WHEN {is_json_object(self.blob)} "
            f"THEN {members_without(self.blob, self.keys_set_on_the_row(*removed))} END"
        )
        pairs = "".join(
            f", CASE WHEN {value_column(i)} <> '' "
            f"THEN to_json({literal(name)}) || ':' || to_json({value_column(i)}) END"
            for i, name in enumerate(self.columns)
            if name not in removed
        )
        return f"nullif('{{' || concat_ws(',', {source}{pairs}) || '}}', '{{}}')"

    def folded(
        self, table: Table, removed: Collection[str] = (), *, as_given: bool = False
    ) -> Table:
        built = self.json(removed)
        if as_given:
            built = (
                f"CASE WHEN {self.sets_no_column()} THEN nullif({self.blob}, '') ELSE {built} END"
            )
        return table.view(
            f"{table.name}_folded",
            f"SELECT {table.star(COLUMN)}, {built} AS {column(COLUMN)} FROM {table.name}",
        )

    def colliding_keys(self, table: Table) -> list[str]:
        if not self.columns:
            return []
        in_blobs = {
            key
            for (key,) in table.rows(
                f"SELECT DISTINCT unnest(json_keys({self.blob})) FROM {table.name} "
                f"WHERE {self.blob} <> ''"
            )
        }
        shared = [(i, name) for i, name in enumerate(self.columns) if name in in_blobs]
        if not shared:
            return []
        collides = [
            f"bool_or({value_column(i)} <> '' AND json_exists({self.blob}, {json_path(name)}) "
            f"AND coalesce(json_extract_string({self.blob}, {json_path(name)}), '') "
            f"<> {value_column(i)})"
            for i, name in shared
        ]
        found = table.one(
            f"SELECT {', '.join(collides)} FROM {table.name} WHERE {self.blob} <> ''"
        )
        return sorted(name for (_, name), collided in zip(shared, found) if collided)
