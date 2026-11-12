"""``meetings`` テーブルの CRUD。ドメイン型と ``ensure_database`` を再公開する。"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from speech_summarizer_ai.data.schema import connect, ensure_database
from speech_summarizer_ai.domain.meeting import (
    LIST_CARD_SUMMARY_PREVIEW_LEN,
    MeetingDetailRecord,
    MeetingListRow,
    ProgressStatus,
    format_created_at_for_display,
    header_meta_for_detail,
    summary_preview_for_list_card,
)

__all__ = [
    "LIST_CARD_SUMMARY_PREVIEW_LEN",
    "MeetingDetailRecord",
    "MeetingListRow",
    "ProgressStatus",
    "append_paragraph_line",
    "delete_meeting",
    "ensure_database",
    "format_created_at_for_display",
    "get_meeting",
    "header_meta_for_detail",
    "insert_meeting_for_recording",
    "list_meetings",
    "summary_preview_for_list_card",
    "update_meeting_progress_status",
    "update_meeting_summary",
    "update_meeting_title",
]


def _coerce_progress_status(raw: str) -> ProgressStatus:
    """DB に保存された ``progress_status`` 文字列を列挙値へ変換する。

    値が ``ProgressStatus`` に無い場合は ``SUCCESS`` を返す。

    Args:
        raw: DB から読み取ったステータス文字列。

    Returns:
        ProgressStatus: 対応する列挙値。不明な文字列は ``SUCCESS``。
    """
    try:
        return ProgressStatus(raw)
    except ValueError:
        return ProgressStatus.SUCCESS


def _paragraph_list_to_lines(raw_json: str) -> tuple[tuple[str, str], ...]:
    """``paragraph_list`` カラムの JSON を ``(時刻, 本文)`` のタプル列に変換する。

    Args:
        raw_json: ``paragraph_list`` 列の JSON 文字列。

    Returns:
        tuple[tuple[str, str], ...]: ``(時刻, 本文)`` の不変タプル列。リストでない・要素形式が不正な場合は空タプル。
    """
    data = json.loads(raw_json)
    if not isinstance(data, list):
        return ()
    lines: list[tuple[str, str]] = []
    for item in data:
        if isinstance(item, dict):
            t = item.get("time")
            tx = item.get("text")
            if isinstance(t, str) and isinstance(tx, str):
                lines.append((t, tx))
        elif isinstance(item, (list, tuple)) and len(item) == 2:
            if isinstance(item[0], str) and isinstance(item[1], str):
                lines.append((item[0], item[1]))
    return tuple(lines)


def list_meetings(project_root: Path) -> list[MeetingListRow]:
    """商談一覧を ``created_at`` の新しい順で取得する。

    ``created_at`` は ISO 形式文字列のため辞書順で新しい日時が先頭になる。
    同一値のときは ``id`` 降順で並べる。

    Args:
        project_root: プロジェクトルートディレクトリ。

    Returns:
        list[MeetingListRow]: 一覧行のリスト。先頭が作成日時が最も新しい行。
    """
    with connect(project_root) as conn:
        cur = conn.execute("""
            SELECT id, created_at, title, summary, paragraph_list, progress_status
            FROM meetings
            ORDER BY created_at DESC, id DESC
            """)
        out: list[MeetingListRow] = []
        for row in cur.fetchall():
            summary = str(row["summary"]).strip()
            pl = str(row["paragraph_list"]).strip()
            summarized = bool(summary) or (pl not in ("", "[]"))
            preview = summary_preview_for_list_card(str(row["summary"]))
            pst = _coerce_progress_status(str(row["progress_status"]))
            out.append(
                MeetingListRow(
                    id=int(row["id"]),
                    created_at=str(row["created_at"]),
                    title=str(row["title"]),
                    summary_preview=preview,
                    summarized=summarized,
                    progress_status=pst,
                )
            )
        return out


def insert_meeting_for_recording(project_root: Path) -> int:
    """録音開始時に空の商談行を作成し、主キーを返す。

    ``paragraph_list`` は ``[]``、``progress_status`` は ``recording`` とする。

    Args:
        project_root: プロジェクトルートディレクトリ。

    Returns:
        int: 挿入した行の主キー（``id``）。
    """
    now = datetime.now()
    title = "新規録音"
    empty_summary = ""
    empty_pl = "[]"
    created = now.replace(microsecond=0).isoformat(timespec="seconds")
    pst = ProgressStatus.RECORDING.value
    with connect(project_root) as conn:
        cur = conn.execute(
            """
            INSERT INTO meetings (
                title, summary, paragraph_list,
                created_at, updated_at, progress_status
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (title, empty_summary, empty_pl, created, created, pst),
        )
        return int(cur.lastrowid)


