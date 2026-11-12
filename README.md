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
- `resources/icons/` — アイコン（`app.svg`、Windows 用 `app.ico`、macOS 用 `app.icns`）。PyInstaller で同梱され EXE にも埋め込まれる。
- `scripts/` — 開発用起動（`run_dev.py`）、macOS 用 `setup_mac.sh` / `run_mac.command`。
- `packaging/` — MSIX 向けマニフェスト・スクリプト、PyInstaller 用 `hook-webrtcvad` など。
- `pyproject.toml` / `requirements.txt` — 依存関係とパッケージ定義。
- 実行時データ（SQLite・録音・ローカルモデル）は `platform_utils.paths.project_root()` を基準に置く。
  - **Windows:** WinRT の `ApplicationData` が使える環境（MSIX 等）ではそのローカルフォルダ。**未パッケージの EXE** などでは `%LOCALAPPDATA%\WEEL\SpeechSummarizerAI\` 直下に `database/`・`sessions/`・`models/` ができる。
  - **Windows 以外:** リポジトリルート（`src` の親）直下に同じ名前のディレクトリを使う。
- `tests/` — テスト。
- `speech_summarizer_ai.spec` — Windows 向け PyInstaller 定義。
- `speech_summarizer_ai_mac.spec` — macOS 向け PyInstaller 定義（`.app`）。`scripts/build_mac_app.sh` から使う。

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

## macOS（MacBook Pro）での利用

macOS では Windows 専用の部品を次のように置き換えて動作します。

| 機能 | Windows | macOS |
| --- | --- | --- |
| マイク録音 | PyAudioWPatch (WASAPI) | sounddevice (CoreAudio) |
| PC 再生音の録音 | WASAPI ループバック | **BlackHole** 等の仮想オーディオデバイス（任意） |
| 要約 LLM | Foundry Local (WinML) | **MLX**（Apple Silicon）/ Ollama（Intel Mac） |
| データ保存先 | `%LOCALAPPDATA%\WEEL\SpeechSummarizerAI` | `~/Library/Application Support/WEEL/SpeechSummarizerAI` |

### 1. アプリ（.app）と DMG を作ってインストール

Python 3.11 以上と Xcode コマンドラインツールが必要です（未導入なら `brew install python@3.12`、`xcode-select --install`）。
ターミナルでこのフォルダに移動して次を 1 回だけ実行します（初回は 5〜10 分程度）。

```bash
./scripts/build_mac_app.sh
```

次の 2 つが作られます。

- `/Applications/Speech Summarizer AI.app` — 以降は **Launchpad / アプリケーションフォルダ / Dock からダブルクリック** で起動
- `dist/SpeechSummarizerAI-<バージョン>-<arm64|x86_64>.dmg` — 他の Mac に配る用。開いてアプリを「Applications」へドラッグするだけでインストールできます
  （Apple の公証は行っていないため、受け取った側では初回のみ右クリック →「開く」）

オプション: `--no-install`（/Applications へコピーしない）、`--no-dmg`（DMG を作らない）。
動作ログ: `~/Library/Logs/SpeechSummarizerAI.log`

#### Mac でビルドせずに DMG を作る（GitHub Actions）

このリポジトリを GitHub に push すると、GitHub の Mac 上で DMG を作れます。

- **Actions** タブ →「Build macOS DMG」→「Run workflow」→ 完了後、実行結果ページの Artifacts から DMG をダウンロード
- `v0.1.0` のようなタグを push すると、Releases に DMG が自動で添付されます

### 2. （開発用）.app を作らずに起動

```bash
./scripts/setup_mac.sh
```

```bash
./scripts/run_mac.command
```
初回起動時に音声認識モデル（Whisper）と要約モデル（`mlx-community/Qwen2.5-7B-Instruct-4bit`、約 4.3GB）をダウンロードします。
初回録音時に「ターミナルがマイクへのアクセスを求めています」と表示されたら **許可** してください
（拒否した場合は「システム設定 → プライバシーとセキュリティ → マイク」で「Speech Summarizer AI」（.app 以外で起動した場合はターミナル）を ON）。

### 3. （任意）オンライン会議・動画の音声も録音する

macOS には PC 再生音を直接録る仕組みが無いため、無料の仮想オーディオデバイス BlackHole を使います。

1. `brew install blackhole-2ch`（インストール後に再起動が必要な場合あり）
2. 「Audio MIDI 設定」アプリ →「＋」→「複数出力装置を作成」→ **スピーカー（またはヘッドホン）** と **BlackHole 2ch** にチェック
3. 「システム設定 → サウンド → 出力」でその複数出力装置を選択

アプリは名前に `BlackHole` を含む入力デバイスを自動で PC 音として使います（別デバイスを使う場合は `SSAI_LOOPBACK_DEVICE="デバイス名の一部"`）。
BlackHole が無い場合はマイクのみで録音します。

### 環境変数（任意）

| 変数 | 内容 |
| --- | --- |
| `SSAI_MLX_MODEL` | MLX モデルの HF リポジトリ。メモリ 8〜16GB の Mac は `mlx-community/Qwen2.5-3B-Instruct-4bit` 推奨 |
| `SSAI_LLM_BACKEND` | `mlx` / `openai`。Intel Mac は自動で `openai`（Ollama） |
| `SSAI_OPENAI_BASE_URL` / `SSAI_OPENAI_MODEL` | OpenAI 互換サーバー（既定 `http://localhost:11434/v1` / `qwen2.5:7b`） |
| `SSAI_LOOPBACK_DEVICE` | PC 音として使う入力デバイス名 |
| `SSAI_DATA_DIR` | DB・モデル・セッションの保存先 |

Intel Mac では事前に `brew install ollama`、`ollama serve`、`ollama pull qwen2.5:7b` を実行してください。

**補足:** 起動中にもう 1 つ起動すると、録音の開始/停止が切り替わります（HP Programmable Key と同じ仕組み）。
ショートカット.app で「シェルスクリプトを実行」に `open -n -a "Speech Summarizer AI"` を登録すれば、キーボードショートカットで録音を操作できます。

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
