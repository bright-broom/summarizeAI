"""一覧・詳細の表示用ヘルパ（相対日時・Markdown 除去・所要時間）のテスト。"""

from __future__ import annotations

from datetime import date

from speech_summarizer_ai.domain.meeting import (
    MeetingDetailRecord,
    ProgressStatus,
    format_created_at_relative,
    header_meta_for_detail,
    strip_markdown,
    summary_preview_for_list_card,
    transcript_duration_label,
)

TODAY = date(2026, 11, 12)  # 木曜日


def test_relative_dates() -> None:
    assert format_created_at_relative("2026-11-12T13:30:00", today=TODAY) == "今日 13:30"
    assert format_created_at_relative("2026-11-11T16:00:00", today=TODAY) == "昨日 16:00"
    assert format_created_at_relative("2026-11-09T09:15:00", today=TODAY) == "11/9(月) 09:15"
    assert format_created_at_relative("2025-12-01T09:00:00", today=TODAY) == "2025/12/1(月) 09:00"
    assert format_created_at_relative("not-a-date", today=TODAY) == "not-a-date"


def test_preview_drops_markdown_syntax() -> None:
    md = "## 概要\n予算を **確認** した。\n\n## 決定事項\n- 10%増額\n1. 採用開始"
    assert strip_markdown(md).split() == ["予算を", "確認", "した。", "10%増額", "採用開始"]
    preview = summary_preview_for_list_card(md)
    assert "#" not in preview and "**" not in preview and not preview.startswith("-")


def test_duration_label() -> None:
    assert transcript_duration_label(()) == ""
    assert transcript_duration_label((("10:00:05", "a"), ("10:00:40", "b"))) == "1分未満"
    assert transcript_duration_label((("10:00:05", "a"), ("10:12:40", "b"))) == "約13分"
    assert transcript_duration_label((("23:50:00", "a"), ("01:05:00", "b"))) == "約1時間15分"
    assert transcript_duration_label((("x", "a"), ("y", "b"))) == ""


def test_detail_meta() -> None:
    rec = MeetingDetailRecord(
        id=1,
        title="t",
        summary="",
        transcript_lines=(("10:00:00", "a"), ("10:30:00", "b")),
        created_at="2026-11-12T10:00:00",
        updated_at="2026-11-12T10:30:00",
        progress_status=ProgressStatus.SUCCESS,
    )
    assert header_meta_for_detail(rec) == "2026/11/12(木) 10:00  ·  約30分  ·  発言 2件"
