"""macOS 互換レイヤのテスト（sounddevice / mlx_lm をフェイクに差し替えて Linux 等でも実行可能）。"""

from __future__ import annotations

import sys
import threading
import types
from pathlib import Path

import numpy as np
import pytest


class _FakeRawStream:
    def __init__(self, samplerate, channels, dtype, blocksize, device, latency):
        self.channels = channels
        self.device = device
        self.active = False
        self.read_available = 0 if device == 2 else blocksize

    def start(self):
        self.active = True

    def stop(self):
        self.active = False

    def close(self):
        pass

    def read(self, n):
        return bytes(np.full(n * self.channels, 1000, dtype=np.int16).tobytes()), False


def _fake_sd() -> types.ModuleType:
    sd = types.ModuleType("sounddevice")
    devs = [
        {"name": "MacBook Pro Speakers", "max_input_channels": 0, "max_output_channels": 2, "default_samplerate": 48000.0},
        {"name": "MacBook Pro Microphone", "max_input_channels": 1, "max_output_channels": 0, "default_samplerate": 48000.0},
        {"name": "BlackHole 2ch", "max_input_channels": 2, "max_output_channels": 2, "default_samplerate": 48000.0},
    ]

    def query_devices(index=None):
        return devs if index is None else devs[index]

    sd.query_devices = query_devices
    sd.default = types.SimpleNamespace(device=[1, 0])
    sd.RawInputStream = _FakeRawStream
    return sd


def test_mac_audio_session_records_mic_and_blackhole(monkeypatch):
    monkeypatch.setitem(sys.modules, "sounddevice", _fake_sd())
    monkeypatch.setattr(sys, "platform", "darwin")
    from speech_summarizer_ai.audio import backend

    monkeypatch.setattr(backend, "_pa_module", None)
    chunks: list[np.ndarray] = []
    stop = threading.Event()
    err: list[str | None] = [None]

    def cb(c):
        chunks.append(c)
        if len(chunks) >= 5:
            stop.set()

    t = threading.Thread(
        target=backend.run_recording_session, args=(stop, err), kwargs={"live_mono_chunk_callback": cb}
    )
    t.start()
    t.join(5)
    assert not t.is_alive()
    assert err[0] is None
    assert len(chunks) >= 5 and chunks[0].dtype == np.int16 and chunks[0].size == 1024


def test_mac_llm_backend_via_foundry_interface(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setenv("SSAI_LLM_BACKEND", "mlx")
    monkeypatch.setenv("SSAI_DATA_DIR", str(tmp_path))

    # フェイク mlx_lm
    mlx_lm = types.ModuleType("mlx_lm")
    su = types.ModuleType("mlx_lm.sample_utils")

    class Tok:
        def apply_chat_template(self, messages, add_generation_prompt, tokenize):
            return "PROMPT:" + messages[-1]["content"][:10]

    mlx_lm.load = lambda path: ("MODEL", Tok())
    mlx_lm.stream_generate = lambda m, t, p, **kw: iter(
        [types.SimpleNamespace(text="会議"), types.SimpleNamespace(text="の要約。")]
    )
    su.make_sampler = lambda **kw: None
    su.make_logits_processors = lambda **kw: []
    monkeypatch.setitem(sys.modules, "mlx_lm", mlx_lm)
    monkeypatch.setitem(sys.modules, "mlx_lm.sample_utils", su)

    from speech_summarizer_ai.llm import foundry_local, mac_backend
    from speech_summarizer_ai.platform_utils import paths

    monkeypatch.setattr(foundry_local.FoundryLocalSummarizer, "_manager_initialized", False)
    root = paths.project_root()
    assert root == tmp_path
    cache = paths.foundry_llm_cache_directory(root)

    s = foundry_local.FoundryLocalSummarizer(project_root=root)
    with pytest.raises(foundry_local.FoundryLocalModelNotCachedError):
        s.load_model(allow_download=False)

    # 重みが揃った状態を再現
    d = mac_backend.mlx_local_dir(cache)
    d.mkdir(parents=True)
    (d / "config.json").write_text("{}")
    (d / "model.safetensors").write_bytes(b"\0" * (2 * 1024 * 1024))
    assert mac_backend.mlx_weights_present(cache)

    s.load_model(allow_download=False)
    title = s.generate_conversation_title("今日は予算について話しました。")
    assert "会議" in title
    s.unload()
