"""起動時に STT 不足分と必要なら Foundry LLM を取得する。

LLM 取得ダイアログの要否は **3 ステップのファイル存在確認** のみで決め、Foundry SDK での load 試行は行わない。

1. ``models/llm/.speech_summarizer_llm_probe_ok`` の有無
2. マーカー 2 行目の解決済みモデル ID 読み取り
3. ``models/llm/`` 以下の対応パスに ``model.onnx`` が存在するか
"""

from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import QObject, QSettings, QThread, Qt, Signal, Slot
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QLabel,
    QMessageBox,
    QProgressBar,
    QVBoxLayout,
)

from speech_summarizer_ai import settings as config
from speech_summarizer_ai.llm.foundry_local import (
    FoundryLocalNotAvailableError,
    FoundryLocalSummarizer,
    foundry_sdk_importable,
)
from speech_summarizer_ai.stt.model_downloader import (
    download_stt_model,
    list_stt_model_status,
)
from speech_summarizer_ai.stt.model_layout import STT_STORAGE_FOLDER_NAMES
from speech_summarizer_ai.ui.theme import (
    DEFAULT_UI_DARK_UNSAVED,
    stt_model_setup_dialog_qss,
)
from speech_summarizer_ai.platform_utils import paths


def _is_transient_cancel_download_error(message: str) -> bool:
    """エラーメッセージが「一時的なキャンセル系失敗」かを判定する。

    Foundry 側から返る ``Operation was cancelled`` / ``Download was cancelled`` のような
    失敗を検出し、自動再試行すべきかどうかを決めるために使う。

    Args:
        message: 例外の文字列表現（``str(exception)``）。

    Returns:
        bool: キャンセル系失敗として扱い、自動再試行してよい場合 True。
    """
    t = message.casefold()
    if "cancel" not in t:
        return False
    return "download" in t or "operation" in t


def _cancel_retry_backoff_seconds(attempt_one_based: int) -> int:
    """キャンセル系失敗の再試行前に待つ秒数を返す。

    Args:
        attempt_one_based: 現在の試行回数（1 始まり）。

    Returns:
        int: 次の再試行までの待機秒数。
    """
    k = max(attempt_one_based - 1, 0)
    return min(12, 2 ** min(k, 4))


def _format_bytes(n: int) -> str:
    """バイト数を読みやすい文字列にする。

    Args:
        n: バイト数。負値は「不明」として ``"—"`` を返す。

    Returns:
        str: 単位付きの表記（例 ``"1.25 MiB"``）。
    """
    if n < 0:
        return "—"
    x = float(n)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if x < 1024.0 or unit == "TiB":
            if unit == "B":
                return f"{int(x)} {unit}"
            return f"{x:.2f} {unit}"
        x /= 1024.0
    return f"{int(n)} B"


def _needs_foundry_llm_download_at_startup(project_root: Path) -> bool:
    """LLM モデルが揃っているか **3 ステップのファイル存在確認** のみで判定する。

    Foundry SDK の import / load は行わない。

    ステップ 1: ``FOUNDRY_LLM_CACHE_IN_PROJECT`` が False → プロジェクト側を使わないためダイアログ不要。
    ステップ 2: ``models/llm/.speech_summarizer_llm_probe_ok`` が無い → 未ダウンロード。
    ステップ 3: マーカー 2 行目の解決済みモデル ID（例: ``Phi-4-mini-instruct-generic-gpu:5``）が
               設定エイリアス（``FOUNDRY_LLM_MODEL_ALIAS``）の前方一致（大文字小文字無視）を満たし、
               かつ ``models/llm/`` 以下の対応パスに ``model.onnx`` があるか。
               両方 OK → ダイアログ不要。いずれか NG → 再取得が必要。

    Args:
        project_root (Path): モデル配置の基準パス（``models/llm`` の親）。

    Returns:
        bool: 起動時に LLM 取得 UI を表示するなら True。
    """
    # ステップ 1: プロジェクト外キャッシュ設定ならスキップ
    if not config.FOUNDRY_LLM_CACHE_IN_PROJECT:
        return False

    # ステップ 2: probe marker ファイルの存在確認
    if not paths.foundry_llm_probe_marker_path(project_root).is_file():
        return foundry_sdk_importable()

    # ステップ 3: marker 2 行目の解決済みモデル ID でディレクトリ存在確認
    alias = config.FOUNDRY_LLM_MODEL_ALIAS
    resolved_id = paths.read_llm_resolved_id(project_root, alias)
    if not resolved_id:
        # marker はあるが 2 行目が空、またはエイリアス不一致 → 再取得
        return foundry_sdk_importable()
    # resolved_id が現在のエイリアスから始まるか確認（大文字小文字区別なし）。
    # 例: alias="phi-4-mini", resolved_id="Phi-4-mini-instruct-generic-gpu:5" → OK
    # エイリアスが変更されたとき古いマーカーを誤って有効と判定しないための安全弁。
    if not resolved_id.lower().startswith(alias.lower()):
        return foundry_sdk_importable()
    if paths.foundry_llm_model_onnx_present(project_root, resolved_id):
        return False
    return foundry_sdk_importable()


