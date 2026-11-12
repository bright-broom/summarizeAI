"""日本語文字起こし品質まわり（リサンプル・幻覚除去・発話の区切り方・文脈ヒント）のテスト。"""

from __future__ import annotations

import queue
import threading
from dataclasses import dataclass

import numpy as np
import pytest

from speech_summarizer_ai.stt import faster_whisper_engine as eng
from speech_summarizer_ai.stt import realtime

SR = 48_000


def _tone(freq: float, seconds: float, amp: float = 0.5) -> np.ndarray:
    t = np.arange(int(SR * seconds)) / SR
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def _band_energy(x: np.ndarray, sr: int, lo: float, hi: float) -> float:
    spec = np.abs(np.fft.rfft(x)) ** 2
    f = np.fft.rfftfreq(x.size, 1 / sr)
    return float(spec[(f >= lo) & (f <= hi)].sum())


def test_resampler_suppresses_aliasing() -> None:
    # 12 kHz の成分は 16 kHz 出力では表現できない。素朴な間引きだと 4 kHz に折り返して音声帯域を汚す。
    x = _tone(12_000, 1.0)
    y = eng._resample_linear_float32(x, src_sr=SR, dst_sr=16_000)
    assert y.size == 16_000
    naive = x[::3]
    alias_naive = _band_energy(naive, 16_000, 3_500, 4_500)
    alias_ours = _band_energy(y, 16_000, 3_500, 4_500)
    assert alias_ours < alias_naive * 1e-3


def test_resampler_keeps_speech_band() -> None:
    x = _tone(1_000, 1.0)
    y = eng._resample_linear_float32(x, src_sr=SR, dst_sr=16_000)
    assert abs(float(np.max(np.abs(y[2000:-2000]))) - 0.5) < 0.02


def test_normalize_level_boosts_quiet_but_not_loud() -> None:
    quiet = _tone(500, 0.2, amp=0.05)
    assert float(np.max(np.abs(eng._normalize_level(quiet)))) == pytest.approx(0.3, rel=0.02)  # 6x cap
    loud = _tone(500, 0.2, amp=0.9)
    assert np.array_equal(eng._normalize_level(loud), loud)


@pytest.mark.parametrize(
    "text",
    ["ご視聴ありがとうございました", "ご視聴ありがとうございました。", "チャンネル登録よろしくお願いします",
     "字幕", "ありがとうございました。", "ああああああああ", "はいはいはいはいはいはいはい", "  "],
)
def test_hallucinations_are_dropped(text: str) -> None:
    assert realtime.is_probable_hallucination(text)


@pytest.mark.parametrize(
    "text",
    ["本日はありがとうございました。次回は来週火曜日です。", "予算の件、ありがとうございました", "はい", "了解です",
     "お疲れ様でした、では資料を共有します"],
)
def test_real_speech_is_kept(text: str) -> None:
    assert not realtime.is_probable_hallucination(text)


def test_quietest_cut_finds_pause() -> None:
    loud = (_tone(300, 1.0) * 32767).astype(np.int16)
    gap = np.zeros(SR // 10, dtype=np.int16)
    buf = np.concatenate([loud, gap, loud])
    cut = realtime._quietest_cut(buf, search_from=0)
    assert loud.size <= cut <= loud.size + gap.size


@dataclass
class _Seg:
    start: float
    end: float
    text: str


class _FakeTranscriber:
    calls: list[dict] = []

    def __init__(self, **_kw) -> None:
        pass

    def transcribe_int16_mono(self, pcm, **kw):
        n = len(_FakeTranscriber.calls) + 1
        _FakeTranscriber.calls.append({"seconds": pcm.size / SR, **kw})
        text = f"発話{n}です。" if n != 2 else "ご視聴ありがとうございました"
        seg = _Seg(0.0, pcm.size / SR, text)
        return type("R", (), {"segments": (seg,), "text": text})()


def _speech(seconds: float) -> np.ndarray:
    return (_tone(220, seconds, 0.3) * 32767).astype(np.int16)


def _silence(seconds: float) -> np.ndarray:
    return np.zeros(int(SR * seconds), dtype=np.int16)


def test_realtime_segmentation_merges_short_pauses_and_passes_context(monkeypatch, tmp_path) -> None:
    _FakeTranscriber.calls = []
    monkeypatch.setattr(realtime, "FastWhisperTranscriber", _FakeTranscriber)
    # VAD は振幅で判定（テストを webrtcvad に依存させない）
    monkeypatch.setattr(realtime, "_webrtcvad_module", lambda: None)

    audio = np.concatenate([
        _speech(1.5), _silence(0.4), _speech(1.5),   # 0.4 秒の息継ぎ → 1 発話にまとまる
        _silence(1.5),                               # 長い間 → ここで区切る
        _speech(2.0), _silence(1.5),                 # 2 発話目（幻覚を返す → 捨てる）
        _speech(5.0), _silence(1.0),                 # 3 発話目（4 秒以上なので 0.6 秒で区切る）
    ])
    q: queue.Queue = queue.Queue()
    for i in range(0, audio.size, 4800):
        q.put(audio[i : i + 4800])
    stop = threading.Event()
    stop.set()
    out: list[tuple[str, float]] = []
    errors: list[str] = []
    realtime.run_realtime_transcription_loop(
        stop_event=stop, audio_queue=q, project_root=tmp_path,
        get_model_folder=lambda: "kotoba",
        emit_text=lambda t, s: out.append((t, s)), emit_error=errors.append,
    )
    assert not errors
    calls = _FakeTranscriber.calls
    assert len(calls) == 3
    # 1 発話目は息継ぎを含めてまとまっている（1.5 + 0.4 + 1.5 + 末尾 0.3 秒以内）
    assert 3.3 <= calls[0]["seconds"] <= 3.8
    assert calls[0]["initial_prompt"] is None
    assert calls[0]["beam_size"] == 5
    # 幻覚は出力されず、文脈ヒントにも入らない
    assert [t for t, _ in out] == ["発話1です。", "発話3です。"]
    assert calls[2]["initial_prompt"] == "発話1です。"
    # タイムスタンプは録音先頭からの秒
    assert out[1][1] == pytest.approx(1.5 + 0.4 + 1.5 + 1.5 + 2.0 + 1.5, abs=0.05)
