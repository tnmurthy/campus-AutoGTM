"""A Supabase stand-in recording writes, so the pipeline is testable offline."""

from typing import Any


class FakeResponse:
    def __init__(self, data: list[dict[str, Any]]):
        self.data = data


class FakeQuery:
    def __init__(self, table: "FakeTable", rows: list[dict[str, Any]]):
        self._table = table
        self._rows = rows

    def eq(self, column: str, value: Any) -> "FakeQuery":
        return FakeQuery(self._table, [r for r in self._rows if r.get(column) == value])

    def limit(self, n: int) -> "FakeQuery":
        return FakeQuery(self._table, self._rows[:n])

    def execute(self) -> FakeResponse:
        return FakeResponse(list(self._rows))


class FakeTable:
    def __init__(self, client: "FakeSupabase", name: str):
        self._client = client
        self._name = name

    def select(self, columns: str) -> FakeQuery:
        return FakeQuery(self, self._client.rows.setdefault(self._name, []))

    def insert(self, values: dict[str, Any]) -> FakeQuery:
        if self._name in self._client.fail_on:
            raise RuntimeError(f"simulated write failure on {self._name}")
        row = dict(values)
        row.setdefault("id", f"{self._name}-{len(self._client.rows.setdefault(self._name, [])) + 1}")
        self._client.rows.setdefault(self._name, []).append(row)
        self._client.writes.append((self._name, row))
        return FakeQuery(self, [row])


class FakeSupabase:
    def __init__(self, fail_on: set[str] | None = None):
        self.rows: dict[str, list[dict[str, Any]]] = {}
        self.writes: list[tuple[str, dict]] = []
        self.fail_on = fail_on or set()

    def table(self, name: str) -> FakeTable:
        return FakeTable(self, name)
