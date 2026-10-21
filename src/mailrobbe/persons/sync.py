"""Writing computed rows into an aggregation table, touching only the rows that change."""

from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import text

from mailrobbe.persons.roots import Executor


async def sync_rows(
    db: Executor,
    table: str,
    keys: Sequence[str],
    values: Sequence[str],
    fresh: str,
    params: Mapping[str, Any],
    scope: str = "true",
) -> None:
    """Make the rows of table within scope exactly those of the query fresh, in one statement.

    fresh selects the key and value columns by these names. Rows whose values differ are
    updated, missing ones inserted, and rows matching scope (a condition on the table, alias t)
    that fresh lacks are deleted; unchanged rows are not written at all. keys are the table's
    primary key: the INSERT skips existing rows through it, since an anti join with the table
    it fills scans that table once per row when its statistics say it is empty (D112).
    """
    key_list, value_list = ", ".join(keys), ", ".join(values)
    same_key = " AND ".join(f"t.{key} = f.{key}" for key in keys)
    own = ", ".join(f"t.{value}" for value in values)
    new = ", ".join(f"f.{value}" for value in values)
    assign = ", ".join(f"{value} = f.{value}" for value in values)
    statement = f"""
        WITH fresh AS ({fresh}),
        updated AS (
            UPDATE {table} t SET {assign} FROM fresh f
            WHERE {same_key} AND ({own}) IS DISTINCT FROM ({new})
        ),
        deleted AS (
            DELETE FROM {table} t
            WHERE {scope} AND NOT EXISTS (SELECT FROM fresh f WHERE {same_key})
        )
        INSERT INTO {table} ({key_list}, {value_list})
        SELECT {key_list}, {value_list} FROM fresh f
        ON CONFLICT ({key_list}) DO NOTHING
    """
    await db.execute(text(statement), dict(params))