class _StartupModelsWorker(QObject):
    """STT モデルを順に取得し、必要なら続けて Foundry LLM を取得する。

    ``PySide6.QtCore.Signal`` はクラス属性として宣言する。各シグナルのペイロードは次のとおり。

    ``status(str, int, int)``:
        現在の STT モデル名、進捗インデックス（1 始まり）、対象モデル全体数。

    ``byte_progress(int, int, str)``:
        STT ダウンロードの累計転送バイト数、合計バイト数（不明時 ``-1``）、
        tqdm 由来の説明文。

    ``step_completed(int)``:
        完了した STT モデル数（1 始まり。最後の emit は全体数と一致）。

    ``llm_phase_started()``:
        STT 完了後、LLM フェーズに入る直前。

    ``llm_ep_progress(str, float)``:
        Foundry 実行プロバイダ（EP）名と進捗（0〜100）。

    ``llm_model_progress(float)``:
        LLM 重みダウンロードの進捗（0〜100）。

    ``finished()``:
        全処理が成功して終了したとき。

    ``failed(str)``:
        エラーメッセージ。
    """

    status = Signal(str, int, int)
    byte_progress = Signal(int, int, str)
    step_completed = Signal(int)
    llm_phase_started = Signal()
    llm_ep_progress = Signal(str, float)
    llm_model_progress = Signal(float)
    finished = Signal()
    failed = Signal(str)

    def __init__(
        self,
        project_root: Path,
        stt_folder_names: list[str],
        run_llm_phase: bool,
    ) -> None:
        """ワーカーを初期化する。

        Args:
            project_root: モデル保存先の基準パス。
            stt_folder_names: 取得する STT サブフォルダ名の列（順に処理）。
            run_llm_phase: STT 完了後に Foundry LLM の取得・ロード試行を行うか。

        Returns:
            None
        """
        super().__init__()
        self._project_root = project_root
        self._stt_folder_names = stt_folder_names
        self._run_llm_phase = run_llm_phase

    def _emit_bytes(self, current: int, total: int, desc: str) -> None:
        """STT ダウンロード進捗を ``byte_progress`` シグナルへ転送する。

        Args:
            current: セッション累積転送バイト。
            total: 合計バイト（不明時は ``-1``）。
            desc: 現在ファイル名などの説明。

        Returns:
            None
        """
        self.byte_progress.emit(current, total, desc)

    @Slot()
    def run(self) -> None:
        """ワーカースレッド開始時に ``QThread.started`` から呼ばれる。

        STT を順に取得し、設定されていれば LLM 取得フェーズへ進む。
        いずれかで失敗したら ``failed`` を emit して終了する。

        Returns:
            None
        """
        total_stt = len(self._stt_folder_names)
        for idx, name in enumerate(self._stt_folder_names):
            step = idx + 1
            self.status.emit(name, step, total_stt)
            attempt = 0
            while True:
                attempt += 1
                self.byte_progress.emit(0, -1, "")
                try:
                    download_stt_model(
                        self._project_root,
                        name,
                        on_progress=self._emit_bytes,
                    )
                    break
                except Exception as e:
                    msg = str(e)
                    if (
                        attempt < config.FOUNDRY_LLM_DOWNLOAD_CANCEL_AUTO_RETRY_MAX
                        and (_is_transient_cancel_download_error(msg))
                    ):
                        time.sleep(_cancel_retry_backoff_seconds(attempt))
                        continue
                    self.failed.emit(msg)
                    return
            self.step_completed.emit(step)

        if not self._run_llm_phase:
            self.finished.emit()
            return

        self.llm_phase_started.emit()
        attempt = 0
        while True:
            attempt += 1
            self.llm_model_progress.emit(0.0)
            try:
                summarizer = FoundryLocalSummarizer(
                    project_root=self._project_root,
                    model_alias=config.FOUNDRY_LLM_MODEL_ALIAS,
                )
                # EXE 起動時など EP 登録（OpenVINO 等）で環境差の失敗を避けるため、
                # ここでは重みの download のみ。EP と load は初回要約時の load_model へ委ねる。
                summarizer.download_model_weights_only(
                    model_download_progress=self.llm_model_progress.emit,
                )
                break
            except FoundryLocalNotAvailableError as e:
                self.failed.emit(
                    "Foundry Local SDK が利用できません。\n"
                    "pip install foundry-local-sdk-winml foundry-local-core-winml openai\n"
                    f"詳細: {e}"
                )
                return
            except Exception as e:
                msg = str(e)
                if attempt < config.FOUNDRY_LLM_DOWNLOAD_CANCEL_AUTO_RETRY_MAX and (
                    _is_transient_cancel_download_error(msg)
                ):
                    time.sleep(_cancel_retry_backoff_seconds(attempt))
                    continue
                self.failed.emit(msg)
                return

        self.finished.emit()


