"""macOS 用 LLM バックエンド（Foundry Local SDK 互換の最小インターフェース）。

Foundry Local（WinML）は Windows 専用のため、macOS では次のいずれかで要約を実行する。

- ``mlx``（既定・Apple Silicon）: ``mlx-lm`` でプロセス内推論。重みは Hugging Face から
  ``models/llm/<repo>`` に取得する（``settings.llm.MAC_MLX_MODEL_REPO``）。
- ``openai``: Ollama / LM Studio など OpenAI 互換のローカルサーバーへ接続する
  （Intel Mac 向け）。環境変数 ``SSAI_LLM_BACKEND=openai`` で有効化。

:mod:`speech_summarizer_ai.llm.foundry_local` が期待する
``Configuration`` / ``FoundryLocalManager`` / ``catalog.get_model()`` / ``get_chat_client()``
/ ``complete_chat()`` / ``complete_streaming_chat()`` の形だけを再現する。
"""

from __future__ import annotations

import gc
import json
import os
import platform
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from speech_summarizer_ai import settings as config


def backend_name() -> str:
    """使用するバックエンド名（``mlx`` または ``openai``）を返す。"""
    env = os.environ.get("SSAI_LLM_BACKEND", "").strip().lower()
    if env in ("mlx", "openai"):
        return env
    # Intel Mac では MLX が動かないため OpenAI 互換サーバーを既定にする。
    return "mlx" if platform.machine() == "arm64" else "openai"


def mlx_repo_id() -> str:
    """MLX 用 Hugging Face リポジトリ ID。"""
    return os.environ.get("SSAI_MLX_MODEL", "").strip() or config.MAC_MLX_MODEL_REPO


def mlx_local_dir(cache_dir: Path) -> Path:
    """``models/llm`` 配下の MLX 重み配置先。"""
    return cache_dir / mlx_repo_id().replace("/", "__")


def mlx_weights_present(cache_dir: Path) -> bool:
    """MLX 重み（``config.json`` と ``*.safetensors``）が揃っているか。"""
    d = mlx_local_dir(cache_dir)
    if not (d / "config.json").is_file():
        return False
    if (d / ".download_incomplete").exists():
        return False
    return any(p.stat().st_size > 1024 * 1024 for p in d.glob("*.safetensors"))


def _chunk(text: str) -> Any:
    """OpenAI 風ストリーミングチャンクを作る。"""
    delta = SimpleNamespace(content=text, role="assistant")
    return SimpleNamespace(choices=[SimpleNamespace(delta=delta)])


def _complete(text: str) -> Any:
    """OpenAI 風の非ストリーミング応答を作る。"""
    msg = SimpleNamespace(role="assistant", content=text)
    return SimpleNamespace(choices=[SimpleNamespace(message=msg)])


class _ChatSettings:
    """``client.settings`` 相当（foundry_local が属性を書き換える）。"""

    def __init__(self) -> None:
        self.temperature: float = 0.3
        self.max_tokens: int = 4096
        self.top_p: float = 1.0
        self.repetition_penalty: float | None = None


# --------------------------------------------------------------------------- MLX


class _MlxChatClient:
    def __init__(self, owner: _MlxModel) -> None:
        self._owner = owner
        self.settings = _ChatSettings()

    def complete_streaming_chat(self, messages: list[dict[str, str]]) -> Iterator[Any]:
        from mlx_lm import stream_generate  # noqa: PLC0415
        from mlx_lm.sample_utils import make_logits_processors, make_sampler  # noqa: PLC0415

        model, tokenizer = self._owner._require_loaded()
        prompt = tokenizer.apply_chat_template(
            messages, add_generation_prompt=True, tokenize=False
        )
        s = self.settings
        sampler = make_sampler(temp=float(s.temperature), top_p=float(s.top_p or 1.0))
        procs = (
            make_logits_processors(repetition_penalty=float(s.repetition_penalty))
            if s.repetition_penalty
            else None
        )
        with self._owner._gen_lock:
            for resp in stream_generate(
                model,
                tokenizer,
                prompt,
                max_tokens=int(s.max_tokens),
                sampler=sampler,
                logits_processors=procs,
            ):
                if resp.text:
                    yield _chunk(resp.text)

    def complete_chat(self, messages: list[dict[str, str]]) -> Any:
        parts = [c.choices[0].delta.content for c in self.complete_streaming_chat(messages)]
        return _complete("".join(parts))