def append_paragraph_line(
    project_root: Path, meeting_id: int, time_str: str, text: str
) -> bool:
    """``paragraph_list`` に ``{"time","text"}`` を 1 件追加する（リアルタイム文字起こし用）。

    Args:
        project_root: プロジェクトルートディレクトリ。
        meeting_id: 商談 ID。
        time_str: 表示用時刻（例: ``00:01:02``）。
        text: 本文。前後の空白は無視し、空なら追記しない。

    Returns:
        bool: 対象行が存在し更新に成功した場合、または本文が空で追記不要な場合は True。行が存在しない場合は False。
    """
    body = text.strip()
    if not body:
        return True
    now = datetime.now().replace(microsecond=0).isoformat(timespec="seconds")
    with connect(project_root) as conn:
        row = conn.execute(
            "SELECT paragraph_list FROM meetings WHERE id = ?",
            (meeting_id,),
        ).fetchone()
        if row is None:
            return False
        raw = str(row["paragraph_list"])
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = []
        if not isinstance(data, list):
            data = []
        data.append({"time": time_str, "text": body})
        conn.execute(
            """
            UPDATE meetings
            SET paragraph_list = ?, updated_at = ?
            WHERE id = ?
            """,
            (json.dumps(data, ensure_ascii=False), now, meeting_id),
        )
    return True


def get_meeting(project_root: Path, meeting_id: int) -> MeetingDetailRecord | None:
    """指定 ID の商談詳細レコードを取得する。

    Args:
        project_root: プロジェクトルートディレクトリ。
        meeting_id: 商談 ID。

    Returns:
        MeetingDetailRecord | None: 詳細レコード。該当 ID が無ければ None。
    """
    with connect(project_root) as conn:
        row = conn.execute(
            """
            SELECT id, title, summary, paragraph_list,
                   created_at, updated_at, progress_status
            FROM meetings
            WHERE id = ?
            """,
            (meeting_id,),
        ).fetchone()
        if row is None:
            return None
        lines = _paragraph_list_to_lines(str(row["paragraph_list"]))
        pst = _coerce_progress_status(str(row["progress_status"]))
        return MeetingDetailRecord(
            id=int(row["id"]),
            title=str(row["title"]),
            summary=str(row["summary"]),
            transcript_lines=lines,
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
            progress_status=pst,
        )


def delete_meeting(project_root: Path, meeting_id: int) -> bool:
    """指定 ID の商談行を削除する。

    Args:
        project_root: プロジェクトルートディレクトリ。
        meeting_id: 商談 ID。

    Returns:
        bool: 1 行以上削除できた場合 True。
    """
    with connect(project_root) as conn:
        cur = conn.execute("DELETE FROM meetings WHERE id = ?", (meeting_id,))
        return cur.rowcount > 0


def update_meeting_title(project_root: Path, meeting_id: int, title: str) -> bool:
    """一覧・詳細で使う ``title`` 列を更新する。

    Args:
        project_root: プロジェクトルートディレクトリ。
        meeting_id: 商談 ID。
        title: 新しいタイトル。空白のみは不可。

    Returns:
        bool: 1 行更新できた場合 True。タイトルが空白のみの場合は False。
    """
    new_title = title.strip()
    if not new_title:
        return False
    now = datetime.now().replace(microsecond=0).isoformat(timespec="seconds")
    with connect(project_root) as conn:
        cur = conn.execute(
            """
            UPDATE meetings
            SET title = ?, updated_at = ?
            WHERE id = ?
            """,
            (new_title, now, meeting_id),
        )
        return cur.rowcount > 0


def update_meeting_progress_status(
    project_root: Path, meeting_id: int, status: ProgressStatus
) -> bool:
    """``progress_status`` 列を更新する。

    Args:
        project_root: プロジェクトルートディレクトリ。
        meeting_id: 商談 ID。
        status: 新しい処理状態。

    Returns:
        bool: 該当行が存在し 1 行更新できた場合 True。
    """
    now = datetime.now().replace(microsecond=0).isoformat(timespec="seconds")
    with connect(project_root) as conn:
        cur = conn.execute(
            """
            UPDATE meetings
            SET progress_status = ?, updated_at = ?
            WHERE id = ?
            """,
            (status.value, now, meeting_id),
        )
        return cur.rowcount > 0


def update_meeting_summary(project_root: Path, meeting_id: int, summary: str) -> bool:
    """要約本文 ``summary`` 列を更新する（空文字も可）。

    あわせて ``updated_at`` を現在時刻（マイクロ秒付き ISO 8601）に更新する。

    Args:
        project_root: プロジェクトルートディレクトリ。
        meeting_id: 商談 ID。
        summary: 要約本文。

    Returns:
        bool: 該当行が存在し更新できた場合 True。該当 ID が無い場合は False。
    """
    now = datetime.now().isoformat(timespec="microseconds")
    with connect(project_root) as conn:
        cur = conn.execute(
            """
            UPDATE meetings
            SET summary = ?, updated_at = ?
            WHERE id = ?
            """,
            (summary, now, meeting_id),
        )
        return cur.rowcount > 0
