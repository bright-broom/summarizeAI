"""``models/stt`` へ Hugging Face から faster-whisper 重みを取得する（再開・バックオフ付き）。"""

from __future__ import annotations

import argparse
import asyncio
import errno
import logging
import math
import os
import random
import re
import time
import warnings
from collections.abc import Callable
from pathlib import Path

import httpx
from huggingface_hub import HfApi, hf_hub_url
from huggingface_hub.hf_api import RepoFile
from huggingface_hub.utils import filter_repo_objects

from speech_summarizer_ai import settings as config
from speech_summarizer_ai.stt.model_layout import (
    STT_STORAGE_FOLDER_NAMES,
    is_stt_model_directory_ready,
    stt_download_model_id,
)
from speech_summarizer_ai.platform_utils import paths

_STT_HF_REPO_IDS: dict[str, str] = {
    "tiny": "Systran/faster-whisper-tiny",
    "base": "Systran/faster-whisper-base",
    "small": "Systran/faster-whisper-small",
    "medium": "Systran/faster-whisper-medium",
    "large": "Systran/faster-whisper-large-v3",
}

_missing_hf = [f for f, _ in config.STT_MODEL_OPTIONS if f not in _STT_HF_REPO_IDS]
if _missing_hf:
    raise RuntimeError(
        "config.STT_MODEL_OPTIONS に含まれるフォルダに対し、download_stt_models._STT_HF_REPO_IDS "
        f"へ Hub リポジトリを追加してください。不足: {_missing_hf!r}"
    )

_SUPPRESSED_HF_AUTH_WARN = False

_READ_CHUNK_BYTES: int = 256 * 1024

# HTTP: resume + flaky network（同一ファイル内でリトライし、ハブ全体は Windows ロック以外も数回）
_HTTP_STREAM_ATTEMPTS: int = 8
_HTTP_RETRY_BASE_DELAY_S: float = 0.5
_HTTP_RETRY_MAX_DELAY_S: float = 30.0
_DOWNLOAD_OUTER_ATTEMPTS: int = 5

_HF_ALLOW_PATTERNS: list[str] = [
    "config.json",
    "preprocessor_config.json",
    "model.bin",
    "tokenizer.json",
    "vocabulary.*",
]


class _HFUnauthenticatedLogFilter(logging.Filter):
    """HF Hub の未認証リクエストに関するログ行を間引く。"""

    def filter(self, record: logging.LogRecord) -> bool:
        """ログレコードを通すかどうかを返す。

        Args:
            record: ログレコード。

        Returns:
            bool: 抑制対象なら False、それ以外は True。
        """
        msg = record.getMessage().lower()
        if "unauthenticated" in msg and "hf hub" in msg:
            return False
        return True


def _suppress_hf_unauthenticated_warning_once() -> None:
    """HF Hub 未認証に関する警告とログを、プロセス内で一度だけ抑制する。

    Returns:
        None
    """
    global _SUPPRESSED_HF_AUTH_WARN
    if _SUPPRESSED_HF_AUTH_WARN:
        return
    _SUPPRESSED_HF_AUTH_WARN = True
    warnings.filterwarnings(
        "ignore",
        message=r".*[Uu]nauthenticated requests to the HF Hub.*",
    )
    _lg = logging.getLogger("huggingface_hub")
    if not any(isinstance(f, _HFUnauthenticatedLogFilter) for f in _lg.filters):
        _lg.addFilter(_HFUnauthenticatedLogFilter())


