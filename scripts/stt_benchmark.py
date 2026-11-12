"""日本語文字起こしの精度・速度ベンチマーク（macOS 用）。

macOS 標準の日本語音声（say コマンド）で読み上げた音声を、アプリと同じリアルタイム経路
（VAD 区切り → faster-whisper）に流し、文字誤り率（CER）と処理時間をモデル別に測る。

    python scripts/stt_benchmark.py --models base small kotoba

``--legacy`` を付けると、改善前の処理（アンチエイリアス無しの間引き・0.25 秒区切り・
ビーム 3・文脈ヒント無し・幻覚フィルタ無し）でも測って比較する。
結果は Markdown 表で標準出力（GitHub Actions ではジョブ概要）に出す。
"""

from __future__ import annotations

import argparse
import os
import queue
import subprocess
import sys
import tempfile
import threading
import time
import wave
from pathlib import Path

import numpy as np

# 正解は議事録として自然な表記（数字は算用数字）。読み上げは say が数字を自然に読む。
SENTENCES = [
    "本日は第4四半期の予算執行状況と、来期の採用計画について確認します。",
    "マーケティング予算は現時点で85%を消化しています。",
    "来期はエンジニアを2名、1月から採用する方向で進めたいと考えています。",
    "顧客A社の導入スケジュールは、12月の第2週に後ろ倒しになりました。",
    "シングルサインオン連携の検証が残課題なので、来週火曜日までに対応します。",
    "佐藤さんは採用要件を11月20日までにまとめて、共有してください。",
    "田中さんからは予算の再配分案を、次回の定例会議で説明してもらいます。",
    "それでは、本日の会議はここまでとします。お疲れ様でした。",
]
GAP_SECONDS = 1.2
SR = 48_000


def find_japanese_voice() -> str:
    out = subprocess.run(["say", "-v", "?"], capture_output=True, text=True, check=True).stdout
    voices = [ln.split()[0] for ln in out.splitlines() if "ja_JP" in ln or "ja-JP" in ln]
    for preferred in ("Kyoko", "Otoya"):
        if preferred in voices:
            return preferred
    if voices:
        return voices[0]
    raise SystemExit("日本語の音声（ja_JP）が見つかりません: say -v '?'")


def synthesize(voice: str, text: str, workdir: Path, idx: int) -> np.ndarray:
    path = workdir / f"s{idx}.wav"
    subprocess.run(
        ["say", "-v", voice, "-o", str(path), "--file-format=WAVE",
         f"--data-format=LEI16@{SR}", text],
        check=True,
    )
    with wave.open(str(path), "rb") as w:
        assert w.getframerate() == SR, w.getframerate()
        data = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
        if w.getnchannels() > 1:
            data = data.reshape(-1, w.getnchannels())[:, 0]
    return data.copy()


def build_audio(voice: str) -> np.ndarray:
    rng = np.random.default_rng(0)
    parts: list[np.ndarray] = []
    with tempfile.TemporaryDirectory() as d:
        for i, s in enumerate(SENTENCES):
            parts.append(synthesize(voice, s, Path(d), i))
            parts.append(np.zeros(int(SR * GAP_SECONDS), dtype=np.int16))
    audio = np.concatenate(parts).astype(np.float32)
    # 会議室程度の背景ノイズ（白色雑音 + 高域ノイズ。高域は旧リサンプラで折り返す）
    noise = rng.normal(0, 120, audio.size)
    t = np.arange(audio.size) / SR
    hiss = 150 * np.sin(2 * np.pi * 13_500 * t)
    return np.clip(audio + noise + hiss, -32768, 32767).astype(np.int16)


def normalize(s: str) -> str:
    import unicodedata

    s = unicodedata.normalize("NFKC", s).replace("お疲れさま", "お疲れ様")
    drop = set("。、，．,.!！?？・…「」『』（）() 　\n")
    return "".join(ch for ch in s if ch not in drop)


def cer(ref: str, hyp: str) -> float:
    r, h = normalize(ref), normalize(hyp)
    prev = list(range(len(h) + 1))
    for i, rc in enumerate(r, 1):
        cur = [i] + [0] * len(h)
        for j, hc in enumerate(h, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (rc != hc))
        prev = cur
    return prev[-1] / max(1, len(r))


FEATURES = ("resample", "normalize", "segment", "prompt", "beam", "filter")

# 比較する組み合わせ（改善前 = 何も有効にしない）
VARIANTS: dict[str, tuple[str, ...]] = {
    "改善前": (),
    "+リサンプル": ("resample",),
    "+音量補正": ("normalize",),
    "+区切り方": ("segment",),
    "+文脈ヒント": ("prompt",),
    "+ビーム5": ("beam",),
    "+幻覚除去": ("filter",),
    "すべて": FEATURES,
    "文脈ヒント以外": tuple(f for f in FEATURES if f != "prompt"),
}


