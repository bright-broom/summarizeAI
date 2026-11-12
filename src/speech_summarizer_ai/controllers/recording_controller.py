"""録音・リアルタイム STT・LLM 要約と DB 更新。UI とは Qt Signal のみで連携する。"""

from __future__ import annotations

import gc
import queue
import sys
import threading
import wave
from pathlib import Path

import numpy as np
from PySide6.QtCore import QObject, QTimer, Signal

from speech_summarizer_ai import settings as config
from speech_summarizer_ai.audio import backend as audio_backend
from speech_summarizer_ai.data import meetings_repository as meetings_db
from speech_summarizer_ai.domain.meeting import ProgressStatus
from speech_summarizer_ai.llm.foundry_local import (
    FoundryLocalModelNotCachedError,
    FoundryLocalNotAvailableError,
    FoundryLocalSummarizer,
)
from speech_summarizer_ai.llm.meeting_summarizer import (
    summarize_meeting_from_paragraphs,
)
from speech_summarizer_ai.platform_utils import paths
from speech_summarizer_ai.stt.realtime import (
    format_stt_timestamp,
    run_realtime_transcription_loop,
)


class RecordingController(QObject):
    """録音・STT・要約の状態とスレッド。古い STT 完了は世代番号で無視する。"""

    #: ``(meeting_id,)`` 録音用行を DB に作成したとき。
    recording_meeting_created = Signal(int)
    #: ``(meeting_id, time_str, text)`` 文字起こしを DB に追記したとき。
    live_transcript_line_saved = Signal(int, str, str)
    #: ``(meeting_id,)`` 要約開始時。
    meeting_summarization_started = Signal(int)
    #: ``(meeting_id,)`` 要約と progress 更新まで完了したとき。
    meeting_summarization_finished = Signal(int)
    #: ``(recording,)`` 録音スレッドの有無。
    recording_state_changed = Signal(bool)
    #: ``(active,)`` 停止後の STT／要約パイプラインが動いているか。
    post_stop_pipeline_changed = Signal(bool)
    #: ``(stt_pending,)`` HUD タイトル更新が必要なとき。
    idle_title_should_update = Signal(bool)
    #: ``(title, body)`` 情報ダイアログ。
    message_info_requested = Signal(str, str)
    #: ``(title, body)`` 警告ダイアログ。
    message_warning_requested = Signal(str, str)
    #: 内部。``(time_str, text, meeting_id)``。
    _stt_utterance_for_db = Signal(str, str, int)
    #: 内部。``(session_gen,)`` STT 終了。
    _stt_session_finished = Signal(int)

    _WINDOW_TITLE = "Speech Summarizer AI"

    def __init__(self, project_root: Path, parent: QObject | None = None) -> None:
        """コントローラーを初期化する。

        Args:
            project_root: セッション・DB・モデルの基準ディレクトリ。
            parent: Qt 親 ``QObject``。

        Returns:
            None
        """
        super().__init__(parent)
        self._save_dir = project_root

        self._stop_event = threading.Event()
        self._record_thread: threading.Thread | None = None
        self._session_audio_path: Path | None = None
        self._record_error: str | None = None

        self._live_queue: queue.Queue | None = None
        self._stt_thread: threading.Thread | None = None
        self._stt_stop_event: threading.Event | None = None
        self._stt_finish_generation: int = 0
        self._stt_folder_lock = threading.Lock()
        self._live_stt_folder_name: str = config.STT_DEFAULT_MODEL

        self._recording_meeting_id: int | None = None
        self._foundry_summarizer: FoundryLocalSummarizer | None = None
        self._foundry_summarizer_lock = threading.Lock()
        self._post_stop_pipeline_active: bool = False

        self._stt_utterance_for_db.connect(self._persist_stt_line)
        self._stt_session_finished.connect(self._on_stt_worker_finished)
        self.meeting_summarization_finished.connect(self._release_post_stop_pipeline)

    @property
    def project_root(self) -> Path:
        """録音・DB・モデルファイルの基準ディレクトリ（プロジェクトルート）。

        Returns:
            セッション・SQLite・モデル解決に使うルートパス。
        """
        return self._save_dir

    def is_recording(self) -> bool:
        """録音スレッドが起動中かどうかを返す。

        Returns:
            録音スレッドが生きていれば True。
        """
        return self._record_thread is not None

    def is_stt_worker_alive(self) -> bool:
        """バックグラウンド STT スレッドが起動中かどうかを返す。

        Returns:
            STT ワーカースレッドが存在し生存していれば True。
        """
        return self._stt_thread is not None and self._stt_thread.is_alive()

    def is_post_stop_pipeline_active(self) -> bool:
        """録音停止後の文字起こし／要約パイプラインが進行中かどうかを返す。

        Returns:
            停止後パイプラインが有効なら True。
        """
        return self._post_stop_pipeline_active

    def recording_controls_interactive(self) -> bool:
        """録音開始／停止 UI が操作可能かどうかを返す。

        録音停止から要約完了までの間は False になる。

        Returns:
            操作可能なら True。
        """
        return not self._post_stop_pipeline_active

    def set_live_stt_folder_name(self, folder: str) -> None:
        """リアルタイム STT が参照する ``models/stt/<folder>`` のフォルダ名を設定する。

        一覧ウィンドウのモデル選択などから更新される。

        Args:
            folder: STT モデルサブディレクトリ名（例: ``tiny`` / ``base``）。

        Returns:
            None
        """
        with self._stt_folder_lock:
            self._live_stt_folder_name = folder

    def _get_live_stt_folder_name(self) -> str:
        """スレッド安全に、現在のリアルタイム STT 用モデルフォルダ名を返す。

        Returns:
            ``models/stt`` 直下のフォルダ名。
        """
        with self._stt_folder_lock:
            return self._live_stt_folder_name

    def _emit_stt_text(self, text: str, t0_sec: float) -> None:
        """STT ワーカースレッドから呼ばれ、認識文をコンソールへ出し DB 追記用シグナルを送る。

        全文トランスクリプトはメモリに保持せず、行単位で SQLite に追記する。
        空文字は無視する。録音中の meeting_id が無い場合はシグナルを送らない。

        Args:
            text: 認識テキスト。
            t0_sec: 録音開始からのセグメント開始秒。

        Returns:
            None
        """
        ts = format_stt_timestamp(t0_sec)
        tx = text.strip()
        if not tx:
            return
        print(f"[STT {ts}] {tx}", flush=True)
        mid = self._recording_meeting_id
        if mid is None:
            return
        self._stt_utterance_for_db.emit(ts, tx, mid)

    def _persist_stt_line(self, ts: str, text: str, meeting_id: int) -> None:
        """メインスレッドで ``paragraph_list`` に 1 行追記し、UI へ通知する。

        Args:
            ts: 表示用時刻文字列。
            text: 認識本文。
            meeting_id: 商談 ID。

        Returns:
            None
        """
        if not meetings_db.append_paragraph_line(self._save_dir, meeting_id, ts, text):
            print(
                f"[STT] paragraph_list の DB 追記に失敗しました (meeting_id={meeting_id})",
                file=sys.stderr,
                flush=True,
            )
            return
        self.live_transcript_line_saved.emit(meeting_id, ts, text)

    def _emit_stt_error(self, msg: str) -> None:
        """STT ワーカーからの致命的エラーメッセージを標準エラーへ出力する。

        Args:
            msg: 出力するメッセージ。

        Returns:
            None
        """
        print(msg, file=sys.stderr, flush=True)

    def _stt_worker_entry(self, session_gen: int) -> None:
        """STT バックグラウンドスレッドのエントリポイント。

        ``run_realtime_transcription_loop`` を実行し、終了時に必ず
        ``_stt_session_finished`` を送出する。

        Args:
            session_gen: この STT セッションの世代番号。

        Returns:
            None
        """
        try:
            q = self._live_queue
            ev = self._stt_stop_event
            if q is None or ev is None:
                return
            run_realtime_transcription_loop(
                stop_event=ev,
                audio_queue=q,
                project_root=self._save_dir,
                get_model_folder=self._get_live_stt_folder_name,
                emit_text=self._emit_stt_text,
                emit_error=self._emit_stt_error,
            )
        finally:
            self._stt_session_finished.emit(session_gen)

    def _on_stt_worker_finished(self, session_gen: int) -> None:
        """バックグラウンド STT ワーカー終了時にメインスレッドで呼ばれる。

        現在の STT セッション世代と一致しない場合は何もしない。一致する場合は
        要約キューへ進める。

        Args:
            session_gen: 完了した STT セッションの世代番号。

        Returns:
            None
        """
        print(
            f"[STT] メインスレッド: セッション完了コールバック "
            f"(session_gen={session_gen}, current_gen={self._stt_finish_generation})",
            flush=True,
        )
        if session_gen != self._stt_finish_generation:
            print(
                f"[STT] 古いセッションのため完了処理をスキップしました "
                f"(session_gen={session_gen})",
                flush=True,
            )
            return
        self._stt_thread = None
        self._stt_stop_event = None
        self._live_queue = None
        stt_done_mid = self._recording_meeting_id
        self._recording_meeting_id = None
        self.idle_title_should_update.emit(False)
        if stt_done_mid is not None:
            QTimer.singleShot(
                0, lambda m=stt_done_mid: self._queue_post_stt_summarization(m)
            )
        else:
            print(
                "[STT] 警告: セッション完了時に recording_meeting_id が無く、"
                "要約キューに載せられませんでした。",
                flush=True,
            )
            self._set_post_stop_pipeline_active(False)

    def _queue_post_stt_summarization(self, meeting_id: int) -> None:
        """文字起こし完了後に要約処理を開始する（メインスレッド）。

        設定により LLM をスキップし、進捗ステータスのみ更新することもある。

        Args:
            meeting_id: 対象の商談 ID。

        Returns:
            None
        """
        if not config.AUTO_LLM_SUMMARIZE_AFTER_STT:
            print(
                "[summarize] AUTO_LLM_SUMMARIZE_AFTER_STT=False のため LLM 要約をスキップし、"
                "status->success のみ行います。",
                flush=True,
            )
            meetings_db.update_meeting_summary(self._save_dir, meeting_id, "")
            meetings_db.update_meeting_progress_status(
                self._save_dir, meeting_id, ProgressStatus.SUCCESS
            )
            self.meeting_summarization_finished.emit(meeting_id)
            return
        rec = meetings_db.get_meeting(self._save_dir, meeting_id)
        if rec is None:
            print(
                f"[summarize] meeting_id={meeting_id}: DB に行がありません; 要約を中止",
                flush=True,
            )
            self._set_post_stop_pipeline_active(False)
            return
        if rec.progress_status == ProgressStatus.FAILED:
            print(
                f"[summarize] meeting_id={meeting_id}: progress_status が FAILED のため要約しません",
                flush=True,
            )
            self._set_post_stop_pipeline_active(False)
            return
        lines = rec.transcript_lines
        if not lines:
            print(
                f"[summarize] meeting_id={meeting_id}: no transcript lines; "
                "skip LLM, status->success",
                flush=True,
            )
            meetings_db.update_meeting_summary(self._save_dir, meeting_id, "")
            meetings_db.update_meeting_progress_status(
                self._save_dir, meeting_id, ProgressStatus.SUCCESS
            )
            self.meeting_summarization_finished.emit(meeting_id)
            return
        print(
            f"[summarize] meeting_id={meeting_id}: STT done; starting summarization "
            f"({len(lines)} line(s)), progress_status->summarizing",
            flush=True,
        )
        meetings_db.update_meeting_progress_status(
            self._save_dir, meeting_id, ProgressStatus.SUMMARIZING
        )
        self.meeting_summarization_started.emit(meeting_id)
        t = threading.Thread(
            target=self._summarize_worker_run,
            args=(meeting_id,),
            name="FoundrySummarize",
            daemon=True,
        )
        t.start()

    def _unload_foundry_summarizer_after_job(self) -> None:
        """要約ジョブ終了後に Foundry LLM をアンロードし参照を外す。

        STT（faster-whisper）は変更しない。プロセス内の Foundry マネージャは SDK 側で残る場合があるが、
        モデル重みは :meth:`FoundryLocalSummarizer.unload` で解放する。

        Returns:
            None
        """
        with self._foundry_summarizer_lock:
            s = self._foundry_summarizer
            if s is None:
                return
            try:
                s.unload()
            except Exception:  # noqa: BLE001
                pass
            self._foundry_summarizer = None
            gc.collect()
            print(
                "[summarize] Foundry Local model unloaded (LLM memory released).",
                flush=True,
            )

    def _ensure_foundry_summarizer_loaded(self) -> FoundryLocalSummarizer:
        """この要約ジョブ用に Foundry Local をロードする。

        ジョブ完了後は必ず :meth:`_unload_foundry_summarizer_after_job` で破棄する。
        次の録音・要約では再度ロードする。STT モデルは別経路のため常時メモリに残りうる。

        Returns:
            ロード済みの ``FoundryLocalSummarizer`` インスタンス。
        """
        with self._foundry_summarizer_lock:
            if self._foundry_summarizer is not None and getattr(
                self._foundry_summarizer, "_loaded", False
            ):
                return self._foundry_summarizer
            print(
                "[summarize] Loading Foundry Local model for this summarize job…",
                flush=True,
            )
            s = FoundryLocalSummarizer(
                project_root=self._save_dir,
                model_alias=config.FOUNDRY_LLM_MODEL_ALIAS,
            )
            s.load_model(download_eps=True, allow_download=False)
            self._foundry_summarizer = s
            print("[summarize] Foundry Local model ready.", flush=True)
            return self._foundry_summarizer

    def _summarize_worker_run(self, meeting_id: int) -> None:
        """バックグラウンドスレッドで LLM 要約を実行し、DB を更新する。

        正常・異常にかかわらず、終了時に ``meeting_summarization_finished`` を送出する。

        Args:
            meeting_id: 対象の商談 ID。

        Returns:
            None
        """
        print(f"[summarize] meeting_id={meeting_id}: worker thread started", flush=True)
        try:
            rec = meetings_db.get_meeting(self._save_dir, meeting_id)
            if rec is None or rec.progress_status == ProgressStatus.FAILED:
                print(
                    f"[summarize] meeting_id={meeting_id}: abort (no record or FAILED)",
                    flush=True,
                )
                return
            if not rec.transcript_lines:
                print(
                    f"[summarize] meeting_id={meeting_id}: transcript empty in worker; "
                    "skip LLM, status->success",
                    flush=True,
                )
                meetings_db.update_meeting_summary(self._save_dir, meeting_id, "")
                meetings_db.update_meeting_progress_status(
                    self._save_dir, meeting_id, ProgressStatus.SUCCESS
                )
                return
            try:
                summarizer = self._ensure_foundry_summarizer_loaded()
                outcome = summarize_meeting_from_paragraphs(
                    self._save_dir, meeting_id, summarizer
                )
                meetings_db.update_meeting_summary(
                    self._save_dir, meeting_id, outcome.summary
                )
                if outcome.title:
                    meetings_db.update_meeting_title(
                        self._save_dir, meeting_id, outcome.title
                    )
                meetings_db.update_meeting_progress_status(
                    self._save_dir, meeting_id, ProgressStatus.SUCCESS
                )
                print(
                    f"[summarize] meeting_id={meeting_id}: saved title={outcome.title!r} "
                    f"summary ({len(outcome.summary)} chars), progress_status->success",
                    flush=True,
                )
            except FoundryLocalNotAvailableError:
                msg = (
                    "要約には Foundry Local SDK が必要です。\n"
                    "pip install foundry-local-sdk-winml foundry-local-core-winml openai"
                )
                print(
                    f"[summarize] meeting_id={meeting_id}: Foundry Local not available",
                    flush=True,
                )
                meetings_db.update_meeting_summary(self._save_dir, meeting_id, msg)
                meetings_db.update_meeting_progress_status(
                    self._save_dir, meeting_id, ProgressStatus.FAILED
                )
            except FoundryLocalModelNotCachedError as e:
                msg = str(e)
                print(
                    f"[summarize] meeting_id={meeting_id}: LLM not in cache: {e!r}",
                    flush=True,
                )
                paths.clear_llm_probe_marker(self._save_dir)
                meetings_db.update_meeting_summary(self._save_dir, meeting_id, msg)
                meetings_db.update_meeting_progress_status(
                    self._save_dir, meeting_id, ProgressStatus.FAILED
                )
            except Exception as e:
                print(
                    f"[summarize] meeting_id={meeting_id}: ERROR {e!r}",
                    flush=True,
                )
                meetings_db.update_meeting_summary(
                    self._save_dir,
                    meeting_id,
                    f"（要約に失敗しました: {e}）",
                )
                meetings_db.update_meeting_progress_status(
                    self._save_dir, meeting_id, ProgressStatus.FAILED
                )
        finally:
            self._unload_foundry_summarizer_after_job()
            print(
                f"[summarize] meeting_id={meeting_id}: done (emit meeting_summarization_finished)",
                flush=True,
            )
            # 要約はバックグラウンドスレッド上で動く。QTimer.singleShot はそのスレッドのイベント
            # ループに積まれるが、ワーカーにループが無いと発火しない。シグナルはスレッド間で
            # Queued 接続されメインへ届く（STT の _stt_session_finished と同様）。
            self.meeting_summarization_finished.emit(meeting_id)

    def _release_post_stop_pipeline(self, _meeting_id: int) -> None:
        """要約完了後に停止後パイプラインを終了し、録音操作を再有効化する。

        Args:
            _meeting_id: シグナル接続用（未使用）。

        Returns:
            None
        """
        self._set_post_stop_pipeline_active(False)

    def _set_post_stop_pipeline_active(self, active: bool) -> None:
        """停止後パイプラインの稼働フラグを更新し、``post_stop_pipeline_changed`` を送出する。

        Args:
            active: パイプラインが動作中なら True。

        Returns:
            None
        """
        if self._post_stop_pipeline_active == active:
            self.post_stop_pipeline_changed.emit(active)
            return
        self._post_stop_pipeline_active = active
        self.post_stop_pipeline_changed.emit(active)

    def _record_worker(self) -> None:
        """録音スレッドのエントリポイント。``audio_backend.run_recording_session`` を実行する。

        録音ファイルが有効なときは ``wave`` でチャンク単位ストリーミング書き込みする。

        Returns:
            None
        """
        slot: list[str | None] = [None]
        q = self._live_queue
        if q is None:
            slot[0] = "内部エラー: リアルタイム STT キューがありません。"
            return

        def live_cb(chunk: np.ndarray) -> None:
            q.put(chunk)

        wav_out = None
        audio_path = self._session_audio_path
        try:
            if config.SAVE_RECORDED_AUDIO_TO_FILE and audio_path is not None:
                wav_out = wave.open(str(audio_path), "wb")
                wav_out.setnchannels(config.output_channel_count())
                wav_out.setsampwidth(config.SAMPLE_WIDTH)
                wav_out.setframerate(config.SAMPLE_RATE)

                def recording_sink(pcm: np.ndarray) -> None:
                    wav_out.writeframes(pcm.tobytes())

                pcm_sink = recording_sink
            else:
                pcm_sink = None

            audio_backend.run_recording_session(
                self._stop_event,
                slot,
                live_mono_chunk_callback=live_cb,
                recording_pcm_sink=pcm_sink,
            )
        finally:
            if wav_out is not None:
                try:
                    wav_out.close()
                except Exception:  # noqa: BLE001
                    pass
        self._record_error = slot[0]

    def toggle_recording(self) -> None:
        """録音を開始するか、実行中なら停止して WAV 保存まで行う。

        Returns:
            None
        """
        if self._record_thread is None:
            if self._post_stop_pipeline_active:
                self.message_info_requested.emit(
                    self._WINDOW_TITLE,
                    "音声認識および要約が完了するまでお待ちください。",
                )
                return
            if self._stt_thread is not None and self._stt_thread.is_alive():
                self.message_info_requested.emit(
                    self._WINDOW_TITLE,
                    "前回の音声認識がまだバックグラウンドで処理中です。\n"
                    "完了してから録音を開始してください。",
                )
                return
            if self._stt_thread is not None and not self._stt_thread.is_alive():
                self._on_stt_worker_finished(self._stt_finish_generation)
            try:
                new_mid = meetings_db.insert_meeting_for_recording(self._save_dir)
            except Exception as e:
                self.message_warning_requested.emit(
                    self._WINDOW_TITLE,
                    f"商談レコードの作成に失敗しました。\n{e}",
                )
                return
            self._recording_meeting_id = new_mid
            self.recording_meeting_created.emit(new_mid)
            if config.SAVE_RECORDED_AUDIO_TO_FILE:
                session_dir, audio_path = paths.new_session_audio_path(self._save_dir)
                session_dir.mkdir(parents=True, exist_ok=True)
                self._session_audio_path = audio_path
            else:
                self._session_audio_path = None
            self._stop_event.clear()
            self._live_queue = queue.Queue()
            self._stt_stop_event = threading.Event()
            self._stt_finish_generation += 1
            session_gen = self._stt_finish_generation
            self._stt_thread = threading.Thread(
                target=lambda: self._stt_worker_entry(session_gen),
                name="RealtimeSTT",
                daemon=False,
            )
            self._stt_thread.start()
            self._record_thread = threading.Thread(
                target=self._record_worker,
                name="AudioCapture",
                daemon=True,
            )
            self._record_thread.start()
            self.recording_state_changed.emit(True)
        else:
            self._set_post_stop_pipeline_active(True)
            self.recording_state_changed.emit(False)
            self._stop_event.set()
            self._record_thread.join(timeout=30.0)
            self._record_thread = None
            if self._stt_stop_event is not None:
                self._stt_stop_event.set()
            self.idle_title_should_update.emit(self.is_stt_worker_alive())
            self._finalize_recording_session()

    def _apply_meeting_status_after_wav(self, *, saved: bool, err: str | None) -> None:
        """WAV 保存の結果を meetings の ``progress_status`` に反映する。

        保存に成功しエラーが無い場合は ``recording`` のままにする。

        Args:
            saved: ファイル書き込みに成功したか。
            err: 録音スレッドが報告したエラーメッセージ。無ければ None。

        Returns:
            None
        """
        mid = self._recording_meeting_id
        if mid is None:
            return
        if saved and not err:
            return
        meetings_db.update_meeting_progress_status(
            self._save_dir, mid, ProgressStatus.FAILED
        )

    def _finalize_recording_session(self) -> None:
        """録音停止後の確認。WAV は録音中にストリーミング済み（または保存オフ）。

        Returns:
            None
        """
        path = self._session_audio_path
        self._session_audio_path = None
        err = self._record_error
        self._record_error = None
        if err:
            self.message_warning_requested.emit("録音", err)
            self._apply_meeting_status_after_wav(saved=False, err=err)
            return
        if not config.SAVE_RECORDED_AUDIO_TO_FILE:
            self._apply_meeting_status_after_wav(saved=True, err=None)
            return
        # 保存 ON: セッション開始時に決めたパスへ録音スレッドがストリーム書き込み済み
        saved = (
            path is not None
            and path.is_file()
            and path.stat().st_size > 44  # RIFF WAV ヘッダより大きい
        )
        if not saved:
            self.message_warning_requested.emit(
                "録音",
                "音声ファイルがほぼ空か作成されませんでした。\n"
                "マイクのアプリ権限（設定）や、既定の録音デバイスを確認してください。",
            )
        self._apply_meeting_status_after_wav(saved=saved, err=None)

    def shutdown_for_quit(self) -> None:
        """終了処理用に録音と STT を停止し、関連する状態を片付ける。

        Facade の ``_quit_application`` から呼ばれる。``QApplication.quit()`` は呼び出し側。

        Returns:
            None
        """
        from PySide6.QtWidgets import (
            QApplication,
        )  # 遅延 import（モジュール先頭の依存を減らす）

        if self._record_thread is not None:
            self.recording_state_changed.emit(False)
            self._stop_event.set()
            self._record_thread.join(timeout=30.0)
            self._record_thread = None
            if self._stt_stop_event is not None:
                self._stt_stop_event.set()
            self._finalize_recording_session()
        if self._stt_thread is not None and self._stt_thread.is_alive():
            if self._stt_stop_event is not None:
                self._stt_stop_event.set()
            self._stt_thread.join()
        # STT 終了シグナルがメインキューに残っているとき、世代を上げる前に処理する
        app_inst = QApplication.instance()
        if app_inst is not None:
            app_inst.processEvents()
        self._stt_finish_generation += 1
        self._stt_thread = None
        self._stt_stop_event = None
        self._live_queue = None
        self._unload_foundry_summarizer_after_job()