def _repo_id_for_model_id(model_id: str) -> str:
    """STT モデル ID から Hugging Face の ``repo_id`` を解決する。

    ``org/name`` 形式ならそのまま返す。短い別名は ``_STT_HF_REPO_IDS`` で引く。

    Args:
        model_id: モデル別名（例: ``base``）または ``org/repo``。

    Returns:
        str: Hub 上のモデルリポジトリ ID。

    Raises:
        ValueError: 別名が登録に無い場合。
    """
    if re.match(r".*/.*", model_id):
        return model_id
    repo = _STT_HF_REPO_IDS.get(model_id)
    if repo is None:
        raise ValueError(
            f"不明な STT モデル ID: {model_id!r}。"
            f" ``config.STT_MODEL_OPTIONS`` のフォルダに対し ``_STT_HF_REPO_IDS`` にエントリを追加してください。"
            f"（登録済み repo キー: {', '.join(_STT_HF_REPO_IDS.keys())}）"
        )
    return repo


def _fetch_ordered_repo_files(api: HfApi, repo_id: str) -> tuple[str, list[RepoFile]]:
    """リポジトリのリビジョン SHA と、取得対象ファイルの順序付きリストを返す。

    ``_HF_ALLOW_PATTERNS`` でフィルタしたうえで ``filter_repo_objects`` の順に並べる。

    Args:
        api: ``HfApi`` インスタンス。
        repo_id: 対象モデルリポジトリ ID。

    Returns:
        tuple[str, list[RepoFile]]: ``(revision_sha, ordered_files)``。

    Raises:
        ValueError: SHA が取れない、または該当ファイルが無い場合。
    """
    repo_info = api.repo_info(repo_id=repo_id, repo_type="model")
    revision = repo_info.sha
    if revision is None:
        raise ValueError(f"repo_info.sha が取得できません: {repo_id!r}")

    files = [
        e
        for e in api.list_repo_tree(
            repo_id=repo_id,
            repo_type="model",
            revision=revision,
            recursive=True,
        )
        if isinstance(e, RepoFile)
    ]
    if not files:
        siblings = getattr(repo_info, "siblings", None) or []
        files = list(siblings)

    names = [f.rfilename for f in files]
    filtered_names = list(
        filter_repo_objects(items=names, allow_patterns=_HF_ALLOW_PATTERNS)
    )
    by_name = {f.rfilename: f for f in files}
    ordered = [by_name[n] for n in filtered_names if n in by_name]
    if not ordered:
        raise ValueError(
            f"Hub に該当ファイルがありません（allow_patterns）: {repo_id!r}"
        )
    return revision, ordered


def _session_byte_total(ordered: list[RepoFile]) -> int:
    """取得対象ファイルの合計バイト数を返す。

    Args:
        ordered: ダウンロード対象の ``RepoFile`` 列。

    Returns:
        int: 合計サイズ。いずれかのサイズが不明なら ``-1``。
    """
    sizes = [getattr(f, "size", None) for f in ordered]
    if any(s is None for s in sizes):
        return -1
    return int(sum(int(s) for s in sizes))


def estimate_hub_download_bytes_for_folder(folder_name: str) -> int:
    """指定 STT フォルダを Hub から取る際の、対象ファイル合計バイトの見積りを返す。

    Args:
        folder_name: ``models/stt`` 直下のフォルダ名（例: ``base``）。

    Returns:
        int: 合計バイト。サイズが一部不明な場合は ``-1``。
    """
    model_id = stt_download_model_id(folder_name)
    repo_id = _repo_id_for_model_id(model_id)
    _, ordered = _fetch_ordered_repo_files(HfApi(), repo_id)
    return _session_byte_total(ordered)


def _hf_request_headers() -> dict[str, str]:
    """HTTP リクエスト用の Hugging Face 認証ヘッダを返す。

    ``HF_TOKEN`` または ``huggingface-cli login`` で得たトークンがあれば ``Authorization`` を付与する。

    Returns:
        dict[str, str]: ヘッダ辞書。トークンが無ければ空に近い。
    """
    try:
        from huggingface_hub.utils import get_token

        token = get_token()
    except Exception:
        token = None
    h: dict[str, str] = {}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def _unlink_quiet(path: Path) -> None:
    """ファイルを削除する。存在しない・削除失敗時は無視する。

    Args:
        path: 削除対象パス。

    Returns:
        None
    """
    try:
        path.unlink()
    except OSError:
        pass


