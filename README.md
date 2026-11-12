# Speech Summarizer AI

Speech Summarizer AI は、「録音 + リアルタイム文字起こし + AI 要約」を提供するアプリケーションです。

マイクで拾ったあなたの声と、オンライン会議・通話・動画などの再生音声を同時に収録し、録音中はその場で文字起こしを表示、録音停止後は内蔵 AI が自動で「会話タイトル」と「要約」を生成します。

クラウド送信は行わず、音声認識も要約 LLM も、すべて端末ローカルで動作します。
会議の音声・文字起こし・要約はあなたの PC の中だけに保存されるため、機密情報を扱う商談・1on1・社内ミーティング・インタビュー・個人のメモ取りまで、安心してお使いいただけます。

本アプリでは、MicrosoftのFoundry LocalをオンデバイスAI推論基盤として採用しています。Foundry Localはアプリ起動時にPCのハードウェア構成を検出し、利用可能なアクセラレータ (NP、GPU、CPU) の中から、最適な実行プロバイダーを自動的に選択します。


さらに、HP 製 PC の Programmable Key にも対応しています。
どのアプリを前面に開いていても、キーを 1 回押すだけで録音開始（リアルタイム文字起こしも同時に開始）、もう一度押せば録音停止と同時に AI 要約が自動的に始まります。Teams や Zoom、ブラウザの会議画面を最前面に保ったまま、物理キーひとつで「録る → 書き起こす → まとめる」が完結します。

## レイアウト

- `src/speech_summarizer_ai/` — アプリ本体（`settings` / `platform_utils` / `domain` / `data` / `audio` / `stt` / `llm` / `controllers` / `ui`）。
- `resources/icons/` — アイコン（`app.svg`、Windows 用 `app.ico` / `app.png`）。PyInstaller で同梱され EXE にも埋め込まれる。
- `scripts/` — 開発用起動（`run_dev.py` など）。
- `packaging/` — MSIX 向けマニフェスト・スクリプト、PyInstaller 用 `hook-webrtcvad` など。
- `pyproject.toml` / `requirements.txt` — 依存関係とパッケージ定義。
- 実行時データ（SQLite・録音・ローカルモデル）は `platform_utils.paths.project_root()` を基準に置く。
  - **Windows:** WinRT の `ApplicationData` が使える環境（MSIX 等）ではそのローカルフォルダ。**未パッケージの EXE** などでは `%LOCALAPPDATA%\WEEL\SpeechSummarizerAI\` 直下に `database/`・`sessions/`・`models/` ができる。
  - **Windows 以外:** リポジトリルート（`src` の親）直下に同じ名前のディレクトリを使う。
- `tests/` — テスト。
- `speech_summarizer_ai.spec` — Windows 向け PyInstaller 定義。

## セットアップと起動

仮想環境を作成して依存関係を入れます。

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

または、パッケージを editable install すると `speech-summarizer-ai` コマンドが使えます。

```bash
pip install -e .
```

開発時はリポジトリルートから次のいずれかで起動できます。

```bash
python scripts/run_dev.py
```

editable install 後は次のコマンドでも起動できます。

```bash
speech-summarizer-ai
python -m speech_summarizer_ai
```

録音は `sessions/<セッションID>/audio.wav` に保存されます（基準ディレクトリは上記の `project_root()`。Windows の配布版では **ユーザーデータ領域** 側の `sessions/` です）。

## Windows 実行ファイルの作成（PyInstaller）

前提:

- Windows PC、**このリポジトリ用**の仮想環境で `requirements.txt`（または `pip install -e .`）を満たしていること（別プロジェクトの venv だと `webrtcvad` 不足などで PyInstaller の hook が失敗することがあります）
- リポジトリルートで作業する

手順:

```bash
venv\Scripts\activate
pyinstaller --noconfirm speech_summarizer_ai.spec
```

クリーンビルドする場合:

```bash
pyinstaller --noconfirm --clean speech_summarizer_ai.spec
```

成果物は **`dist/SpeechSummarizerAI/`** フォルダ（onedir）です。`SpeechSummarizerAI.exe` と同フォルダの DLL 群を一式配布してください。
