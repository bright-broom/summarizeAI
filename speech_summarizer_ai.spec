# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec: Windows 用 GUI 実行ファイルを生成する。

ビルド例（リポジトリルートで、仮想環境を有効化したうえで）::

    pyinstaller --noconfirm speech_summarizer_ai.spec

成果物: **単一の** ``dist/SpeechSummarizerAI.exe``（onefile）。初回起動時に一時フォルダへ展開するため、
起動が onedir 版より遅くなることがあります。配布はこの EXE 1 ファイルで足ります。

データベース・モデル・セッションは Windows ではユーザーデータ領域に作成される
（WinRT ``ApplicationData.local_folder``、または未パッケージ時は
``%LOCALAPPDATA%\\WEEL\\SpeechSummarizerAI``。``platform_utils.paths.project_root()``）。

起動時セットアップは ``speech_summarizer_ai.ui.dialogs.startup_ai_models``（STT + Foundry LLM）。

ビルドは **本リポジトリ用の仮想環境** で行い、``webrtcvad-wheels`` が ``import webrtcvad`` できること
（``requirements.txt`` / ``pip install -e .``）を確認してください。別プロジェクトの venv だと hook が失敗します。

``packaging/pyinstaller_hooks`` を ``hookspath`` で先に渡し、contrib の ``hook-webrtcvad`` より
リポジトリ同梱の hook を優先します。
"""
from __future__ import annotations

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

_block_cipher = None
_root = Path(SPECPATH)
_icon_path = _root / "resources" / "icons" / "app.ico"
_pyi_hooks = _root / "packaging" / "pyinstaller_hooks"

datas: list[tuple[str, str]] = []
if (_root / "resources").is_dir():
    datas.append((str(_root / "resources"), "resources"))

# Foundry Local SDK はコードから import されないネイティブ依存（WinML Core / ORT / ORT-GenAI）を
# importlib で site-packages から探索する。PyInstaller 単体では取り込まれないため明示する。
_binaries_extra: list[tuple[str, str]] = []
_foundry_hidden: list[str] = []
_foundry_native_pkgs = (
    "foundry_local_core_winml",
    "onnxruntime_core",
    "onnxruntime_genai_core",
)
for _pkg in _foundry_native_pkgs:
    try:
        _d, _b, _h = collect_all(_pkg)
        datas.extend(_d)
        _binaries_extra.extend(_b)
        _foundry_hidden.extend(_h)
    except Exception:
        pass

# Conda 等: ``_ctypes`` が ``Library\\bin\\ffi*.dll``、標準配布が ``DLLs\\*.dll`` に依存することがある。
_dll_search_dirs = [
    Path(sys.base_prefix) / "DLLs",
    Path(sys.base_prefix) / "Library" / "bin",
]
_dll_names = (
    "ffi.dll",
    "ffi-8.dll",
    "ffi-7.dll",
    "libexpat.dll",
    "sqlite3.dll",
    "liblzma.dll",
    "LIBBZ2.dll",
    "libmpdec-4.dll",
)
for _d in _dll_search_dirs:
    if not _d.is_dir():
        continue
    for _nm in _dll_names:
        _p = _d / _nm
        if _p.is_file():
            _t = (str(_p), ".")
            if _t not in _binaries_extra:
                _binaries_extra.append(_t)

# 遅延 import や PyInstaller の静的解析で落ちるサブパッケージを明示する。
_hiddenimports = [
    "speech_summarizer_ai.app",
    "speech_summarizer_ai.ui.recording_overlay",
    "speech_summarizer_ai.ui.windows.recording_hud",
    "speech_summarizer_ai.controllers",
    "speech_summarizer_ai.controllers.recording_controller",
    "speech_summarizer_ai.ui.icons",
    "speech_summarizer_ai.ui.icons.action_icons",
    "speech_summarizer_ai.ui.windows",
    "speech_summarizer_ai.ui.windows.meeting_summary_list",
    "speech_summarizer_ai.ui.windows.meeting_detail",
    "speech_summarizer_ai.ui.dialogs",
    "speech_summarizer_ai.ui.dialogs.startup_ai_models",
    "speech_summarizer_ai.ui.widgets",
    "speech_summarizer_ai.ui.widgets.record_control_button",
    "speech_summarizer_ai.ui.theme",
    "speech_summarizer_ai.ui.theme.theme_basics",
    "speech_summarizer_ai.ui.theme.palette",
    "speech_summarizer_ai.ui.theme.qss",
    "speech_summarizer_ai.ui.theme.qss.popups",
    "speech_summarizer_ai.ui.theme.qss.scrollbars",
    "speech_summarizer_ai.ui.theme.qss.components",
    "speech_summarizer_ai.platform_utils.single_instance",
    "speech_summarizer_ai.platform_utils.paths",
    "speech_summarizer_ai.settings",
    "speech_summarizer_ai.settings.audio",
    "speech_summarizer_ai.settings.llm",
    "speech_summarizer_ai.settings.paths",
    "speech_summarizer_ai.settings.stt",
    "speech_summarizer_ai.domain.meeting",
    "speech_summarizer_ai.data.schema",
    "speech_summarizer_ai.data.meetings_repository",
    "speech_summarizer_ai.llm",
    "speech_summarizer_ai.llm.foundry_local",
    "speech_summarizer_ai.llm.meeting_summarizer",
    "speech_summarizer_ai.stt",
    "speech_summarizer_ai.stt.model_downloader",
    "speech_summarizer_ai.stt.model_layout",
    "speech_summarizer_ai.stt.realtime",
    "speech_summarizer_ai.stt.faster_whisper_engine",
    "speech_summarizer_ai.audio",
    "speech_summarizer_ai.audio.backend",
    "pyaudiowpatch",
    "webrtcvad",
    "numpy",
    "ctranslate2",
    "faster_whisper",
    "tqdm",
    "huggingface_hub",
    "av",
    "openai",
    "foundry_local_sdk",
    *_foundry_native_pkgs,
]
_hiddenimports.extend(_foundry_hidden)
try:
    _hiddenimports.extend(collect_submodules("foundry_local_sdk"))
except Exception:
    pass
try:
    _hiddenimports.extend(collect_submodules("winrt"))
except Exception:
    pass
_hiddenimports = list(dict.fromkeys(_hiddenimports))

a = Analysis(
    [str(_root / "src" / "speech_summarizer_ai" / "__main__.py")],
    pathex=[str(_root / "src")],
    binaries=_binaries_extra,
    datas=datas,
    hiddenimports=_hiddenimports,
    hookspath=[str(_pyi_hooks)] if _pyi_hooks.is_dir() else [],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=_block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=_block_cipher)

# onedir: 成果物は dist/SpeechSummarizerAI/SpeechSummarizerAI.exe + 同フォルダの DLL 群
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
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(_icon_path) if _icon_path.is_file() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="SpeechSummarizerAI",
)