def _retry_after_seconds(response: httpx.Response | None) -> float | None:
    """``Retry-After`` ヘッダから待機秒を解釈する。

    Args:
        response: HTTP レスポンス。``None`` のときは ``None`` を返す。

    Returns:
        float | None: 待機秒。ヘッダが無いか解釈できなければ ``None``。
    """
    if response is None:
        return None
    h = response.headers.get("Retry-After")
    if not h:
        return None
    try:
        return float(h)
    except ValueError:
        return None


def _sleep_before_outer_retry(attempt_index: int) -> None:
    """ダウンロード一式の外側リトライ前に、指数バックオフ＋ジッタで待機する。

    Args:
        attempt_index: 外側の試行インデックス（1 から始まる想定）。

    Returns:
        None
    """
    delay = min(
        _HTTP_RETRY_MAX_DELAY_S,
        _HTTP_RETRY_BASE_DELAY_S * (2 ** (attempt_index - 1)),
    )
    jitter = delay * (0.8 + 0.4 * random.random())
    time.sleep(min(_HTTP_RETRY_MAX_DELAY_S, jitter))


def _http_retry_sleep_s(attempt_index: int, response: httpx.Response | None) -> float:
    """HTTP ストリーム失敗後の待機秒を返す。

    ``Retry-After`` があれば優先し、なければ指数バックオフ＋ジッタ。

    Args:
        attempt_index: ストリーム内の試行インデックス（1-origin。初回失敗後の待ちが 1）。
        response: 直近のレスポンス（``Retry-After`` 解釈用）。

    Returns:
        float: スリープ秒（上限 ``_HTTP_RETRY_MAX_DELAY_S``）。
    """
    ra = _retry_after_seconds(response)
    if ra is not None:
        return min(_HTTP_RETRY_MAX_DELAY_S, max(0.0, ra))
    base = min(
        _HTTP_RETRY_MAX_DELAY_S,
        _HTTP_RETRY_BASE_DELAY_S * (2 ** (attempt_index - 1)),
    )
    jitter = base * (0.8 + 0.4 * random.random())
    return min(_HTTP_RETRY_MAX_DELAY_S, jitter)


def _is_retryable_http_status(code: int) -> bool:
    """HTTP ステータスが一時的エラーとして再試行に値するか。

    Args:
        code: HTTP ステータスコード。

    Returns:
        bool: 再試行対象なら True。
    """
    return code in (408, 425, 429, 500, 502, 503, 504)


def _transient_download_exception(exc: BaseException) -> bool:
    """ダウンロード失敗がネットワーク等の一過性とみなせるか。

    Args:
        exc: 捕捉した例外。

    Returns:
        bool: 再試行してよさそうなら True。
    """
    if isinstance(
        exc,
        (
            httpx.TimeoutException,
            httpx.ConnectError,
            httpx.ReadError,
            httpx.WriteError,
            httpx.PoolTimeout,
            httpx.RemoteProtocolError,
            httpx.StreamError,
            httpx.NetworkError,
        ),
    ):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return _is_retryable_http_status(exc.response.status_code)
    return False


def _prepare_incomplete_tmp(tmp: Path, expected_size: int | None) -> int:
    """部分ダウンロード用 ``.incomplete`` ファイルから再開バイト位置を決める。

    Args:
        tmp: ``*.incomplete`` パス。
        expected_size: 最終ファイルの期待サイズ。不明なら ``None``。

    Returns:
        int: 再開オフセット（バイト）。``0`` は先頭から。``-1`` はサイズ一致済みで改名のみ。
    """
    if not tmp.is_file():
        return 0
    partial = tmp.stat().st_size
    if expected_size is None:
        _unlink_quiet(tmp)
        return 0
    if partial > expected_size:
        _unlink_quiet(tmp)
        return 0
    if partial == expected_size:
        return -1
    return partial


