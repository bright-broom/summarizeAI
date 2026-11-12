"""SQLite の接続・スキーマ作成・簡易マイグレーション。"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from speech_summarizer_ai.platform_utils.paths import database_path

# ``progress_status`` 列用の DDL 断片（CHECK 制約付き）。
PROGRESS_STATUS_DDL: str = (
    "TEXT NOT NULL DEFAULT 'success' "
    "CHECK (progress_status IN ('recording', 'summarizing', 'success', 'failed'))"
)

# paragraph_list: [{"time","text"}] または [時刻, 本文] の JSON 配列
_MEETINGS_SCHEMA: str = (
    """
CREATE TABLE IF NOT EXISTS meetings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    paragraph_list TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    progress_status """
    + PROGRESS_STATUS_DDL
    + """
);
"""
)


def _raw_connect(project_root: Path) -> sqlite3.Connection:
    """データベースファイルへ接続し、行ファクトリと PRAGMA を設定する。

    Args:
        project_root: プロジェクトルートディレクトリ。

    Returns:
        sqlite3.Connection: オープン済み接続（呼び出し側で ``close()`` すること）。
    """
    db_path = database_path(project_root)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def connect(project_root: Path) -> Iterator[sqlite3.Connection]:
    """コミット／ロールバック付きで SQLite 接続を提供するコンテキストマネージャ。

    例外送出時は ``rollback()``、正常終了時は ``commit()`` を呼ぶ。

    Args:
        project_root: プロジェクトルートディレクトリ。

    Yields:
        sqlite3.Connection: トランザクション内の接続。
    """
    conn = _raw_connect(project_root)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _table_columns(conn: sqlite3.Connection, name: str) -> set[str]:
    """テーブル ``name`` の列名を集合で返す。

    Args:
        conn: SQLite 接続。
        name: テーブル名。

    Returns:
        set[str]: 列名の集合。
    """
    cur = conn.execute("PRAGMA table_info(" + name + ")")
    return {str(r[1]) for r in cur.fetchall()}


def _ensure_progress_status_column(conn: sqlite3.Connection) -> None:
    """``meetings`` に ``progress_status`` 列が無ければ追加する。

    Args:
        conn: SQLite 接続。

    Returns:
        None
    """
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='meetings'"
    )
    if not cur.fetchone():
        return
    cols = _table_columns(conn, "meetings")
    if "progress_status" in cols:
        return
    conn.execute(
        "ALTER TABLE meetings ADD COLUMN progress_status " + PROGRESS_STATUS_DDL
    )


def _migrate_meetings_drop_display_date(conn: sqlite3.Connection) -> None:
    """``meetings`` を現在の列定義へ移行する。

    Args:
        conn: SQLite 接続。

    Returns:
        None
    """
    conn.executescript(
        """
        BEGIN;
        CREATE TABLE meetings__new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            summary TEXT NOT NULL,
            paragraph_list TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            progress_status """
        + PROGRESS_STATUS_DDL
        + """
        );
        INSERT INTO meetings__new (
            id, title, summary, paragraph_list, created_at, updated_at, progress_status
        )
        SELECT
            id, title, summary, paragraph_list, created_at, updated_at, progress_status
        FROM meetings;
        DROP TABLE meetings;
        ALTER TABLE meetings__new RENAME TO meetings;
        COMMIT;
        """
    )


def init_schema(conn: sqlite3.Connection) -> None:
    """``meetings`` の DDL を適用し、必要なマイグレーションを行う。

    Args:
        conn: SQLite 接続。

    Returns:
        None
    """
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='meetings'"
    )
    if cur.fetchone():
        _ensure_progress_status_column(conn)
        cols = _table_columns(conn, "meetings")
        if "paragraph_list" not in cols:
            conn.execute("DROP TABLE meetings")
        elif "display_date" in cols:
            _migrate_meetings_drop_display_date(conn)
    conn.executescript(_MEETINGS_SCHEMA)
    _ensure_progress_status_column(conn)


def ensure_database(project_root: Path) -> None:
    """プロジェクトルート配下の SQLite に ``meetings`` スキーマを確保する。

    Args:
        project_root: プロジェクトルートディレクトリ。

    Returns:
        None
    """
    with connect(project_root) as conn:
        init_schema(conn)