class StartupModelsSetupDialog(QDialog):
    """初回のみ必要な、不足 STT および／または LLM の取得進捗を表示するダイアログ。"""

    def __init__(
        self,
        project_root: Path,
        stt_missing: list[str],
        run_llm_phase: bool = False,
    ) -> None:
        """起動時モデル取得ダイアログを構築する。

        Args:
            project_root: モデル配置の基準パス。
            stt_missing: 未取得の STT フォルダ名のリスト。
            run_llm_phase: LLM 取得フェーズを続けて実行するか。

        Returns:
            None
        """
        super().__init__(None)
        self._project_root = project_root
        self._stt_missing = stt_missing
        self._run_llm_phase = run_llm_phase
        self.setWindowTitle(
            "Speech Summarizer AI — 初回のみ（音声認識・要約モデルの取得）"
        )
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.setMinimumWidth(520)
        self.setAttribute(Qt.WidgetAttribute.WA_AlwaysShowToolTips, True)

        _ui_dark = bool(
            QSettings("WEEL", "SpeechSummarizerAI").value(
                "ui/dark", DEFAULT_UI_DARK_UNSAVED, type=bool
            )
        )
        self.setStyleSheet(stt_model_setup_dialog_qss(dark=_ui_dark))

        self._label = QLabel()
        self._label.setWordWrap(True)
        self._label.setAlignment(Qt.AlignmentFlag.AlignLeft)

        self._bytes_label = QLabel()
        self._bytes_label.setWordWrap(True)
        self._bytes_label.setAlignment(Qt.AlignmentFlag.AlignLeft)

        self._model_bar = QProgressBar()
        self._model_bar.setTextVisible(True)

        self._bytes_bar = QProgressBar()
        self._bytes_bar.setRange(0, 0)
        self._bytes_bar.setTextVisible(True)
        self._bytes_bar.setFormat("%p%")

        lay = QVBoxLayout(self)
        lay.addWidget(self._label)
        lay.addWidget(self._bytes_label)
        lay.addWidget(self._model_bar)
        lay.addWidget(self._bytes_bar)

        self._thread: QThread | None = None
        self._worker: _StartupModelsWorker | None = None
        self._in_llm_phase = False

    def start_and_exec(self) -> bool:
        """ダウンロードを開始し、終了までイベントループで待つ。

        Returns:
            bool: ワーカー成功で ``accept`` された場合 True。失敗・キャンセル相当は False。
        """
        n_stt = len(self._stt_missing)
        summary_bits: list[str] = []
        if n_stt:
            summary_bits.append(f"音声認識モデル {n_stt} 種類（models/stt）")
        if self._run_llm_phase:
            summary_bits.append(
                f"要約用 LLM「{config.FOUNDRY_LLM_MODEL_ALIAS}」"
                + (
                    "（models/llm）"
                    if config.FOUNDRY_LLM_CACHE_IN_PROJECT
                    else "（Foundry キャッシュ）"
                )
            )

        self._label.setText(
            "【初回起動時のみ】不足しているモデルをこの PC に保存します。\n"
            f"今回の対象: {' / '.join(summary_bits) if summary_bits else '—'}。\n"
            "※ 2 回目以降は保存済みをそのまま使うため、通常はこの画面は出ません。\n"
            "容量・回線の都合で時間がかかることがあります。"
        )

        if n_stt:
            self._model_bar.setRange(0, n_stt)
            self._model_bar.setValue(0)
            self._model_bar.setFormat("音声認識モデル: %v / %m")
        elif self._run_llm_phase:
            self._model_bar.setRange(0, 100)
            self._model_bar.setValue(0)
            self._model_bar.setFormat("要約 LLM: %p%")
        else:
            self._model_bar.setRange(0, 1)
            self._model_bar.setValue(0)

        self._bytes_label.setText("転送量: 準備中…")
        self.adjustSize()
        screen = QApplication.primaryScreen()
        if screen is not None:
            ag = screen.availableGeometry()
            g = self.frameGeometry()
            g.moveCenter(ag.center())
            self.move(g.topLeft())

        self._thread = QThread()
        self._worker = _StartupModelsWorker(
            self._project_root, self._stt_missing, self._run_llm_phase
        )
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.status.connect(self._on_stt_status)
        self._worker.byte_progress.connect(self._on_byte_progress)
        self._worker.step_completed.connect(self._on_step_completed)
        self._worker.llm_phase_started.connect(self._on_llm_phase_started)
        self._worker.llm_ep_progress.connect(self._on_llm_ep_progress)
        self._worker.llm_model_progress.connect(self._on_llm_model_progress)
        self._worker.finished.connect(self._on_worker_finished)
        self._worker.failed.connect(self._on_worker_failed)

        self._worker.finished.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.finished.connect(self._cleanup_worker)

        self.show()
        self._thread.start()
        result = self.exec()
        self._shutdown_download_thread()
        return result == QDialog.DialogCode.Accepted

    def _shutdown_download_thread(self) -> None:
        """ダイアログを閉じたあとでもワーカースレッドが動いていることがあるため、返却前に終了を待つ。

        Returns:
            None
        """
        if self._thread is None:
            return
        if self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(600_000)
        QApplication.processEvents()

    def _on_stt_status(self, name: str, step: int, total: int) -> None:
        """STT モデル 1 種類のダウンロード開始を UI に反映する。

        Args:
            name: 現在のモデルフォルダ名。
            step: 何番目か（1 始まり）。
            total: STT モデル総数。

        Returns:
            None
        """
        self._in_llm_phase = False
        self._label.setText(
            f"【初回のみ】音声認識モデルをダウンロード中: 「{name}」（{step} / {total}）\n"
            "完了までウィンドウを閉じないでください。"
        )
        self._model_bar.setMaximum(total)
        self._model_bar.setValue(step - 1)
        self._bytes_label.setText("転送量: 集計中…")
        self._bytes_bar.setRange(0, 0)

    def _on_byte_progress(self, current: int, total: int, desc: str) -> None:
        """STT バイト進捗をプログレスバーとラベルに反映する（LLM フェーズ中は無視）。

        Args:
            current: 累積転送バイト。
            total: 合計バイト（不明時は ``0`` 以下）。
            desc: 説明文。

        Returns:
            None
        """
        if self._in_llm_phase:
            return
        if total <= 0:
            self._bytes_bar.setRange(0, 0)
            self._bytes_label.setText(
                f"転送量: {_format_bytes(current)} 取得中…"
                + (f"  ({desc})" if desc else "")
            )
            return

        self._bytes_bar.setRange(0, total)
        self._bytes_bar.setValue(min(current, total))
        pct = 100.0 * current / total if total else 0.0
        self._bytes_label.setText(
            f"転送量: {_format_bytes(current)} / {_format_bytes(total)}  "
            f"({pct:.1f}%)" + (f"  — {desc}" if desc else "")
        )

    def _on_step_completed(self, completed: int) -> None:
        """STT モデル 1 種類の完了をモデル用プログレスバーに反映する。

        Args:
            completed: 完了した STT 数（1 始まり）。

        Returns:
            None
        """
        if not self._in_llm_phase:
            self._model_bar.setValue(completed)

    def _on_llm_phase_started(self) -> None:
        """LLM フェーズ開始時にラベルとプログレス表示を切り替える。

        Returns:
            None
        """
        self._in_llm_phase = True
        self._label.setText(
            f"【初回のみ】要約用 LLM「{config.FOUNDRY_LLM_MODEL_ALIAS}」の重みを取得しています。\n"
            "（実行プロバイダの登録は行いません。初回要約時に行われます。）\n"
            "ウィンドウを閉じないでください。"
        )
        self._bytes_label.setText("LLM モデル重み — 準備中…")
        self._bytes_bar.setRange(0, 0)
        self._model_bar.setRange(0, 100)
        self._model_bar.setValue(0)
        self._model_bar.setFormat("要約 LLM: %p%")

    def _on_llm_ep_progress(self, ep_name: str, percent: float) -> None:
        """Foundry 実行プロバイダ（EP）登録の進捗を表示する。

        Args:
            ep_name: EP 名。
            percent: 進捗（0〜100）。

        Returns:
            None
        """
        self._bytes_label.setText(f"Foundry EP: {ep_name} — {percent:5.1f}%")
        self._bytes_bar.setRange(0, 0)

    def _on_llm_model_progress(self, percent: float) -> None:
        """LLM 重みダウンロードの進捗をメインのプログレスバーに反映する。

        Args:
            percent: 進捗（0〜100）。

        Returns:
            None
        """
        p = max(0.0, min(100.0, float(percent)))
        self._model_bar.setRange(0, 100)
        self._model_bar.setValue(int(round(p)))
        self._bytes_label.setText(f"LLM モデル重みの取得: {p:.1f}%")

    def _on_worker_finished(self) -> None:
        """ワーカー成功時にダイアログを承認で閉じる。

        Returns:
            None
        """
        self.accept()

    def _on_worker_failed(self, message: str) -> None:
        """ワーカー失敗時にエラーを表示し、ダイアログを却下で閉じる。

        Args:
            message: ユーザー向けエラーメッセージ。

        Returns:
            None
        """
        QMessageBox.critical(
            self,
            "初回のみのモデル取得に失敗しました",
            message,
        )
        self.reject()

    def _cleanup_worker(self) -> None:
        """スレッド終了後にワーカーと ``QThread`` を ``deleteLater`` する。

        Returns:
            None
        """
        if self._worker is not None:
            self._worker.deleteLater()
            self._worker = None
        if self._thread is not None:
            self._thread.deleteLater()
            self._thread = None


def run_startup_models_setup_if_needed(project_root: Path) -> bool:
    """``models/stt`` と ``models/llm``（設定時）をファイル存在のみで検査する。

    LLM は probe marker + 解決済み ID + ディレクトリ存在の 3 ステップで判定し、起動時に Foundry で load 試行はしない。
    不足分だけダイアログで取得し、揃えばすぐメインへ。

    Args:
        project_root (Path): データ／モデル基準パス。

    Returns:
        bool: モデルが揃っているか、取得に成功して起動を続けられる場合 True。取得失敗時は False。
    """
    status = list_stt_model_status(project_root)
    stt_missing = [name for name in STT_STORAGE_FOLDER_NAMES if not status[name]]
    need_stt_ui = bool(stt_missing)

    need_llm_ui = _needs_foundry_llm_download_at_startup(project_root)

    if not need_stt_ui and not need_llm_ui:
        return True

    dlg = StartupModelsSetupDialog(project_root, stt_missing, need_llm_ui)
    return dlg.start_and_exec()
