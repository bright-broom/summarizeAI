# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec: macOS 用 ``Speech Summarizer AI.app`` を生成する。

ビルドは ``./scripts/build_mac_app.sh`` から行う（Mac 上・``.venv`` 有効化済みで）::

    pyinstaller --noconfirm --clean speech_summarizer_ai_mac.spec

成果物: ``dist/Speech Summarizer AI.app``

データベース・モデル・セッションは ``~/Library/Application Support/WEEL/SpeechSummarizerAI``、
ログは ``~/Library/Logs/SpeechSummarizerAI.log`` に作られる（.app 内には書き込まない）。
"""
from __future__ import annotations

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules, copy_metadata

APP_NAME = "Speech Summarizer AI"
BUNDLE_ID = "jp.weel.speechsummarizerai"

try:
    from speech_summarizer_ai import __version__ as APP_VERSION
except Exception:
    APP_VERSION = "0.1.1"

_root = Path(SPECPATH)
_icon_path = _root / "resources" / "icons" / "app.icns"
_pyi_hooks = _root / "packaging" / "pyinstaller_hooks"

datas: list[tuple[str, str]] = [(str(_root / "resources"), "resources")]
binaries: list[tuple[str, str]] = []
hiddenimports: list[str] = []


def _collect(pkg: str) -> None:
    try:
        d, b, h = collect_all(pkg)
    except Exception as e:  # noqa: BLE001
        print(f"[spec] collect_all({pkg!r}) skipped: {e}")
        return
    datas.extend(d)
    binaries.extend(b)
    hiddenimports.extend(h)


# MLX（Metal カーネル .metallib / dylib を含む）、mlx-lm（モデル定義を動的 import）、
# 音声系・Whisper 系のネイティブ依存を丸ごと取り込む。
for _pkg in (
    "mlx",
    "mlx_lm",
    "sounddevice",
    "_sounddevice_data",
    "ctranslate2",
    "faster_whisper",
    "tokenizers",
    "sentencepiece",
    "jinja2",
):
    _collect(_pkg)

# transformers は巨大なため、トークナイザ・設定まわりだけ取り込む（mlx-lm はトークナイザのみ使用）。
try:
    hiddenimports.extend(
        collect_submodules(
            "transformers",
            filter=lambda n: (
                ".models." not in n
                or n.rsplit(".", 1)[-1].startswith(("tokenization_", "configuration_"))
                or n.endswith(".models.auto")
                or ".models.auto." in n
            )
            and ".commands" not in n
            and "modeling_" not in n
            and ".pipelines" not in n,
        )
    )
except Exception as e:  # noqa: BLE001
    print(f"[spec] transformers submodules skipped: {e}")

# importlib.metadata でバージョン確認されるパッケージのメタデータ。
for _dist in (
    "speech-summarizer-ai",  # アプリ自身のバージョン（自動アップデートの比較に使う）
    "transformers",
    "tokenizers",
    "huggingface-hub",
    "safetensors",
    "numpy",
    "tqdm",
    "regex",
    "requests",
    "packaging",
    "filelock",
    "pyyaml",
    "mlx",
    "mlx-lm",
    "faster-whisper",
    "ctranslate2",
    "sounddevice",
    "webrtcvad-wheels",
    "jinja2",
):
    try:
        datas.extend(copy_metadata(_dist))
    except Exception:  # noqa: BLE001
        pass

hiddenimports += [
    *collect_submodules("speech_summarizer_ai"),
    "webrtcvad",
    "numpy",
    "huggingface_hub",
    "httpx",
    "av",
    "tqdm",
]
hiddenimports = list(dict.fromkeys(hiddenimports))

a = Analysis(
    [str(_root / "src" / "speech_summarizer_ai" / "__main__.py")],
    pathex=[str(_root / "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[str(_pyi_hooks)] if _pyi_hooks.is_dir() else [],
    hooksconfig={},
    runtime_hooks=[],
    # Windows 専用・不要な大物を除外してサイズを抑える。
    excludes=[
        "pyaudiowpatch",
        "winrt",
        "foundry_local_sdk",
        "torch",
        "tensorflow",
        "jax",
        "tkinter",
        "matplotlib",
        "IPython",
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
        "PySide6.Qt3DCore",
        "PySide6.QtQuick3D",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="SpeechSummarizerAI",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,  # ビルドした Mac のアーキテクチャ（Apple Silicon なら arm64）
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="SpeechSummarizerAI",
)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name=f"{APP_NAME}.app",
        icon=str(_icon_path) if _icon_path.is_file() else None,
        bundle_identifier=BUNDLE_ID,
        version=APP_VERSION,
        info_plist={
            "CFBundleName": APP_NAME,
            "CFBundleDisplayName": APP_NAME,
            "CFBundleShortVersionString": APP_VERSION,
            "CFBundleVersion": APP_VERSION,
            "CFBundleDevelopmentRegion": "ja",
            "LSMinimumSystemVersion": "13.0",
            "LSApplicationCategoryType": "public.app-category.productivity",
            "NSHighResolutionCapable": True,
            "NSRequiresAquaSystemAppearance": False,
            # マイク許可ダイアログに表示される説明（無いとマイク入力が無音になる）。
            "NSMicrophoneUsageDescription": (
                "会議や通話の音声を録音し、リアルタイムで文字起こしするためにマイクを使用します。"
                "音声はこの Mac の中だけで処理され、外部には送信されません。"
            ),
        },
    )