class _UiProgressGate:
    """進捗コールバックを間引く（総量不明時はバイト幅、総量既知時は 1% 刻みなど）。"""

    _UNKNOWN_EMIT_STRIDE_BYTES = 512 * 1024

    def __init__(
        self,
        on_progress: Callable[[int, int, str], None],
        session_total: int,
        *,
        smooth_percent_steps: bool,
    ) -> None:
        """ゲートを初期化する。

        Args:
            on_progress: ``(current_bytes, total_bytes_or_-1, description)`` を受け取るコールバック。
            session_total: セッション全体のバイト合計。``0`` 以下は不明扱い。
            smooth_percent_steps: True のときパーセントが変わったときだけ通知するなど滑らかにする。

        Returns:
            None
        """
        self._on_progress = on_progress
        self._session_total = session_total
        self._smooth = smooth_percent_steps
        self._last_percent = -1
        self._last_desc: str | None = None
        self._last_unknown_emit_cur = -1

    def emit(self, current: int, desc: str) -> None:
        """現在の累積バイトと説明文に応じて ``on_progress`` を呼ぶ。

        Args:
            current: セッション全体での累積転送バイト目安。
            desc: 現在のファイル名など表示用文字列。

        Returns:
            None
        """
        total_i = self._session_total
        cur = min(max(0, current), total_i) if total_i > 0 else max(0, current)

        if total_i <= 0:
            if desc != self._last_desc:
                self._last_desc = desc
                self._last_unknown_emit_cur = cur
                self._on_progress(cur, -1, desc)
                return
            if self._last_unknown_emit_cur < 0:
                self._last_unknown_emit_cur = cur
                self._on_progress(cur, -1, desc)
                return
            if cur - self._last_unknown_emit_cur >= self._UNKNOWN_EMIT_STRIDE_BYTES:
                self._last_unknown_emit_cur = cur
                self._on_progress(cur, -1, desc)
            return

        if not self._smooth:
            self._on_progress(cur, total_i, desc)
            return

        if desc != self._last_desc:
            self._last_desc = desc
            self._on_progress(cur, total_i, desc)

        pct = min(100, math.floor(cur * 100 / total_i))
        if pct != self._last_percent:
            self._last_percent = pct
            self._on_progress(cur, total_i, desc)


def _rename_with_retries(src: Path, dst: Path) -> None:
    """``os.replace`` でリネームする。Windows の一時ロック時は指数バックオフで再試行する。

    Args:
        src: 元パス。
        dst: 先パス。

    Returns:
        None

    Raises:
        OSError: 再試行上限後も失敗した場合。
    """
    last: BaseException | None = None
    for attempt in range(12):
        try:
            os.replace(src, dst)
            return
        except OSError as e:
            last = e
            if attempt < 11 and _is_transient_windows_file_lock_error(e):
                time.sleep(0.05 * (2**attempt))
                continue
            raise
    if last:
        raise last


def _is_transient_windows_file_lock_error(exc: BaseException) -> bool:
    """Windows 上のファイルロック等、外側リトライに値するエラーか。

    Args:
        exc: 例外。

    Returns:
        bool: 一過性とみなせるなら True。
    """
    if isinstance(exc, PermissionError):
        return True
    if isinstance(exc, OSError):
        if getattr(exc, "winerror", None) == 32:
            return True
        if exc.errno in (errno.EACCES, errno.EPERM):
            return True
    lower = str(exc).lower()
    return "being used by another process" in lower or "winerror 32" in lower


def _append_bytes(path: Path, data: bytes, truncate: bool) -> None:
    """バイナリをファイルに追記または上書きする（同期 I/O。スレッドプールから呼ばれる）。

    Args:
        path: 出力パス。
        data: 書き込むバイト列。
        truncate: True のとき ``wb`` で開き先頭から書く。

    Returns:
        None
    """
    mode = "wb" if truncate else "ab"
    with open(path, mode) as f:
        f.write(data)


