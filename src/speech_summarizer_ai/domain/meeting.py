"""商談のドメイン型と一覧・詳細向けの表示用ヘルパ。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

# 一覧カード上の要約プレビューに使う最大文字数。
LIST_CARD_SUMMARY_PREVIEW_LEN: int = 50


class ProgressStatus(str, Enum):
    """商談の処理状態（DB の ``meetings.progress_status`` 列と一致する値）。"""

    RECORDING = "recording"
    SUMMARIZING = "summarizing"
    SUCCESS = "success"
    FAILED = "failed"


@dataclass(frozen=True)
class MeetingListRow:
    """商談一覧の 1 行分のデータ。

    Attributes:
        id: 主キー。
        created_at: 作成日時（ISO 形式文字列。一覧の日時表示に用いる）。
        title: 一覧に表示するタイトル。
        summary_preview: 要約本文の先頭（:data:`LIST_CARD_SUMMARY_PREVIEW_LEN` 文字まで、無ければ空）。
        summarized: 要約または段落が存在するかどうか。
        progress_status: 処理状態。
    """

    id: int
    created_at: str
    title: str
    summary_preview: str
    summarized: bool
    progress_status: ProgressStatus


@dataclass(frozen=True)
class MeetingDetailRecord:
    """商談詳細画面用の完全レコード。

    Attributes:
        id: 主キー。
        title: タイトル。
        summary: 要約本文。
        transcript_lines: ``(時刻, 本文)`` のタプル列。
        created_at: 作成日時（ISO 形式文字列）。
        updated_at: 更新日時（ISO 形式文字列）。
        progress_status: 処理状態。
    """

    id: int
    title: str
    summary: str
    transcript_lines: tuple[tuple[str, str], ...]
    created_at: str
    updated_at: str
    progress_status: ProgressStatus


def summary_preview_for_list_card(
    summary: str,
    max_len: int = LIST_CARD_SUMMARY_PREVIEW_LEN,
) -> str:
    """一覧カード用に要約文の先頭を短く整形する（改行は空白に潰す）。

    Args:
        summary: 要約本文。
        max_len: 最大文字数。

    Returns:
        str: 整形後の文字列。元が空なら空文字、``max_len`` 超過時は末尾に ``…`` を付ける。
    """
    s = " ".join(str(summary).split())
    if not s:
        return ""
    if len(s) <= max_len:
        return s
    return s[:max_len] + "…"


def format_created_at_for_display(iso_ts: str) -> str:
    """``created_at`` の ISO 文字列を一覧カード等用 ``YYYY/MM/DD HH:MM`` に整形する。

    Args:
        iso_ts: DB の ``created_at``（例 ``2026-03-19T15:00:00``）。

    Returns:
        str: 整形結果。パースできない場合は引数をそのまま返す。
    """
    try:
        dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
        return dt.strftime("%Y/%m/%d %H:%M")
    except ValueError:
        return iso_ts


def header_meta_for_detail(record: MeetingDetailRecord) -> str:
    """詳細画面ヘッダに表示するメタ文字列（作成日時のみ）を組み立てる。

    Args:
        record: 商談詳細レコード。

    Returns:
        str: 表示用メタ文字列。
    """
    return f"作成 {format_created_at_for_display(record.created_at)}"