def apply_variant(realtime_mod, engine_mod, config, enabled: tuple[str, ...]) -> None:
    """有効にしない改善を、改善前の処理に戻す（比較用）。"""

    def naive_resample(x, *, src_sr, dst_sr):
        n_out = max(1, int(round(x.size * dst_sr / src_sr)))
        t_old = np.linspace(0.0, 1.0, num=x.size, endpoint=False)
        t_new = np.linspace(0.0, 1.0, num=n_out, endpoint=False)
        return np.interp(t_new, t_old, x.astype(np.float64)).astype(np.float32)

    if "resample" not in enabled:
        engine_mod._resample_linear_float32 = naive_resample
    if "normalize" not in enabled:
        engine_mod._normalize_level = lambda x, **_: x
    if "filter" not in enabled:
        realtime_mod.is_probable_hallucination = lambda t: not t.strip()
    if "segment" not in enabled:
        config.REALTIME_SILENCE_FRAMES_10MS = 25
        config.REALTIME_SHORT_UTTERANCE_SILENCE_FRAMES_10MS = 25
        config.REALTIME_MERGE_MIN_SECONDS = 0.0
        realtime_mod.LEGACY_DROP_PAUSES = True
    if "beam" not in enabled:
        config.STT_BEAM_SIZE = 3
    if "prompt" not in enabled:
        config.STT_CONTEXT_PROMPT_CHARS = 0


def run_once(project_root: Path, model: str, audio: np.ndarray) -> tuple[str, float]:
    from speech_summarizer_ai.stt import realtime

    q: queue.Queue = queue.Queue()
    for i in range(0, audio.size, 1024):
        q.put(audio[i : i + 1024])
    stop = threading.Event()
    stop.set()
    texts: list[str] = []
    errors: list[str] = []
    t0 = time.perf_counter()
    realtime.run_realtime_transcription_loop(
        stop_event=stop, audio_queue=q, project_root=project_root,
        get_model_folder=lambda: model,
        emit_text=lambda t, _s: texts.append(t), emit_error=errors.append,
    )
    elapsed = time.perf_counter() - t0
    if errors:
        raise SystemExit(f"{model}: {errors}")
    return "".join(texts), elapsed


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", nargs="+", default=["base", "small", "kotoba"])
    ap.add_argument("--legacy", action="store_true", help="改善前・改善ごとの効果も測る（要因分析）")
    ap.add_argument("--data-dir", default=os.environ.get("SSAI_DATA_DIR") or tempfile.mkdtemp())
    args = ap.parse_args()

    os.environ["SSAI_DATA_DIR"] = args.data_dir
    from speech_summarizer_ai.platform_utils import paths
    from speech_summarizer_ai.stt.model_downloader import download_stt_model

    root = paths.project_root()
    voice = find_japanese_voice()
    audio = build_audio(voice)
    seconds = audio.size / SR
    reference = "".join(SENTENCES)
    print(f"音声: {voice}, {seconds:.1f} 秒, CPU スレッド: {os.cpu_count()}", file=sys.stderr)

    rows: list[tuple[str, str, float, float, str]] = []
    np.save(Path(args.data_dir) / "audio.npy", audio)
    variants = VARIANTS if args.legacy else {"すべて": FEATURES}
    for model in args.models:
        print(f"== {model}: ダウンロード", file=sys.stderr)
        download_stt_model(root, model)
        for label, enabled in variants.items():
            # 設定値をモジュールごと差し替えるため、組み合わせごとに別プロセスで測る
            code = (
                "import sys, json; import scripts.stt_benchmark as b;"
                "from speech_summarizer_ai import settings as c;"
                "from speech_summarizer_ai.stt import realtime as r, faster_whisper_engine as e;"
                f"b.apply_variant(r, e, c, {tuple(enabled)!r});"
                "import numpy as np; from pathlib import Path;"
                f"a = np.load({str(Path(args.data_dir) / 'audio.npy')!r});"
                f"h, s = b.run_once(Path({str(root)!r}), {model!r}, a);"
                "print(json.dumps([h, s]))"
            )
            out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                                 env={**os.environ, "PYTHONPATH": os.getcwd()})
            if out.returncode != 0:
                print(f"   {model} {label}: 失敗\n{out.stderr[-2000:]}", file=sys.stderr)
                continue
            import json

            hyp, sec = json.loads(out.stdout.strip().splitlines()[-1])
            rows.append((model, label, cer(reference, hyp), sec / seconds, hyp))
            print(f"   {model} {label}: CER={rows[-1][2]:.1%} RTF={rows[-1][3]:.2f}", file=sys.stderr)

    print(f"### 日本語文字起こしベンチマーク（{voice} の読み上げ {seconds:.0f} 秒・背景ノイズあり）\n")
    print("| モデル | 処理 | 文字誤り率 (CER) ↓ | 処理時間 / 音声長 ↓ |")
    print("| --- | --- | --- | --- |")
    for model, label, c, rtf, _ in rows:
        print(f"| {model} | {label} | {c:.1%} | {rtf:.2f} |")
    print("\n<details><summary>認識結果</summary>\n")
    print(f"**正解**: {reference}\n")
    for model, label, c, _, hyp in rows:
        print(f"**{model}（{label}, CER {c:.1%}）**: {hyp}\n")
    print("</details>")
    return 0


if __name__ == "__main__":
    sys.exit(main())