async def _download_one_file_async(
    client: httpx.AsyncClient,
    url: str,
    dest: Path,
    *,
    expected_size: int | None,
    after_chunk: Callable[[int], None] | None,
    file_base_offset: int,
) -> int:
    """1 ファイルを HTTP GET で取得し ``dest`` に保存する（レンジ再開・リトライ付き）。

    Args:
        client: ``httpx`` 非同期クライアント。
        url: 取得 URL。
        dest: 最終保存パス。
        expected_size: 期待ファイルサイズ。``None`` のときサイズ検証は緩い。
        after_chunk: チャンクごとにセッション全体の累積バイトを通知する任意コールバック。
        file_base_offset: セッション内でのこのファイル開始前の累積バイト。

    Returns:
        int: この呼び出しで新規に転送したバイト数。既に完備でスキップした場合は ``0``。

    Raises:
        RuntimeError: レンジ無視やサイズ不一致が繰り返される、リトライ上限など。
        httpx.HTTPError: 再試行不能な HTTP エラー。
    """
    if (
        expected_size is not None
        and dest.is_file()
        and dest.stat().st_size == expected_size
    ):
        return 0

    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".incomplete")

    resume_from = _prepare_incomplete_tmp(tmp, expected_size)
    if resume_from == -1:
        _rename_with_retries(tmp, dest)
        return int(expected_size) if expected_size is not None else dest.stat().st_size

    attempt = 0
    soft_range_restarts = 0
    size_mismatch_loops = 0
    while attempt < _HTTP_STREAM_ATTEMPTS:
        attempt += 1
        try:
            while True:
                req_headers: dict[str, str] = {}
                if resume_from > 0:
                    req_headers["Range"] = f"bytes={resume_from}-"

                async with client.stream("GET", url, headers=req_headers) as response:
                    sc = response.status_code

                    if resume_from > 0:
                        if sc == 200:
                            await response.aread()
                            soft_range_restarts += 1
                            if soft_range_restarts > 24:
                                raise RuntimeError(
                                    f"サーバが Range を繰り返し無視しています: {dest.name!r}"
                                )
                            _unlink_quiet(tmp)
                            resume_from = 0
                            break
                        if sc == 416:
                            await response.aread()
                            if (
                                expected_size is not None
                                and resume_from >= expected_size
                            ):
                                _rename_with_retries(tmp, dest)
                                return expected_size
                            _unlink_quiet(tmp)
                            resume_from = 0
                            break
                        if sc != 206:
                            await response.aread()
                            response.raise_for_status()
                    else:
                        if sc >= 400:
                            await response.aread()
                        response.raise_for_status()

                    downloaded = resume_from
                    first_chunk = resume_from == 0
                    async for chunk in response.aiter_bytes(_READ_CHUNK_BYTES):
                        if not chunk:
                            continue
                        await asyncio.to_thread(_append_bytes, tmp, chunk, first_chunk)
                        first_chunk = False
                        downloaded += len(chunk)
                        if after_chunk is not None:
                            after_chunk(file_base_offset + downloaded)

                    if expected_size is not None:
                        got = tmp.stat().st_size
                        if got != expected_size:
                            size_mismatch_loops += 1
                            if size_mismatch_loops > 32:
                                raise RuntimeError(
                                    f"サイズ不一致が繰り返されます: {dest.name!r} "
                                    f"expected {expected_size} got {got}"
                                )
                            _unlink_quiet(tmp)
                            resume_from = 0
                            continue
                    _rename_with_retries(tmp, dest)
                    if expected_size is not None:
                        return expected_size
                    return dest.stat().st_size

        except Exception as exc:
            resp: httpx.Response | None = getattr(exc, "response", None)
            if isinstance(exc, httpx.HTTPStatusError):
                resp = exc.response
            if not _transient_download_exception(exc):
                raise

            if tmp.is_file():
                resume_from = tmp.stat().st_size
                if expected_size is not None:
                    if resume_from > expected_size:
                        _unlink_quiet(tmp)
                        resume_from = 0
                    elif resume_from == expected_size:
                        try:
                            _rename_with_retries(tmp, dest)
                            return expected_size
                        except OSError:
                            pass

            if attempt >= _HTTP_STREAM_ATTEMPTS:
                raise
            await asyncio.sleep(_http_retry_sleep_s(attempt, resp))

    raise RuntimeError(f"ダウンロードのリトライ上限に達しました: {url!r}")


