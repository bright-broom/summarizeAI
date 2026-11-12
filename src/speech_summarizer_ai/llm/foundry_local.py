"""Foundry Local 経由の要約（``foundry-local-sdk-winml``）。"""

from __future__ import annotations

import json
import re
import sys
import threading
import time
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from speech_summarizer_ai import settings as config
from speech_summarizer_ai.llm.prompts import (
    DEFAULT_MAP_EXTRACT_SYSTEM_PROMPT,
    DEFAULT_REFINE_SYSTEM_PROMPT,
    DEFAULT_SUMMARY_SYSTEM_PROMPT,
    DEFAULT_TITLE_SYSTEM_PROMPT,
    MAP_EXTRACT_RETRY_USER_SUFFIX,
)
from speech_summarizer_ai.platform_utils import paths


class FoundryLocalNotAvailableError(ImportError):
    """``foundry_local_sdk`` が未インストール、または読み込めない場合。"""


class FoundryLocalModelNotCachedError(RuntimeError):
    """``allow_download=False`` でキャッシュからの load が続けて失敗したとき。未配置以外（ロック等）も含む。"""


def _load_failure_user_hint(exc: BaseException) -> str:
    """モデルパス不存在エラー向けの補足ヒント文を返す。

    Args:
        exc: SDK が送出した例外。

    Returns:
        str: ヒント文字列。該当しない場合は空文字。
    """
    t = str(exc).replace("\r\n", "\n")
    if "Model path does not exist" not in t:
        return ""
    return (
        " ヒント: ログの「Failed to load model …」に出る完全な ID（例: "
        "qwen2.5-0.5b-instruct-generic-gpu:4）用のファイルが ``models/llm`` に無い状態です。"
        "短いエイリアスはマシンごとに別バリアントへ解決されます。"
        "``settings/llm.py`` の FOUNDRY_LLM_MODEL_ALIAS をその完全 ID に合わせるか、"
        "起動時の LLM 取得を再実行してください。"
    )


def _import_sdk() -> tuple[type, type]:
    """Foundry Local SDK を import し、設定型とマネージャ型を返す。

    Returns:
        tuple[type, type]: ``(Configuration, FoundryLocalManager)`` のクラスオブジェクト。

    Raises:
        FoundryLocalNotAvailableError: パッケージが未インストールまたは import できない場合。
    """
    try:
        from foundry_local_sdk import Configuration, FoundryLocalManager

        return Configuration, FoundryLocalManager
    except ImportError as e:
        raise FoundryLocalNotAvailableError(
            "Foundry Local SDK が見つかりません。\n"
            "pip install foundry-local-sdk-winml foundry-local-core-winml openai\n"
            "詳細: https://learn.microsoft.com/en-us/azure/foundry-local/get-started"
        ) from e


def _wrap_transcript_for_summary_user_message(transcript_body: str) -> str:
    """要約用 user メッセージ本文を組み立てる（文字起こし区画を明示する）。

    Args:
        transcript_body: 文字起こしプレーンテキスト。

    Returns:
        str: LLM に渡す user ロール本文。
    """
    body = transcript_body.strip()
    return (
        "次のセクションは会話の文字起こしです。あなたの応答ではこの文字起こしを"
        "一言一句写さず、内容だけを要約してください。\n\n"
        "---文字起こし本文---\n"
        f"{body}"
    )


def _wrap_structured_notes_for_summary_user_message(notes_body: str) -> str:
    """チャンク統合メモを要約用の user 本文に載せる。

    ``---文字起こし本文---`` 以降を根拠テキストとする点は ``summarize_transcript`` と同形式。

    Args:
        notes_body: チャンク抽出を種類別に統合し整形したプレーンテキスト。

    Returns:
        str: LLM に渡す user ロール本文。
    """
    body = notes_body.strip()
    return (
        "次のセクションは、会議のチャンクごとに抽出し種類別に統合した情報メモです。"
        "元の文字起こしのすべてが含まれているとは限りませんが、"
        "あなたのプロフェッショナルな要約の根拠としてこのメモだけを使ってください。\n"
        "メモの列挙・転記は禁止。同じ引用・決定・タスクを微妙に言い換えて繰り返すこと、"
        "「高い自信を持って」など同型の抽象表現の連発は禁止。重複は一つにまとめてください。\n\n"
        "---文字起こし本文---\n"
        f"{body}"
    )


def _merged_extract_to_plaintext_notes(merged: dict) -> str:
    """種類別に統合した dict を、要約向けの読みやすい日本語メモにする。

    Args:
        merged: :func:`_merge_chunk_extracts` の戻り値。

    Returns:
        str: 空でないセクションのみを含むプレーンテキスト。
    """
    lines: list[str] = []

    def _decision_line(d: dict) -> str:
        txt = str(d.get("content", "") or d.get("decision", "")).strip()
        if not txt:
            return ""
        sp = str(d.get("related_speaker", "") or d.get("speaker", "")).strip()
        return f"- {txt}" + (f"（{sp}）" if sp else "")

    def _action_line(a: dict) -> str:
        task = str(a.get("task", "")).strip()
        if not task:
            return ""
        owner = str(a.get("owner", "")).strip()
        due = str(a.get("due_date", "")).strip()
        bits = [task]
        if owner:
            bits.append(f"担当:{owner}")
        if due:
            bits.append(f"期限:{due}")
        return "- " + " / ".join(bits)

    mt = merged.get("main_topics") or []
    po = merged.get("purpose_overview") or []

    if po or mt:
        lines.append("【会話の目的または概要】")
        for p in po:
            if str(p).strip():
                lines.append(f"- {p}")
        for t in mt:
            if str(t).strip():
                lines.append(f"- （話題）{t}")
        lines.append("")

    decs = merged.get("decisions") or []
    if decs:
        lines.append("【合意・決定事項】")
        for d in decs:
            if not isinstance(d, dict):
                continue
            ln = _decision_line(d)
            if ln:
                lines.append(ln)
        lines.append("")

    actions = merged.get("action_items") or []
    if actions:
        lines.append("【次のアクション】")
        for a in actions:
            if not isinstance(a, dict):
                continue
            ln = _action_line(a)
            if ln:
                lines.append(ln)
        lines.append("")

    ois = merged.get("open_issues") or []
    rs = merged.get("risks") or []
    if ois or rs:
        lines.append("【未決の論点・リスク】")
        for x in ois:
            if str(x).strip():
                lines.append(f"- （論点）{x}")
        for x in rs:
            if str(x).strip():
                lines.append(f"- （リスク）{x}")
        lines.append("")

    for title, key in (
        ("【補足：重要な事実】", "key_facts"),
        ("【補足：注目発言】", "key_quotes"),
    ):
        rows = merged.get(key) or []
        if rows:
            lines.append(title)
            lines.extend(f"- {r}" for r in rows if str(r).strip())
            lines.append("")

    return "\n".join(lines).strip()


