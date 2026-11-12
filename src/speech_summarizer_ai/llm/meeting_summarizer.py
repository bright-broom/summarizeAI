"""DB の ``paragraph_list``（文字起こし行）を入力に Foundry Local でタイトル・要約を生成する。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from speech_summarizer_ai.data import meetings_repository as meetings_db
from speech_summarizer_ai.llm.foundry_local import (
    FoundryLocalSummarizer,
    format_transcript_lines,
)


@dataclass(frozen=True)
class MeetingLlmOutcome:
    """LLM による会話タイトルと要約。"""

    title: str
    summary: str


def summarize_meeting_from_paragraphs(
    project_root: Path,
    meeting_id: int,
    summarizer: FoundryLocalSummarizer,
) -> MeetingLlmOutcome:
    """``meetings.paragraph_list`` 相当の行からタイトルと要約本文を生成する。

    文字起こし全文を構造化 Map-Reduce 方式（抽出 → 統合 → 生成）で処理する。
    タイトルは最終要約から生成し、長大な文字起こしを LLM に再送するコストを避ける。

    Args:
        project_root: プロジェクトルート。
        meeting_id: 商談 ID。
        summarizer: 既に ``load_model`` 済みの :class:`FoundryLocalSummarizer`。

    Returns:
        MeetingLlmOutcome: タイトル（空の場合あり）と要約。行が無い／DB に無いときは空文字。
    """
    rec = meetings_db.get_meeting(project_root, meeting_id)
    if rec is None:
        return MeetingLlmOutcome(title="", summary="")

    body = format_transcript_lines(rec.transcript_lines)

    # Map-Reduce 方式で要約（抽出 → 統合 → 生成）
    result = summarizer.summarize_transcript_map_reduce(body)

    # タイトルは最終要約から生成（全文の再送を避けてメモリ効率を高める）
    title_source = result.text if result.text else body
    title = summarizer.generate_conversation_title(title_source)

    return MeetingLlmOutcome(title=title.strip(), summary=result.text)