async def _download_repository_http_async(
    repo_id: str,
    revision: str,
    ordered: list[RepoFile],
    target: Path,
    session_total: int,
    on_progress: Callable[[int, int, str], None] | None,
    *,
    smooth_percent_steps: bool,
) -> None:
    """モデルリポジトリの必要ファイルを HTTP で ``target`` 以下に展開する（非同期）。

    Args:
        repo_id: Hugging Face リポジトリ ID。
        revision: コミット SHA。
        ordered: 取得する ``RepoFile`` の順序付きリスト。
        target: ルートディレクトリ（例: ``models/stt/base``）。
        session_total: 進捗用の合計バイト（不明時は ``0`` 以下）。
        on_progress: 進捗コールバック。``None`` で通知なし。
        smooth_percent_steps: :class:`_UiProgressGate` に渡す間引きフラグ。

    Returns:
        None
    """
    headers = _hf_request_headers()
    timeout = httpx.Timeout(600.0, connect=60.0, pool=60.0)
    gate = (
        _UiProgressGate(
            on_progress, session_total, smooth_percent_steps=smooth_percent_steps
        )
        if on_progress is not None
        else None
    )

    async with httpx.AsyncClient(
        timeout=timeout,
        headers=headers,
        follow_redirects=True,
        limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
    ) as client:
        offset = 0
        for rf in ordered:
            rel = rf.rfilename
            url = hf_hub_url(
                repo_id=repo_id,
                filename=rel,
                repo_type="model",
                revision=revision,
            )
            dest = target / rel
            sz = getattr(rf, "size", None)

            if gate is not None:
                gate.emit(offset, rel)

            if sz is not None and dest.is_file() and dest.stat().st_size == int(sz):
                offset += int(sz)
                if session_total > 0:
                    offset = min(offset, session_total)
                if gate is not None:
                    gate.emit(offset, rel)
                continue

            def _after_chunk(global_so_far: int) -> None:
                if gate is None:
                    return
                cur = global_so_far
                if session_total > 0:
                    cur = min(cur, session_total)
                gate.emit(cur, rel)

            written = await _download_one_file_async(
                client,
                url,
                dest,
                expected_size=int(sz) if sz is not None else None,
                after_chunk=_after_chunk if gate is not None else None,
                file_base_offset=offset,
            )
            offset += written if written > 0 else (int(sz) if sz is not None else 0)
            if session_total > 0:
                offset = min(offset, session_total)
            if gate is not None:
                gate.emit(offset, rel)

    if gate is not None and session_total > 0:
        gate.emit(session_total, "")


def _download_repository_http(
    repo_id: str,
    revision: str,
    ordered: list[RepoFile],
    target: Path,
    session_total: int,
    on_progress: Callable[[int, int, str], None] | None,
    *,
    smooth_percent_steps: bool,
) -> None:
    """:func:`_download_repository_http_async` を ``asyncio.run`` で同期的に実行する。

    引数の意味は非同期版と同じ。

    Returns:
        None
    """
    asyncio.run(
        _download_repository_http_async(
            repo_id,
            revision,
            ordered,
            target,
            session_total,
            on_progress,
            smooth_percent_steps=smooth_percent_steps,
        )
    )