def _looks_like_transcript_echo(summary: str, raw_transcript: str) -> bool:
    """要約出力が文字起こしのコピーに見えるかどうかを返す。

    Args:
        summary: モデル出力。
        raw_transcript: 元の文字起こし。

    Returns:
        bool: コピーとみなせる場合 True。
    """
    s, r = summary.strip(), raw_transcript.strip()
    if not s or not r:
        return False
    if s == r:
        return True
    if len(r) < 40:
        return False
    if len(s) >= int(len(r) * 0.92) and s[:120] == r[:120]:
        return True
    return False


def _split_sentences_ja(text: str) -> list[str]:
    """日本語本文を文末記号でおおまかに文に分割する（繰り返し検出用）。

    Args:
        text: プレーンテキスト。

    Returns:
        list[str]: 空でない文の列（記号は各要素末尾に含まれる場合あり）。
    """
    t = text.strip()
    if not t:
        return []
    parts = re.split(r"(?<=[。．!?？！])\s*", t)
    return [p.strip() for p in parts if len(p.strip()) >= 8]


def _dedupe_consecutive_sentences(text: str) -> str:
    """連続して同一の文が並んでいる場合、1 つだけ残す。

    モデルが同一文を「。」区切りで連結した場合に後処理で軽減する。

    Args:
        text: 生のモデル出力。

    Returns:
        str: 連続重複を除いたテキスト。
    """
    sents = _split_sentences_ja(text)
    if len(sents) < 2:
        return text.strip()
    deduped: list[str] = []
    for s in sents:
        if deduped and deduped[-1] == s:
            continue
        deduped.append(s)
    return "".join(deduped)


def _strip_incomplete_trailing_sentence(text: str) -> str:
    """文末記号のない末尾（入力トークン上限で途中打ち切られた断片）を取り除く。

    「。」「！」「？」などで終わる部分だけを残し、ぶつ切りの末尾は捨てる。
    文末記号が一度も無ければ空文字を返す。

    Args:
        text: モデル出力または後処理済みテキスト。

    Returns:
        str: 完成した文のみを連結したテキスト。
    """
    t = text.strip()
    if not t:
        return ""
    if re.search(r"[。．!?？！]\s*$", t):
        return t
    last_end: int | None = None
    for m in re.finditer(r"[。．!?？！]", t):
        last_end = m.end()
    if last_end is None:
        return ""
    return t[:last_end].strip()


def _finalize_refine_segment(text: str) -> str:
    """Refine の 1 セグメントとして採用する前に適用する整形。

    Args:
        text: モデル出力。

    Returns:
        str: 連続重複除去後、未完の末尾を除いたテキスト。
    """
    return _strip_incomplete_trailing_sentence(_dedupe_consecutive_sentences(text))


def _has_excessive_repetition(
    text: str, *, threshold: float = 0.45, min_line_len: int = 15
) -> bool:
    """テキスト内に同一フレーズの反復ループがあるかを検出する。

    改行が少ない 1 段落出力でも、文末で分割した文単位の重複を検出する。

    Args:
        text: 検査対象テキスト。
        threshold: 非ユニーク行の割合がこれを超えると True（0〜1）。
        min_line_len: 重複判定に含める最短行長（文字数）。短すぎる行は除外。

    Returns:
        bool: 過剰な繰り返しがあれば True。
    """
    stripped = text.strip()
    if not stripped:
        return False

    lines = [
        ln.strip() for ln in stripped.splitlines() if len(ln.strip()) >= min_line_len
    ]
    if len(lines) >= 3:
        repetition_rate = 1.0 - len(set(lines)) / len(lines)
        if repetition_rate > threshold:
            return True

    sents = _split_sentences_ja(stripped)
    if len(sents) >= 4:
        uniq = len(set(sents))
        if uniq / len(sents) < 0.42:
            return True

    run = 1
    max_run = 1
    for i in range(1, len(sents)):
        if sents[i] == sents[i - 1]:
            run += 1
            max_run = max(max_run, run)
        else:
            run = 1
    if max_run >= 3:
        return True

    if len(sents) >= 6:
        most_common = Counter(sents).most_common(1)[0][1]
        if most_common >= 3:
            return True

    return False


def _extract_assistant_text_from_complete_chat(
    client: Any, messages: list[dict[str, str]]
) -> str:
    """``complete_chat`` の応答から assistant の本文を取り出す。

    Args:
        client: チャットクライアント。
        messages: 送受信メッセージ列。

    Returns:
        str: assistant のテキスト。取得できなければ空文字。
    """
    try:
        result = client.complete_chat(messages)
    except Exception:
        return ""
    choices = getattr(result, "choices", None) or []
    for choice in choices:
        msg = getattr(choice, "message", None)
        if msg is None:
            continue
        role = getattr(msg, "role", None)
        content = getattr(msg, "content", None)
        if role == "assistant" and isinstance(content, str) and content.strip():
            return content.strip()
    if choices:
        try:
            msg = choices[0].message
            c = getattr(msg, "content", None)
            if isinstance(c, str) and c.strip():
                return c.strip()
        except (IndexError, AttributeError):
            pass
    return ""


def _streaming_chat_aggregate(client: Any, messages: list[dict[str, str]]) -> str:
    """Foundry の ``complete_streaming_chat`` で本文を集約する。

    ストリームが空なら ``complete_chat`` から読み替える。

    Args:
        client: チャットクライアント（``complete_streaming_chat`` / ``complete_chat`` を実装）。
        messages: ``role`` と ``content`` を持つメッセージ列。

    Returns:
        str: assistant の出力テキスト（前後空白除去）。
    """

    def _delta_content(chunk: Any) -> str | None:
        try:
            delta = chunk.choices[0].delta
            return getattr(delta, "content", None) if delta is not None else None
        except (IndexError, AttributeError):
            return None

    parts: list[str] = []
    for chunk in client.complete_streaming_chat(messages):
        c = _delta_content(chunk)
        if c:
            parts.append(c)
    text = "".join(parts).strip()
    if not text:
        text = _extract_assistant_text_from_complete_chat(client, messages)
    return text


@dataclass(frozen=True)
class SummarizeResult:
    """要約 1 件分の結果。

    Attributes:
        text: 要約本文。
        model_alias: 使用したモデル別名。
    """

    text: str
    model_alias: str


@dataclass
class ChunkExtract:
    """Map フェーズで 1 チャンクから抽出した構造化情報。

    Attributes:
        chunk_index: チャンク番号（0 始まり）。
        chunk_title: この区間の主題。
        purpose_summary: この区間の会話の目的・ねらいまたは概要。
        main_topics: 話題一覧。
        decisions: 決定事項リスト（各要素は dict）。
        action_items: アクションアイテムリスト（各要素は dict）。
        open_issues: 未解決の問題。
        risks: リスク。
        key_facts: 重要な事実。
        key_quotes: 注目すべき発言。
    """

    chunk_index: int
    chunk_title: str
    purpose_summary: str
    main_topics: list[str]
    decisions: list[dict]
    action_items: list[dict]
    open_issues: list[str]
    risks: list[str]
    key_facts: list[str]
    key_quotes: list[str]


