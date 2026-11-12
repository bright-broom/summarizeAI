"""faster-whisper 用モデル ID と ``models/stt/<folder>`` のフォルダ名の対応。

``speech_summarizer_ai.settings`` の ``STT_MODEL_OPTIONS`` をソースに、
UI / CLI 表記の正規化・ダウンロード API 向け ID・ローカル配置の妥当性判定を行う。
"""

from __future__ import annotations

from pathlib import Path

from speech_summarizer_ai import settings as config


def _build_model_aliases() -> dict[str, str]:
    """``config.STT_MODEL_OPTIONS`` から、表記ゆれを解決するルックアップを構築する。

    各エントリについて、保存フォルダ名（小文字）と UI ラベル（小文字）の両方をキーにし、
    値は正規のフォルダ名（小文字）とする。オプション集合に ``large`` が含まれるときだけ、
    キー ``large-v3`` を ``large`` にマップする。

    Returns:
        dict[str, str]: 小文字キーから正規フォルダ名（小文字）への写像。
    """
    out: dict[str, str] = {}
    for folder, label in config.STT_MODEL_OPTIONS:
        f = folder.strip().lower()
        out[f] = f
        out[label.strip().lower()] = f
    folders = {folder for folder, _ in config.STT_MODEL_OPTIONS}
    if "large" in folders:
        out["large-v3"] = "large"
    return out


# リポジトリ直下 models/stt/<name> の <name>（``config.STT_MODEL_OPTIONS`` の第 1 要素）
STT_STORAGE_FOLDER_NAMES: tuple[str, ...] = tuple(
    folder for folder, _ in config.STT_MODEL_OPTIONS
)

# ``resolve_whisper_model_name`` 用。起動時に一度だけ構築する。
_MODEL_ALIASES: dict[str, str] = _build_model_aliases()


def resolve_whisper_model_name(name: str) -> str:
    """UI や略称から faster-whisper / ``download_model`` 用のサイズ ID に正規化する。

    ``large`` は内部で ``large-v3`` 相当の重みに解決される（faster-whisper の ``large`` キー）。

    Args:
        name: 例 ``"Base"``, ``"large"``, ``"medium"``。

    Returns:
        str: ``tiny`` / ``base`` / … / ``large`` など。
    """
    key = name.strip().lower()
    return _MODEL_ALIASES.get(key, name.strip())


def canonical_stt_folder_name(model_size: str) -> str:
    """``models/stt/<folder>`` に使うフォルダ名を返す。

    Args:
        model_size: モデル指定（``Tiny`` / ``large-v3`` 等）。

    Returns:
        str: ``config.STT_MODEL_OPTIONS`` に含まれるフォルダ名。

    Raises:
        ValueError: 上記にマップできない場合。
    """
    w = resolve_whisper_model_name(model_size)
    if w == "large-v3":
        w = "large"
    if w in STT_STORAGE_FOLDER_NAMES:
        return w
    raise ValueError(
        f"ローカル STT レイアウト未対応のモデル: {model_size!r} "
        f"(対応: {', '.join(STT_STORAGE_FOLDER_NAMES)})"
    )


def stt_download_model_id(folder_name: str) -> str:
    """``download_model`` に渡すサイズ文字列（``large`` は Hub 上で v3 に解決される）。

    Args:
        folder_name: ``tiny`` … ``large``（``STT_STORAGE_FOLDER_NAMES`` のいずれか）。

    Returns:
        str: faster-whisper の ``download_model`` 向け ID。

    Raises:
        ValueError: 不明なフォルダ名の場合。
    """
    name = folder_name.strip().lower()
    if name not in STT_STORAGE_FOLDER_NAMES:
        raise ValueError(
            f"不明な STT フォルダ名: {folder_name!r} "
            f"(期待: {', '.join(STT_STORAGE_FOLDER_NAMES)})"
        )
    return name


def is_stt_model_directory_ready(model_dir: Path) -> bool:
    """ローカルディレクトリに CTranslate2 の Whisper 重みがあるか（簡易チェック）。

    Args:
        model_dir: 例 ``.../models/stt/base``。

    Returns:
        bool: ``model.bin`` が存在すれば ``True``。
    """
    return model_dir.is_dir() and (model_dir / "model.bin").is_file()