def download_stt_model(
    project_root: Path,
    folder_name: str,
    *,
    on_progress: Callable[[int, int, str], None] | None = None,
    smooth_percent_steps: bool = True,
) -> Path:
    """1 種類の STT モデルを Hub から取得し ``models/stt/<folder>`` に配置する。

    ネットワーク・Windows ロックなど一過性エラー時は外側で数回リトライする。

    Args:
        project_root: プロジェクトルート。
        folder_name: ``models/stt`` 直下のフォルダ名。
        on_progress: 任意。``(current, total_or_-1, description)``。
        smooth_percent_steps: 進捗通知を間引くか。

    Returns:
        Path: モデルが配置されたディレクトリ。

    Raises:
        ValueError: モデル ID が解決できない、Hub にファイルが無い等。
        OSError: リトライ後もファイル操作に失敗した場合。
        RuntimeError: ダウンロードが完了しなかった場合。
    """
    _suppress_hf_unauthenticated_warning_once()
    model_id = stt_download_model_id(folder_name)
    repo_id = _repo_id_for_model_id(model_id)
    target = paths.stt_model_directory(project_root, folder_name)
    target.mkdir(parents=True, exist_ok=True)

    api = HfApi()
    revision, ordered = _fetch_ordered_repo_files(api, repo_id)
    session_total = _session_byte_total(ordered)

    for attempt in range(_DOWNLOAD_OUTER_ATTEMPTS):
        try:
            _download_repository_http(
                repo_id,
                revision,
                ordered,
                target,
                session_total,
                on_progress,
                smooth_percent_steps=smooth_percent_steps,
            )
            return target
        except Exception as e:
            if attempt < _DOWNLOAD_OUTER_ATTEMPTS - 1 and (
                _is_transient_windows_file_lock_error(e)
                or _transient_download_exception(e)
            ):
                _sleep_before_outer_retry(attempt + 1)
                continue
            raise


def download_all_stt_models(project_root: Path) -> dict[str, Path]:
    """登録済みすべての STT モデル（tiny〜large 等）を順にダウンロードする。

    Args:
        project_root: プロジェクトルート。

    Returns:
        dict[str, Path]: フォルダ名から配置パスへの対応。
    """
    out: dict[str, Path] = {}
    for name in STT_STORAGE_FOLDER_NAMES:
        out[name] = download_stt_model(project_root, name)
    return out


def list_stt_model_status(project_root: Path) -> dict[str, bool]:
    """各 STT フォルダが認識実行に十分な状態かを返す。

    Args:
        project_root: プロジェクトルート。

    Returns:
        dict[str, bool]: フォルダ名をキーに、配置済みなら True。
    """
    return {
        name: is_stt_model_directory_ready(
            paths.stt_model_directory(project_root, name)
        )
        for name in STT_STORAGE_FOLDER_NAMES
    }


def main() -> None:
    """``python -m speech_summarizer_ai.stt.model_downloader`` 用の CLI エントリ。

    ``--model`` または ``--all`` で取得する。

    Returns:
        None
    """
    _suppress_hf_unauthenticated_warning_once()

    parser = argparse.ArgumentParser(
        description="faster-whisper モデルを models/stt/<size> にダウンロードする。",
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=None,
        help="リポジトリルート（省略時はパッケージから自動解決）",
    )
    parser.add_argument(
        "--model",
        choices=[*STT_STORAGE_FOLDER_NAMES],
        default=None,
        help="1 種類だけ取得する場合に指定（省略時は --all と同じ）",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="tiny から large まですべてダウンロードする",
    )
    args = parser.parse_args()
    root = args.project_root if args.project_root is not None else paths.project_root()

    if args.all:
        paths = download_all_stt_models(root)
        for k, p in paths.items():
            print(f"{k}: {p}")
    elif args.model is not None:
        p = download_stt_model(root, args.model)
        print(p)
    else:
        parser.error("--model <name> または --all を指定してください。")


if __name__ == "__main__":
    main()