def format_transcript_lines(lines: Sequence[tuple[str, str]]) -> str:
    """``(時刻, 本文)`` を ``[時刻] 本文`` 形式のテキストに連結する。

    Args:
        lines: 段落の列。

    Returns:
        str: 改行区切り。本文が空の要素は除く。
    """
    parts: list[str] = []
    for ts, body in lines:
        t = str(ts).strip()
        b = str(body).strip()
        if not b:
            continue
        if t:
            parts.append(f"[{t}] {b}")
        else:
            parts.append(b)
    return "\n".join(parts)


# ── Map-Reduce ヘルパー ────────────────────────────────────────────────────────


def _parse_json_from_llm_output(text: str) -> dict:
    """LLM 出力から JSON オブジェクトを解析する。

    - 先頭の完全なオブジェクトだけ ``JSONDecoder.raw_decode`` で取る（後ろに説明文が付く場合に有効）。
    - Markdown の `` ```json `` ブロックにも対応する。

    Args:
        text: モデルの生出力。

    Returns:
        dict: 解析済み辞書。解析失敗時は空辞書。
    """

    def _one_object(s: str) -> dict | None:
        s = s.strip()
        if not s:
            return None
        try:
            v = json.loads(s)
            return v if isinstance(v, dict) else None
        except json.JSONDecodeError:
            pass
        i = s.find("{")
        if i == -1:
            return None
        dec = json.JSONDecoder()
        try:
            obj, _end = dec.raw_decode(s[i:])
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass
        j = s.rfind("}")
        if j > i:
            try:
                v = json.loads(s[i : j + 1])
                return v if isinstance(v, dict) else None
            except json.JSONDecodeError:
                pass
        return None

    t = text.strip()
    if not t:
        return {}

    m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", t)
    if m:
        got = _one_object(m.group(1))
        if got is not None:
            return got

    got = _one_object(t)
    return got if got is not None else {}


def _chunk_extract_from_dict(index: int, d: dict) -> ChunkExtract:
    """辞書から :class:`ChunkExtract` を生成する。キーが不足しても失敗しない。

    Args:
        index: チャンク番号。
        d: LLM 出力を解析した辞書。

    Returns:
        ChunkExtract: 抽出結果。
    """

    def _str_list(val: object) -> list[str]:
        if isinstance(val, list):
            return [str(v) for v in val if v]
        return []

    def _dict_list(val: object) -> list[dict]:
        if isinstance(val, list):
            return [v for v in val if isinstance(v, dict)]
        return []

    ps = str(d.get("purpose_summary", "") or d.get("purpose_or_overview", "")).strip()

    return ChunkExtract(
        chunk_index=index,
        chunk_title=str(d.get("chunk_title", f"チャンク {index + 1}")).strip(),
        purpose_summary=ps,
        main_topics=_str_list(d.get("main_topics")),
        decisions=_dict_list(d.get("decisions")),
        action_items=_dict_list(d.get("action_items")),
        open_issues=_str_list(d.get("open_issues")),
        risks=_str_list(d.get("risks")),
        key_facts=_str_list(d.get("key_facts")),
        key_quotes=_str_list(d.get("key_quotes")),
    )


def _merge_chunk_extracts(extracts: list[ChunkExtract]) -> dict:
    """全チャンクの抽出結果を種類別に統合し重複を除去する（Python のみ・LLM 不使用）。

    Args:
        extracts: 全チャンクの :class:`ChunkExtract` リスト。

    Returns:
        dict: 種類別に統合されたデータ。
            ``purpose_overview`` は各チャンクの ``purpose_summary`` の非重複リスト。
    """

    def _dedup_str_list(items: list[str]) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for item in items:
            key = item.strip().lower()
            if key and key not in seen:
                seen.add(key)
                out.append(item.strip())
        return out

    def _dedup_dict_list(items: list[dict]) -> list[dict]:
        seen: set[str] = set()
        out: list[dict] = []
        for item in items:
            key = json.dumps(item, ensure_ascii=False, sort_keys=True).lower()
            if key not in seen:
                seen.add(key)
                out.append(item)
        return out

    return {
        "purpose_overview": _dedup_str_list(
            [e.purpose_summary.strip() for e in extracts if e.purpose_summary.strip()]
        ),
        "main_topics": _dedup_str_list([t for e in extracts for t in e.main_topics]),
        "decisions": _dedup_dict_list([d for e in extracts for d in e.decisions]),
        "action_items": _dedup_dict_list([a for e in extracts for a in e.action_items]),
        "open_issues": _dedup_str_list([i for e in extracts for i in e.open_issues]),
        "risks": _dedup_str_list([r for e in extracts for r in e.risks]),
        "key_facts": _dedup_str_list([f for e in extracts for f in e.key_facts]),
        "key_quotes": _dedup_str_list([q for e in extracts for q in e.key_quotes]),
    }


