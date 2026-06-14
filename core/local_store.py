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
            self._ensure_timeline_table(conn)

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

    def _ensure_timeline_table(self, conn: sqlite3.Connection):
        conn.execute(
            """
            create table if not exists loot_events_timeline (
                id integer primary key autoincrement,
                session_id integer not null references sessions(id) on delete cascade,
                item_name text not null,
                quantity integer not null,
                value real not null default 0,
                elapsed_seconds real not null default 0
            )
            """
        )
        conn.execute(
            "create index if not exists idx_timeline_session on loot_events_timeline(session_id)"
        )

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
        now = datetime.now(timezone.utc)
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
            row = conn.execute(
                "select started_at from sessions where id = ?", (session_id,)
            ).fetchone()
            elapsed = 0.0
            if row:
                elapsed = max(0.0, (now - self._parse_datetime(row["started_at"])).total_seconds())
            conn.execute(
                """
                insert into loot_events_timeline
                    (session_id, item_name, quantity, value, elapsed_seconds)
                values (?, ?, ?, ?, ?)
                """,
                (session_id, event.item_name, event.quantity, total_value, elapsed),
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

    def get_session_detail(self, session_id: int) -> dict:
        with self._connect() as conn:
            session_row = conn.execute(
                "select * from sessions where id = ?", (session_id,)
            ).fetchone()
            if not session_row:
                return {"session": None, "timeline": [], "items": []}

            timeline_rows = conn.execute(
                """
                select item_name, quantity, value, elapsed_seconds
                from loot_events_timeline
                where session_id = ?
                order by elapsed_seconds asc, id asc
                """,
                (session_id,),
            ).fetchall()

            item_rows = conn.execute(
                """
                select item_name, quantity, value
                from loot_events_local
                where session_id = ?
                order by quantity desc
                """,
                (session_id,),
            ).fetchall()

        return {
            "session": {
                "id": int(session_row["id"]),
                "zone": session_row["zone"],
                "started_at": session_row["started_at"],
                "ended_at": session_row["ended_at"],
                "duration": session_row["duration"],
                "avg_hour": float(session_row["avg_hour"] or 0.0),
            },
            "timeline": [
                {
                    "item_name": r["item_name"],
                    "quantity": int(r["quantity"]),
                    "value": float(r["value"]),
                    "elapsed_seconds": float(r["elapsed_seconds"]),
                }
                for r in timeline_rows
            ],
            "items": [
                {
                    "item_name": r["item_name"],
                    "quantity": int(r["quantity"]),
                    "value": float(r["value"]),
                }
                for r in item_rows
            ],
        }

    def delete_session(self, session_id: int):
        with self._connect() as conn:
            conn.execute("pragma foreign_keys = on")
            conn.execute("delete from sessions where id = ?", (session_id,))

    def wipe_database(self):
        with self._connect() as conn:
            conn.execute("pragma foreign_keys = on")
            conn.execute("delete from sessions")
            conn.execute("delete from sqlite_sequence where name = 'sessions'")

    def get_db_stats(self) -> dict:
        with self._connect() as conn:
            summary = conn.execute(
                """
                select
                    count(*) as total_sessions,
                    max(avg_hour) as best_avg_hour,
                    (select zone from sessions order by avg_hour desc limit 1) as best_zone,
                    (select id   from sessions order by avg_hour desc limit 1) as best_session_id
                from sessions
                """
            ).fetchone()

            totals = conn.execute(
                """
                select
                    coalesce(sum(quantity), 0) as total_items,
                    coalesce(sum(value), 0) as total_silver
                from loot_events_local
                """
            ).fetchone()

            session_rows = conn.execute(
                """
                select
                    s.id,
                    s.started_at,
                    s.ended_at,
                    s.duration,
                    s.zone,
                    s.avg_hour,
                    coalesce(sum(e.value), 0) as total_silver,
                    count(distinct e.item_name) as item_count
                from sessions s
                left join loot_events_local e on e.session_id = s.id
                group by s.id
                order by s.id desc
                limit 50
                """
            ).fetchall()

            top_item_rows = conn.execute(
                """
                select
                    item_name,
                    sum(quantity) as total_qty,
                    sum(value) as total_silver
                from loot_events_local
                group by item_name
                order by total_qty desc
                limit 10
                """
            ).fetchall()

        return {
            "summary": {
                "total_sessions": int(summary["total_sessions"]),
                "total_items": int(totals["total_items"]),
                "total_silver": float(totals["total_silver"]),
                "best_avg_hour": float(summary["best_avg_hour"] or 0.0),
                "best_zone": summary["best_zone"] or "—",
                "best_session_id": int(summary["best_session_id"]) if summary["best_session_id"] is not None else None,
            },
            "sessions": [
                {
                    "id": int(row["id"]),
                    "started_at": row["started_at"],
                    "ended_at": row["ended_at"],
                    "duration": row["duration"],
                    "zone": row["zone"],
                    "avg_hour": float(row["avg_hour"] or 0.0),
                    "total_silver": float(row["total_silver"]),
                    "item_count": int(row["item_count"]),
                }
                for row in session_rows
            ],
            "top_items": [
                {
                    "item_name": row["item_name"],
                    "total_qty": int(row["total_qty"]),
                    "total_silver": float(row["total_silver"]),
                }
                for row in top_item_rows
            ],
        }

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
