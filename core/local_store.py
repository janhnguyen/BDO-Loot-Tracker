from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .parser import get_item_value, get_item_value_for_zone
from .uploader import LootEvent


@dataclass
class SessionSummary:
    id: int
    started_at: str
    ended_at: str | None


class LocalStore:
    DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S UTC"

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._connect() as conn:
            conn.execute(
                """
                create table if not exists sessions (
                    id integer primary key autoincrement,
                    started_at text not null,
                    ended_at text,
                    duration text not null default '00:00:00',
                    avg_hour real not null default 0,
                    zone text not null
                )
                """
            )
            self._ensure_sessions_table(conn)
            self._ensure_loot_events_table(conn)
            conn.execute(
                "create index if not exists idx_loot_events_local_session on loot_events_local(session_id)"
            )

    def _ensure_loot_events_table(self, conn: sqlite3.Connection):
        expected_columns = {
            "id",
            "session_id",
            "character",
            "zone",
            "item_name",
            "quantity",
            "value",
        }
        columns = {
            row["name"]
            for row in conn.execute("pragma table_info(loot_events_local)").fetchall()
        }
        if not columns:
            conn.execute(
                """
                create table loot_events_local (
                    id integer primary key autoincrement,
                    session_id integer not null references sessions(id) on delete cascade,
                    character text not null,
                    zone text not null,
                    item_name text not null,
                    quantity integer not null,
                    value real not null default 0,
                    unique(session_id, item_name)
                )
                """
            )
            return
        if columns == expected_columns:
            return
        self._migrate_loot_events_table(conn, columns)

    def _migrate_loot_events_table(self, conn: sqlite3.Connection, columns: set[str]):
        conn.execute(
            """
            create table loot_events_local_new (
                id integer primary key autoincrement,
                session_id integer not null references sessions(id) on delete cascade,
                character text not null,
                zone text not null,
                item_name text not null,
                quantity integer not null,
                value real not null default 0,
                unique(session_id, item_name)
            )
            """
        )

        if {"session_id", "item_name", "quantity", "character", "zone"}.issubset(columns):
            legacy_rows = conn.execute(
                "select * from loot_events_local order by id asc"
            ).fetchall()
            grouped: dict[tuple[int, str], dict] = {}
            for row in legacy_rows:
                key = (int(row["session_id"]), str(row["item_name"]))
                bucket = grouped.setdefault(
                    key,
                    {
                        "character": str(row["character"]),
                        "zone": str(row["zone"]),
                        "quantity": 0,
                    },
                )
                bucket["quantity"] += int(row["quantity"])

            for (session_id, item_name), bucket in grouped.items():
                qty = int(bucket["quantity"])
                total_value = get_item_value(item_name) * qty
                conn.execute(
                    """
                    insert into loot_events_local_new (
                        session_id, character, zone, item_name, quantity, value
                    ) values (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        session_id,
                        bucket["character"],
                        bucket["zone"],
                        item_name,
                        qty,
                        total_value,
                    ),
                )

        conn.execute("drop table loot_events_local")
        conn.execute("alter table loot_events_local_new rename to loot_events_local")

    def create_session(self, zone: str) -> int:
        now = self._format_datetime(datetime.now(timezone.utc))
        with self._connect() as conn:
            cur = conn.execute(
                "insert into sessions (started_at, zone) values (?, ?)",
                (now, zone),
            )
            return int(cur.lastrowid)

    def end_session(self, session_id: int, duration_seconds: float | None = None):
        now = self._format_datetime(datetime.now(timezone.utc))
        duration_seconds_value = max(0.0, float(duration_seconds or 0.0))
        duration = self._format_duration(duration_seconds_value)
        with self._connect() as conn:
            total_value = float(
                conn.execute(
                    "select coalesce(sum(value), 0) as total_value from loot_events_local where session_id = ?",
                    (session_id,),
                ).fetchone()["total_value"]
            )
            avg_hour = total_value * 3600 / max(duration_seconds_value, 1.0)
            conn.execute(
                "update sessions set ended_at = ?, duration = ?, avg_hour = ? where id = ?",
                (now, duration, avg_hour, session_id),
            )

    def update_session_zone(self, session_id: int, zone: str):
        with self._connect() as conn:
            conn.execute("update sessions set zone = ? where id = ?", (zone, session_id))
            conn.execute("update loot_events_local set zone = ? where session_id = ?", (zone, session_id))

    def add_event(self, session_id: int, event: LootEvent):
        total_value = get_item_value_for_zone(event.item_name, event.zone) * event.quantity
        with self._connect() as conn:
            conn.execute(
                """
                insert into loot_events_local (
                    session_id, character, zone, item_name, quantity, value
                ) values (?, ?, ?, ?, ?, ?)
                on conflict(session_id, item_name) do update set
                    quantity = loot_events_local.quantity + excluded.quantity,
                    value = loot_events_local.value + excluded.value,
                    character = excluded.character,
                    zone = excluded.zone
                """,
                (
                    session_id,
                    event.character,
                    event.zone,
                    event.item_name,
                    event.quantity,
                    total_value,
                ),
            )

    def list_sessions(self, limit: int = 50) -> list[SessionSummary]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                select
                    s.id,
                    s.started_at,
                    s.ended_at
                from sessions s
                order by s.id desc
                limit ?
                """,
                (limit,),
            ).fetchall()
            return [
                SessionSummary(
                    id=int(row["id"]),
                    started_at=row["started_at"],
                    ended_at=row["ended_at"],
                )
                for row in rows
            ]

    def get_unuploaded_events(self, session_id: int) -> list[tuple[int, LootEvent]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                select
                    e.id,
                    e.character,
                    e.zone,
                    e.item_name,
                    e.quantity,
                    e.value,
                    s.duration,
                    s.avg_hour
                from loot_events_local e
                join sessions s on s.id = e.session_id
                where e.session_id = ?
                order by e.id asc
                """,
                (session_id,),
            ).fetchall()

        events: list[tuple[int, LootEvent]] = []
        for row in rows:
            duration_seconds = self._parse_duration(str(row["duration"] or "00:00:00"))
            events.append(
                (
                    int(row["id"]),
                    LootEvent(
                        item_name=row["item_name"],
                        quantity=int(row["quantity"]),
                        zone=row["zone"],
                        raw_text=f"session_total:{session_id}",
                        character=row["character"],
                        time=duration_seconds,
                        avg_hour=float(row["avg_hour"] or 0.0),
                    ),
                )
            )
        return events

    def upload_session_events(self, session_id: int) -> int:
        rows = self.get_unuploaded_events(session_id)
        return len(rows)

    def _ensure_sessions_table(self, conn: sqlite3.Connection):
        columns = {
            row["name"]
            for row in conn.execute("pragma table_info(sessions)").fetchall()
        }

        needs_rebuild = (
            "duration_seconds" in columns
            or "duration" not in columns
            or "avg_hour" not in columns
        )
        if not needs_rebuild:
            if conn.execute(
                "select name from sqlite_master where type='table' and name='uploaded_loot_events'"
            ).fetchone():
                conn.execute("drop table uploaded_loot_events")
            return

        conn.execute("alter table sessions rename to sessions_old")
        conn.execute(
            """
            create table sessions (
                id integer primary key autoincrement,
                started_at text not null,
                ended_at text,
                duration text not null default '00:00:00',
                avg_hour real not null default 0,
                zone text not null
            )
            """
        )

        old_cols = {
            row["name"]
            for row in conn.execute("pragma table_info(sessions_old)").fetchall()
        }
        has_duration_seconds = "duration_seconds" in old_cols
        has_zone = "zone" in old_cols

        old_rows = conn.execute(
            "select * from sessions_old order by id asc"
        ).fetchall()
        for row in old_rows:
            started_dt = self._parse_datetime(row["started_at"])
            ended_dt = self._parse_datetime(row["ended_at"]) if row["ended_at"] else None
            duration_seconds = float(row["duration_seconds"] or 0.0) if has_duration_seconds else 0.0
            if duration_seconds <= 0 and ended_dt is not None:
                duration_seconds = max(0.0, (ended_dt - started_dt).total_seconds())
            conn.execute(
                """
                insert into sessions (id, started_at, ended_at, duration, avg_hour, zone)
                values (?, ?, ?, ?, ?, ?)
                """,
                (
                    int(row["id"]),
                    self._format_datetime(started_dt),
                    self._format_datetime(ended_dt) if ended_dt else None,
                    self._format_duration(duration_seconds),
                    0.0,
                    row["zone"] if has_zone else "Unknown",
                ),
            )

        conn.execute("drop table sessions_old")
        if conn.execute(
            "select name from sqlite_master where type='table' and name='uploaded_loot_events'"
        ).fetchone():
            conn.execute("drop table uploaded_loot_events")

    @classmethod
    def _format_datetime(cls, value: datetime) -> str:
        return value.astimezone(timezone.utc).strftime(cls.DATETIME_FORMAT)

    @classmethod
    def _parse_datetime(cls, value: str) -> datetime:
        if not value:
            return datetime.now(timezone.utc)
        try:
            parsed = datetime.strptime(value, cls.DATETIME_FORMAT)
            return parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            parsed = datetime.fromisoformat(value)
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)

    @staticmethod
    def _format_duration(seconds: float) -> str:
        total_seconds = int(max(0.0, seconds))
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        secs = total_seconds % 60
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"

    @staticmethod
    def _parse_duration(value: str) -> float:
        try:
            hours, minutes, seconds = (int(part) for part in value.split(":", 2))
            return float(hours * 3600 + minutes * 60 + seconds)
        except (TypeError, ValueError):
            return 0.0