def split_transcript_into_chunks(
    text: str,
    chunk_size: int,
    overlap: int,
) -> list[str]:
    """文字起こしテキストを改行境界でチャンク分割する（オーバーラップ付き）。

    行の途中では切らず、必ず行末をチャンク境界にする。
    テキスト全体が ``chunk_size`` 以内に収まる場合は要素 1 つのリストを返す。

    注意: 音声 VAD の無音区間は使わない。文字数と改行のみで分割する。

    Args:
        chunk_size: 1 チャンクあたりの最大文字数。
        overlap: 隣接チャンク間のオーバーラップ文字数（文脈の継続性を保つ）。
            ``chunk_size`` の 1/4 を超える場合は自動的に切り詰める。
        text: 分割対象テキスト。

    Returns:
        list[str]: チャンクリスト。空入力は空リスト。
    """
    stripped = text.strip()
    if not stripped:
        return []
    safe_overlap = min(overlap, max(chunk_size // 4, 0))
    lines = stripped.splitlines()
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for line in lines:
        line_len = len(line) + 1  # +1 for newline
        if current_len + line_len > chunk_size and current:
            chunks.append("\n".join(current))
            # オーバーラップ: 末尾から safe_overlap 文字分の行を引き継ぐ
            tail: list[str] = []
            tail_len = 0
            for prev_line in reversed(current):
                plen = len(prev_line) + 1
                if tail_len + plen > safe_overlap:
                    break
                tail.insert(0, prev_line)
                tail_len += plen
            current = tail + [line]
            current_len = sum(len(ln) + 1 for ln in current)
        else:
            current.append(line)
            current_len += line_len

    if current:
        chunks.append("\n".join(current))
    return chunks


def _wrap_refine_user_message(previous_summary: str, new_chunk: str) -> str:
    """Refine ステップ用の user メッセージを組み立てる。

    Args:
        previous_summary: 前ステップで生成された要約。
        new_chunk: 新しい文字起こしチャンク。

    Returns:
        str: LLM に渡す user ロール本文。
    """
    return (
        "---既存の要約---\n"
        f"{previous_summary.strip()}\n\n"
        "---追加の文字起こし---\n"
        f"{new_chunk.strip()}"
    )


def _wrap_transcript_for_title_user_message(transcript_body: str) -> str:
    """タイトル生成用 user メッセージ本文を組み立てる。

    Args:
        transcript_body: 文字起こしプレーンテキスト。

    Returns:
        str: LLM に渡す user ロール本文。
    """
    body = transcript_body.strip()
    return (
        "次のセクションは会話の文字起こしです。内容にふさわしい短いタイトルを"
        "1行だけ出力してください（説明文や「タイトル」という語は不要）。\n\n"
        "---文字起こし本文---\n"
        f"{body}"
    )


def sanitize_meeting_title(raw: str, *, max_chars: int | None = None) -> str:
    """LLM のタイトル出力を 1 行・長さ上限に揃える。

    Args:
        raw: 生文字列。
        max_chars: 上限。``None`` なら設定値。

    Returns:
        str: 整形結果。空入力は ``""``。
    """
    lim = max_chars if max_chars is not None else config.FOUNDRY_LLM_TITLE_MAX_CHARS
    s = raw.strip()
    if not s:
        return ""
    line = s.splitlines()[0].strip()
    for prefix in ("タイトル:", "タイトル：", "【", "■", "- ", "・"):
        if line.startswith(prefix):
            line = line[len(prefix) :].strip()
    line = line.strip("「」『』\"'")
    if len(line) > lim:
        line = line[: max(1, lim - 1)] + "…"
    return line


class FoundryLocalSummarizer:
    """Foundry Local チャットで要約する。

    マネージャはプロセス単位で 1 回初期化し、モデルハンドルはインスタンスごとに load / unload する。
    """

    _manager_lock = threading.Lock()
    _manager_initialized = False

    def __init__(
        self,
        *,
        model_alias: str = config.FOUNDRY_LLM_MODEL_ALIAS,
        app_name: str = config.FOUNDRY_LLM_APP_NAME,
        system_prompt: str | None = None,
        temperature: float = 0.3,
        max_tokens: int = 4096,
        project_root: Path | None = None,
    ) -> None:
        """インスタンスを初期化する。

        Args:
            model_alias: カタログ上のモデル別名。
            app_name: Foundry Local アプリ名。
            system_prompt: 要約用 system プロンプト。``None`` のとき既定の要約プロンプトを使う。
            temperature: チャット生成温度。
            max_tokens: チャット最大トークン。
            project_root: モデルキャッシュ等の基準パス。``None`` で自動解決。

        Returns:
            None
        """
        self._model_alias = model_alias
        self._app_name = app_name
        self._system_prompt = (
            system_prompt
            if system_prompt is not None
            else DEFAULT_SUMMARY_SYSTEM_PROMPT
        )
        self._temperature = temperature
        self._max_tokens = max_tokens
        root = project_root if project_root is not None else paths.project_root()
        if config.FOUNDRY_LLM_CACHE_IN_PROJECT:
            self._model_cache_dir = str(
                paths.foundry_llm_cache_directory(root).resolve()
            )
        else:
            self._model_cache_dir = None
        self._configuration: Any = None
        self._manager: Any = None
        self._model: Any = None
        self._loaded = False

    def _ensure_manager(self) -> None:
        """プロセス単位の Foundry Local マネージャを初期化し、インスタンスに紐付ける。

        Returns:
            None
        """
        Configuration, FoundryLocalManager = _import_sdk()
        with FoundryLocalSummarizer._manager_lock:
            if not FoundryLocalSummarizer._manager_initialized:
                if self._model_cache_dir is not None:
                    Path(self._model_cache_dir).mkdir(parents=True, exist_ok=True)
                cfg_kw: dict[str, Any] = {"app_name": self._app_name}
                if self._model_cache_dir is not None:
                    cfg_kw["model_cache_dir"] = self._model_cache_dir
                try:
                    self._configuration = Configuration(**cfg_kw)
                except TypeError:
                    # 古い SDK で ``model_cache_dir`` 未対応のときは従来どおり
                    print(
                        "[summarize] Foundry Local: model_cache_dir 非対応の SDK のため "
                        "既定キャッシュのみ使用します。",
                        flush=True,
                    )
                    self._configuration = Configuration(app_name=self._app_name)
                FoundryLocalManager.initialize(self._configuration)
                if self._model_cache_dir is not None:
                    print(
                        f"[summarize] Foundry Local model_cache_dir={self._model_cache_dir!r}",
                        flush=True,
                    )
                FoundryLocalSummarizer._manager_initialized = True
            self._manager = FoundryLocalManager.instance

    def _iter_family_variant_ids(self, catalog: Any) -> list[str]:
        """``list_models()`` から ``self._model_alias`` と同族のモデル ID を列挙する。

        Args:
            catalog: ``FoundryLocalManager.catalog``。

        Returns:
            list[str]: 重複のないモデル ID 一覧。取得に失敗した場合は空リスト。
        """
        family = self._model_alias.strip()
        try:
            entries = list(catalog.list_models())
        except Exception as e:
            print(
                f"[summarize] catalog.list_models() 失敗: {type(e).__name__}: {e}",
                file=sys.stderr,
                flush=True,
            )
            return []

        out: list[str] = []
        seen: set[str] = set()
        for entry in entries:
            mid = getattr(entry, "id", None)
            malias = getattr(entry, "alias", None)
            if not isinstance(mid, str) or not mid:
                continue
            matches = (
                malias == family
                or mid == family
                or mid.startswith(f"{family}-")
                or mid.startswith(f"{family}:")
            )
            if not matches:
                continue
            if mid in seen:
                continue
            seen.add(mid)
            out.append(mid)

        return out

    def load_model(
        self,
        *,
        download_eps: bool = True,
        allow_download: bool = True,
        ep_progress: Callable[[str, float], None] | None = None,
        model_download_progress: Callable[[float], None] | None = None,
    ) -> None:
        """モデルをロードする（キャッシュ候補の試行、必要ならダウンロード）。

        Args:
            download_eps: True のとき EP を取得・登録する。
            allow_download: False のときキャッシュのみ。候補がことごとく失敗すると
                :class:`FoundryLocalModelNotCachedError`。
            ep_progress: 任意。EP 名と進捗（0〜100）を渡すコールバック。
            model_download_progress: 任意。モデル DL 進捗（0〜100）を渡すコールバック。

        Returns:
            None
        """
        self._ensure_manager()
        assert self._manager is not None

        if download_eps:
            current_ep = ""

            def _ep_cb(ep_name: str, percent: float) -> None:
                nonlocal current_ep
                if ep_progress is not None:
                    ep_progress(ep_name, percent)
                else:
                    if ep_name != current_ep:
                        if current_ep:
                            print()
                        current_ep = ep_name
                    print(f"\r  {ep_name:<30}  {percent:5.1f}%", end="", flush=True)

            self._manager.download_and_register_eps(progress_callback=_ep_cb)
            if ep_progress is None and current_ep:
                print()

        catalog = self._manager.catalog

        def _mdl(progress: float) -> None:
            if model_download_progress is not None:
                model_download_progress(progress)
            else:
                print(
                    f"\rDownloading model: {progress:.2f}%",
                    end="",
                    flush=True,
                )

        def _apply_chat_client_settings() -> None:
            client = self._model.get_chat_client()
            client.settings.temperature = self._temperature
            client.settings.max_tokens = self._max_tokens

        def _resolved_id_of(model: Any, fallback: str) -> str:
            rid = getattr(model, "id", None)
            return rid if isinstance(rid, str) and rid else fallback

        def _try_load_variant(
            variant: str, *, retries: int = 0
        ) -> tuple[Any, BaseException | None]:
            """指定バリアントで ``get_model`` と ``load`` を試す。

            Args:
                variant: エイリアスまたは完全 ID。
                retries: 失敗時の追加リトライ回数。

            Returns:
                tuple[Any, BaseException | None]: 成功時は ``(ハンドル, None)``。失敗時は ``(None, 最後の例外)``。
            """
            last: BaseException | None = None
            for attempt in range(retries + 1):
                if attempt == 1:
                    time.sleep(0.25)
                elif attempt >= 2:
                    time.sleep(0.75)
                try:
                    handle = catalog.get_model(variant)
                    if handle is None:
                        raise RuntimeError("catalog.get_model が None を返した")
                    handle.load()
                    return handle, None
                except Exception as e:
                    last = e
                    print(
                        f"[summarize] LLM load() 失敗 "
                        f"(候補={variant!r}, 試行 {attempt + 1}/{retries + 1}): "
                        f"{type(e).__name__}: {e}",
                        file=sys.stderr,
                        flush=True,
                    )
            return None, last

        root_for_marker = paths.project_root()

        candidates: list[tuple[str, int]] = []  # (variant, extra retries)
        seen_candidates: set[str] = set()

        def _add_candidate(variant: str | None, retries: int) -> None:
            if not variant:
                return
            key = variant.strip()
            if not key or key in seen_candidates:
                return
            seen_candidates.add(key)
            candidates.append((key, retries))

        prev_resolved = paths.read_llm_resolved_id(root_for_marker, self._model_alias)

        # 1) 短いエイリアス（SDK が環境に合うバリアントを解決）。キャッシュ利用時はこれが最も安定。
        _add_candidate(self._model_alias, retries=2 if not allow_download else 0)

        # 2) マーカー記載の解決済み完全 ID は、models/llm に実体があるときだけ試す（カタログとパスがずれた ID の無駄打ちを避ける）
        if prev_resolved and paths.foundry_llm_resolved_weights_present(
            root_for_marker, prev_resolved
        ):
            _add_candidate(prev_resolved, retries=1)

        # 3) カタログから列挙したファミリー一致の他バリアント（環境差・コピー移送対策）
        for cid in self._iter_family_variant_ids(catalog):
            _add_candidate(cid, retries=0)

        last_err: BaseException | None = None
        loaded_variant: str | None = None
        for variant, retries in candidates:
            handle, err = _try_load_variant(variant, retries=retries)
            if err is None and handle is not None:
                self._model = handle
                self._loaded = True
                loaded_variant = variant
                last_err = None
                resolved = _resolved_id_of(handle, variant)
                print(
                    f"[summarize] LLM load 成功: 要求={variant!r} 解決 ID={resolved!r}",
                    flush=True,
                )
                try:
                    paths.write_llm_probe_marker(
                        root_for_marker, self._model_alias, resolved
                    )
                except OSError:
                    pass
                break
            last_err = err

        if last_err is None and loaded_variant is not None:
            _apply_chat_client_settings()
            return

        if not allow_download:
            cache_hint = self._model_cache_dir or "（Foundry SDK 既定キャッシュ）"
            hint = _load_failure_user_hint(last_err) if last_err is not None else ""
            tried = ", ".join(v for v, _ in candidates) or "(なし)"
            raise FoundryLocalModelNotCachedError(
                f"LLM モデル {self._model_alias!r} をキャッシュから load() できませんでした。"
                f"未ダウンロードの場合は起動時の要約モデル取得を完了してください。"
                f"取得済みでもファイルロック・ディスク・GPU/EP の一時エラーで失敗することがあります。"
                f" model_cache_dir={cache_hint!r}。"
                f" 試行候補: [{tried}]。"
                f" 直近の原因: {type(last_err).__name__ if last_err else 'NoError'}: {last_err}"
                f"{hint}"
            ) from last_err

        # ダウンロード経路: 短いエイリアスで取り直し、SDK に環境適合バリアントを選ばせる。
        download_handle = catalog.get_model(self._model_alias)
        download_handle.download(_mdl)
        if model_download_progress is None:
            print()
        download_handle.load()
        self._model = download_handle
        self._loaded = True

        resolved = _resolved_id_of(download_handle, self._model_alias)
        print(
            f"[summarize] LLM download 成功: alias={self._model_alias!r} 解決 ID={resolved!r}",
            flush=True,
        )
        try:
            paths.write_llm_probe_marker(root_for_marker, self._model_alias, resolved)
        except OSError:
            pass

        _apply_chat_client_settings()

    def download_model_weights_only(
        self,
        *,
        model_download_progress: Callable[[float], None] | None = None,
    ) -> None:
        """起動時ダイアログ用に、モデル重みのダウンロードだけ行う。

        実行プロバイダ（OpenVINO 等）の取得・登録（``download_and_register_eps``）は行わない。
        初回の要約などで :meth:`load_model` を呼んだときに EP 登録と ``load`` が行われる。

        Args:
            model_download_progress: モデル DL 進捗（0〜100）を受け取るコールバック。

        Returns:
            None: キャッシュディレクトリへ重みを取得する。

        Raises:
            FoundryLocalNotAvailableError: SDK が利用できない場合。
            Exception: カタログ取得や ``download`` の失敗。
        """
        self._ensure_manager()
        assert self._manager is not None

        catalog = self._manager.catalog

        def _mdl(progress: float) -> None:
            if model_download_progress is not None:
                model_download_progress(progress)
            else:
                print(
                    f"\rDownloading model: {progress:.2f}%",
                    end="",
                    flush=True,
                )

        download_handle = catalog.get_model(self._model_alias)
        download_handle.download(_mdl)
        if model_download_progress is None:
            print()
        print(
            f"[summarize] LLM weights download only (no EP): alias={self._model_alias!r}",
            flush=True,
        )

    def unload(self) -> None:
        """ロード済みモデルハンドルをアンロードする。

        SDK の ``unload()`` の後に ``self._model`` を ``None`` にして参照を外す。
        参照を残すとネイティブ側の重みが解放されても Python ラッパーが掴み続け、
        プロセスの作業セットが下がりにくい。

        Returns:
            None
        """
        if self._model is not None:
            if self._loaded:
                try:
                    self._model.unload()
                except Exception:
                    pass
            self._model = None
        self._loaded = False

    def generate_conversation_title(self, transcript: str) -> str:
        """文字起こしから一覧表示用の短いタイトルを生成する。

        Args:
            transcript: 文字起こし全文。

        Returns:
            str: 整形済みタイトル。入力が空なら空文字。

        Raises:
            RuntimeError: モデル未ロードの場合。
        """
        if not self._loaded or self._model is None:
            raise RuntimeError(
                "モデルが未ロードです。先に load_model() を呼び出してください。"
            )
        raw = transcript.strip()
        if not raw:
            print("[summarize] LLM title: skip (empty input)", flush=True)
            return ""

        system = DEFAULT_TITLE_SYSTEM_PROMPT
        user_message = _wrap_transcript_for_title_user_message(raw)
        messages: list[dict[str, str]] = [
            {"role": "system", "content": system},
            {"role": "user", "content": user_message},
        ]

        client = self._model.get_chat_client()
        prev_temp = getattr(client.settings, "temperature", self._temperature)
        prev_max = getattr(client.settings, "max_tokens", self._max_tokens)
        try:
            client.settings.temperature = 0.25
            client.settings.max_tokens = config.FOUNDRY_LLM_TITLE_MAX_TOKENS
            print(
                f"[summarize] LLM title: generating (model={self._model_alias}, "
                f"chars={len(raw)})…",
                flush=True,
            )

            def _delta_content(chunk: Any) -> str | None:
                try:
                    delta = chunk.choices[0].delta
                    return (
                        getattr(delta, "content", None) if delta is not None else None
                    )
                except (IndexError, AttributeError):
                    return None

            parts: list[str] = []
            for chunk in client.complete_streaming_chat(messages):
                c = _delta_content(chunk)
                if c:
                    parts.append(c)
            text = "".join(parts).strip()
            if not text:
                text = _extract_assistant_text_from_complete_chat(client, messages)
            out = sanitize_meeting_title(text)
            print(
                f"[summarize] LLM title: done (raw_len={len(text)}, title_len={len(out)})",
                flush=True,
            )
            return out
        finally:
            try:
                client.settings.temperature = prev_temp
                client.settings.max_tokens = prev_max
            except Exception:
                client.settings.temperature = self._temperature
                client.settings.max_tokens = self._max_tokens

    def summarize_transcript(
        self,
        transcript: str,
        *,
        extra_instructions: str | None = None,
        stream: bool = False,
        on_stream_chunk: Callable[[str], None] | None = None,
    ) -> SummarizeResult:
        """文字起こし全文を要約する。

        Args:
            transcript: 文字起こしテキスト（プレーン）。
            extra_instructions: システム指示に追加する一文（任意）。
            stream: True のときストリーミング生成。``on_stream_chunk`` に断片を渡す。
            on_stream_chunk: ストリーミング時のコールバック（文字列断片）。

        Returns:
            SummarizeResult: 要約テキストとモデル別名。ストリーミング時も結合結果を ``text`` に入れる。

        Raises:
            RuntimeError: モデル未ロードの場合。
        """
        if not self._loaded or self._model is None:
            raise RuntimeError(
                "モデルが未ロードです。先に load_model() を呼び出してください。"
            )

        raw_transcript = transcript.strip()
        if not raw_transcript:
            print("[summarize] LLM: skip (empty input after strip)", flush=True)
            return SummarizeResult(text="", model_alias=self._model_alias)

        if extra_instructions:
            system = (
                self._system_prompt.rstrip()
                + "\n\n追加の指示:\n"
                + extra_instructions.strip()
            )
        else:
            system = self._system_prompt

        user_message = _wrap_transcript_for_summary_user_message(raw_transcript)
        messages: list[dict[str, str]] = [
            {"role": "system", "content": system},
            {"role": "user", "content": user_message},
        ]

        client = self._model.get_chat_client()
        client.settings.temperature = self._temperature
        client.settings.max_tokens = self._max_tokens

        print(
            f"[summarize] LLM: generating (model={self._model_alias}, "
            f"transcript_chars={len(raw_transcript)}, stream={stream})…",
            flush=True,
        )

        def _delta_content(chunk: Any) -> str | None:
            try:
                delta = chunk.choices[0].delta
                return getattr(delta, "content", None) if delta is not None else None
            except (IndexError, AttributeError):
                return None

        # Foundry Local（WinML）では complete_chat がユーザー入力をそのまま返すことがあるため、
        # 非ストリーム時も complete_streaming_chat で集約する（fundry_test と同じ経路）。
        parts: list[str] = []
        for chunk in client.complete_streaming_chat(messages):
            content = _delta_content(chunk)
            if content:
                parts.append(content)
                if stream and on_stream_chunk is not None:
                    on_stream_chunk(content)
        text = "".join(parts).strip()

        # 万一ストリームが空ならcomplete_chatをフォールバック（抽出は assistant 優先）
        if not text:
            text = _extract_assistant_text_from_complete_chat(client, messages)

        # 文字起こし／ラップ済み user 全文のコピーとみなす場合はフォールバック再試行
        if _looks_like_transcript_echo(
            text, raw_transcript
        ) or _looks_like_transcript_echo(text, user_message):
            print(
                "[summarize] LLM: 出力が文字起こし全文に近いため、"
                "user単一メッセージでストリーム再試行します。",
                flush=True,
            )
            alt_messages: list[dict[str, str]] = [
                {
                    "role": "user",
                    "content": (
                        f"{system}\n\n{_wrap_transcript_for_summary_user_message(raw_transcript)}"
                    ),
                }
            ]
            parts2: list[str] = []
            for chunk in client.complete_streaming_chat(alt_messages):
                c = _delta_content(chunk)
                if c:
                    parts2.append(c)
            text = "".join(parts2).strip()
            if not text:
                text = _extract_assistant_text_from_complete_chat(client, alt_messages)

        print(
            f"[summarize] LLM: done (output_chars={len(text)}, "
            f"stream_mode={'callback' if stream else 'aggregate'})",
            flush=True,
        )
        return SummarizeResult(text=text, model_alias=self._model_alias)

    def summarize_transcript_lines(
        self,
        lines: Sequence[tuple[str, str]],
        **kwargs: Any,
    ) -> SummarizeResult:
        """時刻付き行を 1 テキストに整形してから要約する。

        Args:
            lines: ``(時刻, 本文)`` の列。
            **kwargs: :meth:`summarize_transcript` にそのまま渡す。

        Returns:
            SummarizeResult: :meth:`summarize_transcript` と同じ。
        """
        n = len(lines)
        body = format_transcript_lines(lines)
        print(
            f"[summarize] Formatted transcript: {n} raw line(s) -> "
            f"{len(body)} char(s) for LLM input",
            flush=True,
        )
        return self.summarize_transcript(body, **kwargs)

    def summarize_transcript_refine(
        self,
        transcript: str,
        *,
        chunk_size: int | None = None,
        chunk_overlap: int | None = None,
    ) -> SummarizeResult:
        """Refine 方式（分割要約）で文字起こしを要約する。

        文字起こし全文をチャンクに分割し、前の要約を引き継ぎながら逐次的に要約を更新する。
        チャンクが 1 つ（全文が ``chunk_size`` 以内）の場合は :meth:`summarize_transcript` に委譲する。

        Refine フロー::

            chunk₁ → 要約₁
            [要約₁ + chunk₂] → 要約₂
            …
            [要約ₙ₋₁ + chunkN] → 最終要約

        Args:
            transcript: 文字起こしテキスト。
            chunk_size: 1 チャンクあたりの最大文字数。``None`` のとき設定値を使う。
            chunk_overlap: チャンク間オーバーラップ文字数。``None`` のとき設定値を使う。

        Returns:
            SummarizeResult: 最終要約とモデル別名。

        Raises:
            RuntimeError: モデル未ロードの場合。
        """
        if not self._loaded or self._model is None:
            raise RuntimeError(
                "モデルが未ロードです。先に load_model() を呼び出してください。"
            )

        raw = transcript.strip()
        if not raw:
            return SummarizeResult(text="", model_alias=self._model_alias)

        cs = (
            chunk_size
            if chunk_size is not None
            else config.FOUNDRY_LLM_REFINE_CHUNK_SIZE
        )
        co = (
            chunk_overlap
            if chunk_overlap is not None
            else config.FOUNDRY_LLM_REFINE_CHUNK_OVERLAP
        )

        chunks = split_transcript_into_chunks(raw, cs, co)

        # 全文が 1 チャンクに収まる場合は通常の一括要約に委譲（未完文末も除去）
        if len(chunks) <= 1:
            one = self.summarize_transcript(raw)
            return SummarizeResult(
                text=_finalize_refine_segment(one.text),
                model_alias=one.model_alias,
            )

        print(
            f"[summarize] Refine: {len(chunks)} chunks "
            f"(chunk_size={cs}, overlap={co}, total_chars={len(raw)})",
            flush=True,
        )

        # Step 1: 最初のチャンクを通常の要約で処理
        current_summary = _finalize_refine_segment(
            self.summarize_transcript(chunks[0]).text
        )
        print(
            f"[summarize] Refine: chunk 1/{len(chunks)} done "
            f"(summary_chars={len(current_summary)})",
            flush=True,
        )

        def _delta_content(chunk: Any) -> str | None:
            try:
                delta = chunk.choices[0].delta
                return getattr(delta, "content", None) if delta is not None else None
            except (IndexError, AttributeError):
                return None

        client = self._model.get_chat_client()
        # Refine ステップ専用の設定:
        # - max_tokens: 小さすぎると句点手前で打ち切られる（設定: FOUNDRY_LLM_REFINE_MAX_TOKENS）
        # - temperature: 決定論的ループ緩和
        client.settings.max_tokens = config.FOUNDRY_LLM_REFINE_MAX_TOKENS
        client.settings.temperature = max(self._temperature, 0.5)
        try:
            if hasattr(client.settings, "top_p"):
                client.settings.top_p = 0.92
        except Exception:  # noqa: BLE001
            pass
        # 繰り返しペナルティを SDK が対応していれば設定する
        for _attr, _val in (("repetition_penalty", 1.15), ("frequency_penalty", 0.6)):
            try:
                if hasattr(client.settings, _attr):
                    setattr(client.settings, _attr, _val)
                    break
            except Exception:  # noqa: BLE001
                pass

        # Step 2〜N: 前の要約 + 新チャンク → 更新要約
        for i, chunk in enumerate(chunks[1:], start=2):
            messages: list[dict[str, str]] = [
                {"role": "system", "content": DEFAULT_REFINE_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": _wrap_refine_user_message(current_summary, chunk),
                },
            ]
            parts: list[str] = []
            for stream_chunk in client.complete_streaming_chat(messages):
                c = _delta_content(stream_chunk)
                if c:
                    parts.append(c)
            text = "".join(parts).strip()
            if not text:
                text = _extract_assistant_text_from_complete_chat(client, messages)
            finalized = _finalize_refine_segment(text)

            bad = _has_excessive_repetition(finalized) or _looks_like_transcript_echo(
                finalized, chunk
            )
            if bad:
                print(
                    f"[summarize] Refine: chunk {i}/{len(chunks)} - "
                    "低品質出力（繰り返しまたは文字起こしのコピー）を検出。このチャンクをスキップし前の要約を維持します。",
                    file=sys.stderr,
                    flush=True,
                )
            elif finalized:
                current_summary = finalized

            print(
                f"[summarize] Refine: chunk {i}/{len(chunks)} done "
                f"(summary_chars={len(current_summary)})",
                flush=True,
            )

        return SummarizeResult(
            text=_finalize_refine_segment(current_summary),
            model_alias=self._model_alias,
        )

    def summarize_transcript_map_reduce(
        self,
        transcript: str,
        *,
        chunk_size: int | None = None,
        on_progress: Callable[[str], None] | None = None,
    ) -> SummarizeResult:
        """構造化 Map-Reduce 方式で文字起こし全文を要約する。

        3 段階パイプライン:

        - **Phase 1 (Map)**: 各チャンクから構造化 JSON を抽出。
        - **Phase 2 (Merge)**: 種類別に統合・重複排除。
        - **Phase 3 (Write)**: 統合メモを要約し、最終議事録本文を生成する。

        Args:
            transcript: 文字起こし全文。
            chunk_size: 1 チャンクの最大文字数。``None`` で設定値を使用。
            on_progress: 進捗テキストを受け取るコールバック。

        Returns:
            SummarizeResult: 最終議事録と使用モデル別名。
        """
        if not self._loaded or self._model is None:
            raise RuntimeError(
                "モデルが未ロードです。先に load_model() を呼び出してください。"
            )

        raw = transcript.strip()
        if not raw:
            return SummarizeResult(text="", model_alias=self._model_alias)

        _size = chunk_size or config.FOUNDRY_LLM_MAP_CHUNK_SIZE
        chunks = split_transcript_into_chunks(raw, chunk_size=_size, overlap=0)
        if not chunks:
            return SummarizeResult(text="", model_alias=self._model_alias)

        client = self._model.get_chat_client()
        extracts: list[ChunkExtract] = []
        total = len(chunks)

        # ── Phase 1: Map（各チャンクから JSON 抽出）────────────────────────────
        for idx, chunk in enumerate(chunks):
            if on_progress:
                on_progress(f"[Map-Reduce] 情報抽出中 … チャンク {idx + 1}/{total}")
            print(
                f"[map-reduce] extract chunk {idx + 1}/{total} ({len(chunk)} chars)",
                flush=True,
            )

            client.settings.max_tokens = config.FOUNDRY_LLM_MAP_EXTRACT_MAX_TOKENS
            client.settings.temperature = 0.1

            user_msg = f"会議文字起こし:\n{chunk.strip()}"
            extract_messages: list[dict[str, str]] = [
                {"role": "system", "content": DEFAULT_MAP_EXTRACT_SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ]
            try:
                raw_text = _streaming_chat_aggregate(client, extract_messages)
            except Exception as exc:  # noqa: BLE001
                print(f"[map-reduce] extract error chunk {idx + 1}: {exc}", flush=True)
                extracts.append(
                    ChunkExtract(
                        chunk_index=idx,
                        chunk_title=f"チャンク {idx + 1}",
                        purpose_summary="",
                        main_topics=[],
                        decisions=[],
                        action_items=[],
                        open_issues=[],
                        risks=[],
                        key_facts=[],
                        key_quotes=[],
                    )
                )
                continue

            parsed = _parse_json_from_llm_output(raw_text)
            if not parsed:
                tail = raw_text[-200:] if len(raw_text) > 200 else raw_text
                print(
                    f"[map-reduce] JSON parse failed chunk {idx + 1} "
                    f"(len chars={len(raw_text)}):\n"
                    f"  head={raw_text[:160]!r}\n"
                    f"  tail={tail!r}",
                    flush=True,
                )
                client.settings.max_tokens = (
                    config.FOUNDRY_LLM_MAP_EXTRACT_RETRY_MAX_TOKENS
                )
                retry_user = user_msg.strip() + MAP_EXTRACT_RETRY_USER_SUFFIX
                retry_messages: list[dict[str, str]] = [
                    {"role": "system", "content": DEFAULT_MAP_EXTRACT_SYSTEM_PROMPT},
                    {"role": "user", "content": retry_user},
                ]
                print(
                    f"[map-reduce] extract retry chunk {idx + 1} "
                    f"(max_tokens={config.FOUNDRY_LLM_MAP_EXTRACT_RETRY_MAX_TOKENS})",
                    flush=True,
                )
                try:
                    raw_text = _streaming_chat_aggregate(client, retry_messages)
                    parsed = _parse_json_from_llm_output(raw_text)
                    if parsed:
                        print(
                            f"[map-reduce] JSON parse recovered chunk {idx + 1} after retry.",
                            flush=True,
                        )
                except Exception as exc2:  # noqa: BLE001
                    print(
                        f"[map-reduce] extract retry error chunk {idx + 1}: {exc2}",
                        flush=True,
                    )

            if not parsed:
                print(
                    f"[map-reduce] JSON still empty after retry chunk {idx + 1}.",
                    flush=True,
                )
            extracts.append(_chunk_extract_from_dict(idx, parsed))

        # ── Phase 2: Merge（種類別統合・重複排除）─────────────────
        if on_progress:
            on_progress("[Map-Reduce] 情報を統合中 …")
        merged = _merge_chunk_extracts(extracts)
        notes_plain = _merged_extract_to_plaintext_notes(merged)

        if not notes_plain.strip():
            print(
                "[map-reduce] 統合メモが空のため一括要約にフォールバックします。",
                flush=True,
            )
            fb = self.summarize_transcript(raw)
            return SummarizeResult(
                text=_finalize_refine_segment(fb.text),
                model_alias=self._model_alias,
            )

        # ── Phase 3: Write（要約 system プロンプトで最終本文を生成）────────────
        if on_progress:
            on_progress("[Map-Reduce] 最終議事録を生成中 …")
        print("[map-reduce] write final summary", flush=True)

        client.settings.max_tokens = config.FOUNDRY_LLM_MAP_WRITE_MAX_TOKENS
        client.settings.temperature = self._temperature

        write_user_msg = _wrap_structured_notes_for_summary_user_message(notes_plain)
        write_messages: list[dict[str, str]] = [
            {"role": "system", "content": self._system_prompt},
            {"role": "user", "content": write_user_msg},
        ]
        write_buf_text = ""
        try:
            write_buf_text = _streaming_chat_aggregate(client, write_messages)
        except Exception as exc:  # noqa: BLE001
            print(f"[map-reduce] write error: {exc}", flush=True)

        final_text = _finalize_refine_segment(write_buf_text)
        # 空、または同一フレーズの異常反復なら全文一括要約へフォールバック
        if (not final_text.strip()) or _has_excessive_repetition(final_text):
            print(
                "[map-reduce] 最終要約が空、または反復異常のため一括要約にフォールバックします。",
                flush=True,
            )
            fb = self.summarize_transcript(raw)
            final_text = _finalize_refine_segment(fb.text)

        return SummarizeResult(text=final_text, model_alias=self._model_alias)


def summarize_transcript_with_foundry_local(
    transcript: str,
    *,
    model_alias: str = config.FOUNDRY_LLM_MODEL_ALIAS,
    project_root: Path | None = None,
    load_model_kwargs: dict[str, Any] | None = None,
    **summarize_kwargs: Any,
) -> SummarizeResult:
    """1 回限りでモデルを load して要約し、unload するヘルパー。

    Args:
        transcript: 文字起こしテキスト。
        model_alias: モデル別名。
        project_root: プロジェクトルート。``None`` で自動。
        load_model_kwargs: :meth:`FoundryLocalSummarizer.load_model` に渡す引数。
        **summarize_kwargs: :meth:`FoundryLocalSummarizer.summarize_transcript` に渡す引数。

    Returns:
        SummarizeResult: 要約結果。
    """
    load_model_kwargs = load_model_kwargs or {}
    s = FoundryLocalSummarizer(model_alias=model_alias, project_root=project_root)
    try:
        s.load_model(**load_model_kwargs)
        return s.summarize_transcript(transcript, **summarize_kwargs)
    finally:
        s.unload()


def foundry_sdk_importable() -> bool:
    """Foundry Local SDK が import 可能かどうかを返す。

    Returns:
        bool: import に成功すれば True。
    """
    try:
        _import_sdk()
    except ImportError:
        return False
    return True


def probe_foundry_llm_ready(
    project_root: Path | None = None,
    *,
    model_alias: str | None = None,
) -> bool:
    """キャッシュのみ（追加 DL なし）でモデル load できるかを試す。

    SDK 未導入時は True を返す（起動ダイアログで LLM 必須にしないため）。

    Args:
        project_root: プロジェクトルート。``None`` で自動。
        model_alias: モデル別名。``None`` で設定値。

    Returns:
        bool: load に成功すれば True。未取得や失敗は False。
    """
    try:
        if model_alias is not None:
            s = FoundryLocalSummarizer(
                project_root=project_root, model_alias=model_alias
            )
        else:
            s = FoundryLocalSummarizer(project_root=project_root)
        s.load_model(download_eps=True, allow_download=False)
        s.unload()
        return True
    except FoundryLocalNotAvailableError:
        return True
    except FoundryLocalModelNotCachedError:
        return False
    except Exception:
        return False
