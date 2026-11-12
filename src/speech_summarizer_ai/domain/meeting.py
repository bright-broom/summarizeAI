"""商談のドメイン型と一覧・詳細向けの表示用ヘルパ。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum

# 一覧カード上の要約プレビューに使う最大文字数（カードでは最大 2 行に省略表示）。
LIST_CARD_SUMMARY_PREVIEW_LEN: int = 90

_WEEKDAYS_JA = ("月", "火", "水", "木", "金", "土", "日")

# Markdown の装飾記号（見出し・箇条書き・強調・引用・コード）を取り除くための正規表現。
_MD_LINE_PREFIX = re.compile(r"^\s{0,3}(?:#{1,6}\s+|[-*+]\s+|\d+[.)]\s+|>\s?)")
_MD_INLINE = re.compile(r"(\*\*|__|`)")


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
    s = " ".join(strip_markdown(str(summary)).split())
    if not s:
        return ""
    if len(s) <= max_len:
        return s
    return s[:max_len] + "…"


def strip_markdown(text: str) -> str:
    """一覧プレビュー等のために Markdown の装飾記号を取り除いた平文を返す。

    見出し行（``## 概要`` など）は本文の区切りでしかないため、プレビューでは落とす。

    Args:
        text: Markdown を含みうる文字列。

    Returns:
        str: 装飾を除いた文字列（行構造は保持）。
    """
    out: list[str] = []
    for line in str(text).splitlines():
        if re.match(r"^\s{0,3}#{1,6}\s", line):
            continue
        line = _MD_LINE_PREFIX.sub("", line)
        line = _MD_INLINE.sub("", line)
        out.append(line)
    return "\n".join(out)


def _parse_iso(iso_ts: str) -> datetime | None:
    try:
        return datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def format_created_at_relative(iso_ts: str, *, today: date | None = None) -> str:
    """一覧カード用の相対日時（「今日 13:30」「昨日 16:00」「11/10(月) 09:15」）。

    Args:
        iso_ts: DB の ``created_at``。
        today: 基準日（テスト用）。``None`` で現在日付。

    Returns:
        str: 表示文字列。パースできない場合は引数をそのまま返す。
    """
    dt = _parse_iso(iso_ts)
    if dt is None:
        return iso_ts
    base = today or date.today()
    hm = dt.strftime("%H:%M")
    delta = (base - dt.date()).days
    if delta == 0:
        return f"今日 {hm}"
    if delta == 1:
        return f"昨日 {hm}"
    wd = _WEEKDAYS_JA[dt.weekday()]
    if dt.year == base.year:
        return f"{dt.month}/{dt.day}({wd}) {hm}"
    return f"{dt.year}/{dt.month}/{dt.day}({wd}) {hm}"


def _hms_to_seconds(ts: str) -> int | None:
    parts = ts.strip().split(":")
    if not 2 <= len(parts) <= 3 or not all(p.isdigit() for p in parts):
        return None
    nums = [int(p) for p in parts]
    if len(nums) == 2:
        nums = [0, *nums]
    return nums[0] * 3600 + nums[1] * 60 + nums[2]


def transcript_duration_label(lines: tuple[tuple[str, str], ...]) -> str:
    """文字起こし先頭〜末尾の時刻差から「約12分」のような長さを返す。

    Args:
        lines: ``(時刻, 本文)`` の列。

    Returns:
        str: 長さの表示文字列。算出できない場合は空文字。
    """
    if len(lines) < 2:
        return ""
    a = _hms_to_seconds(lines[0][0])
    b = _hms_to_seconds(lines[-1][0])
    if a is None or b is None:
        return ""
    sec = b - a
    if sec < 0:
        sec += 24 * 3600
    if sec < 60:
        return "1分未満"
    m = round(sec / 60)
    if m < 60:
        return f"約{m}分"
    return f"約{m // 60}時間{m % 60:02d}分"


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
    dt = _parse_iso(record.created_at)
    if dt is not None:
        when = f"{dt.year}/{dt.month}/{dt.day}({_WEEKDAYS_JA[dt.weekday()]}) {dt:%H:%M}"
    else:
        when = format_created_at_for_display(record.created_at)
    parts = [when]
    dur = transcript_duration_label(record.transcript_lines)
    if dur:
        parts.append(dur)
    if record.transcript_lines:
        parts.append(f"発言 {len(record.transcript_lines)}件")
    return "  ·  ".join(parts)