class _MlxModel:
    def __init__(self, cache_dir: Path) -> None:
        self._cache_dir = cache_dir
        self.id = mlx_repo_id()
        self.alias = config.FOUNDRY_LLM_MODEL_ALIAS
        self._model: Any = None
        self._tokenizer: Any = None
        self._gen_lock = threading.Lock()

    def download(self, progress: Callable[[float], None] | None = None) -> None:
        from huggingface_hub import HfApi, snapshot_download  # noqa: PLC0415

        dest = mlx_local_dir(self._cache_dir)
        dest.mkdir(parents=True, exist_ok=True)
        if mlx_weights_present(self._cache_dir):
            if progress:
                progress(100.0)
            return
        marker = dest / ".download_incomplete"
        marker.touch()
        total = 0
        try:
            info = HfApi().model_info(self.id, files_metadata=True)
            total = sum(int(getattr(f, "size", 0) or 0) for f in info.siblings or [])
        except Exception:  # noqa: BLE001
            total = 0

        err: list[BaseException] = []

        def _run() -> None:
            try:
                snapshot_download(repo_id=self.id, local_dir=str(dest))
            except BaseException as e:  # noqa: BLE001
                err.append(e)

        t = threading.Thread(target=_run, daemon=True)
        t.start()
        while t.is_alive():
            t.join(0.5)
            if progress and total > 0:
                done = sum(p.stat().st_size for p in dest.rglob("*") if p.is_file())
                progress(min(99.0, done * 100.0 / total))
        if err:
            raise err[0]
        marker.unlink(missing_ok=True)
        if progress:
            progress(100.0)

    def load(self) -> None:
        if self._model is not None:
            return
        if not mlx_weights_present(self._cache_dir):
            raise RuntimeError(
                f"Model path does not exist: {mlx_local_dir(self._cache_dir)}"
            )
        try:
            from mlx_lm import load  # noqa: PLC0415
        except ImportError as e:
            raise RuntimeError(
                "mlx-lm が見つかりません。pip install mlx-lm を実行してください。"
            ) from e
        self._model, self._tokenizer = load(str(mlx_local_dir(self._cache_dir)))

    def unload(self) -> None:
        self._model = None
        self._tokenizer = None
        gc.collect()
        try:
            import mlx.core as mx  # noqa: PLC0415

            mx.clear_cache()
        except Exception:  # noqa: BLE001
            pass

    def _require_loaded(self) -> tuple[Any, Any]:
        if self._model is None:
            raise RuntimeError("MLX モデルが未ロードです。")
        return self._model, self._tokenizer

    def get_chat_client(self) -> _MlxChatClient:
        if not hasattr(self, "_client"):
            self._client = _MlxChatClient(self)
        return self._client


# ------------------------------------------------------- OpenAI 互換（Ollama 等）


def openai_base_url() -> str:
    return os.environ.get("SSAI_OPENAI_BASE_URL", "").strip() or config.MAC_OPENAI_BASE_URL


def openai_model_name() -> str:
    return os.environ.get("SSAI_OPENAI_MODEL", "").strip() or config.MAC_OPENAI_MODEL


class _OpenAIChatClient:
    def __init__(self) -> None:
        self.settings = _ChatSettings()

    def _payload(self, messages: list[dict[str, str]], stream: bool) -> dict[str, Any]:
        s = self.settings
        body: dict[str, Any] = {
            "model": openai_model_name(),
            "messages": messages,
            "temperature": float(s.temperature),
            "top_p": float(s.top_p or 1.0),
            "max_tokens": int(s.max_tokens),
            "stream": stream,
        }
        if s.repetition_penalty:
            body["frequency_penalty"] = min(2.0, (float(s.repetition_penalty) - 1.0) * 4)
        return body

    def complete_streaming_chat(self, messages: list[dict[str, str]]) -> Iterator[Any]:
        import httpx  # noqa: PLC0415

        url = openai_base_url().rstrip("/") + "/chat/completions"
        with httpx.stream(
            "POST", url, json=self._payload(messages, True), timeout=httpx.Timeout(600.0)
        ) as r:
            r.raise_for_status()
            for line in r.iter_lines():
                line = line.strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    obj = json.loads(data)
                    text = obj["choices"][0]["delta"].get("content")
                except (ValueError, KeyError, IndexError):
                    continue
                if text:
                    yield _chunk(text)

    def complete_chat(self, messages: list[dict[str, str]]) -> Any:
        import httpx  # noqa: PLC0415

        url = openai_base_url().rstrip("/") + "/chat/completions"
        r = httpx.post(url, json=self._payload(messages, False), timeout=600.0)
        r.raise_for_status()
        return _complete(r.json()["choices"][0]["message"]["content"] or "")


class _OpenAIModel:
    def __init__(self) -> None:
        self.id = f"{openai_model_name()}@{openai_base_url()}"
        self.alias = config.FOUNDRY_LLM_MODEL_ALIAS
        self._client = _OpenAIChatClient()

    def download(self, progress: Callable[[float], None] | None = None) -> None:
        # モデル取得はサーバー側（例: ``ollama pull qwen2.5:7b``）で行う。
        self.load()
        if progress:
            progress(100.0)

    def load(self) -> None:
        import httpx  # noqa: PLC0415

        url = openai_base_url().rstrip("/") + "/models"
        try:
            r = httpx.get(url, timeout=5.0)
            r.raise_for_status()
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(
                f"ローカル LLM サーバー {openai_base_url()} に接続できません。"
                f"Ollama を起動し `ollama pull {openai_model_name()}` を実行してください。({e})"
            ) from e

    def unload(self) -> None:
        pass

    def get_chat_client(self) -> _OpenAIChatClient:
        return self._client


# ------------------------------------------------------- Foundry 互換の入口


class Configuration:
    def __init__(self, app_name: str = "", model_cache_dir: str | None = None, **_: Any) -> None:
        self.app_name = app_name
        self.model_cache_dir = model_cache_dir


class _Catalog:
    def __init__(self, cache_dir: Path) -> None:
        self._cache_dir = cache_dir

    def get_model(self, _alias: str) -> Any:
        if backend_name() == "openai":
            return _OpenAIModel()
        return _MlxModel(self._cache_dir)

    def list_models(self) -> list[Any]:
        return []


class FoundryLocalManager:
    instance: FoundryLocalManager | None = None

    def __init__(self, cfg: Configuration) -> None:
        from speech_summarizer_ai.platform_utils import paths  # noqa: PLC0415

        cache = (
            Path(cfg.model_cache_dir)
            if cfg.model_cache_dir
            else paths.foundry_llm_cache_directory(paths.project_root())
        )
        self.catalog = _Catalog(cache)

    @classmethod
    def initialize(cls, cfg: Configuration) -> None:
        cls.instance = cls(cfg)

    def download_and_register_eps(self, progress_callback: Any = None) -> None:
        # Metal / サーバー側で推論するため EP 登録は不要。
        _ = progress_callback
        time.sleep(0)
