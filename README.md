# Speech Summarizer AI

Speech Summarizer AI は、「録音 + リアルタイム文字起こし + AI 要約」を提供するデスクトップアプリです。**Windows** と **macOS（Apple Silicon の MacBook Pro など）** で動作します。

マイクで拾ったあなたの声と、オンライン会議・通話・動画などの再生音声を同時に収録し、録音中はその場で文字起こしを表示、録音停止後は内蔵 AI が自動で「会話タイトル」と「要約」を生成します。

クラウド送信は行わず、音声認識も要約 LLM も、すべて端末ローカルで動作します。
会議の音声・文字起こし・要約はあなたの PC の中だけに保存されるため、機密情報を扱う商談・1on1・社内ミーティング・インタビュー・個人のメモ取りまで、安心してお使いいただけます。

- **Windows:** Microsoft の Foundry Local をオンデバイス AI 推論基盤として採用しています。起動時に PC のハードウェア構成を検出し、利用可能なアクセラレータ（NPU、GPU、CPU）から最適な実行プロバイダーを自動的に選択します。
- **macOS:** Apple の MLX で、Apple Silicon の GPU（Metal）を使って要約 LLM を実行します。

さらに、HP 製 PC の Programmable Key にも対応しています。
どのアプリを前面に開いていても、キーを 1 回押すだけで録音開始（リアルタイム文字起こしも同時に開始）、もう一度押せば録音停止と同時に AI 要約が自動的に始まります。Teams や Zoom、ブラウザの会議画面を最前面に保ったまま、物理キーひとつで「録る → 書き起こす → まとめる」が完結します（Mac ではキーボードショートカットで同じことができます。[後述](#録音をキーボードショートカットで操作する)）。

---

## Mac で使う（DMG からインストール）

Apple Silicon（M1 以降）の Mac 向けです。Intel Mac は [Intel Mac の場合](#intel-mac-の場合) を参照してください。

### 1. DMG をダウンロード

次のどちらかから `SpeechSummarizerAI-<バージョン>-arm64.dmg` を取得します（GitHub へのログインが必要）。

- **Releases**（タグを付けて公開した版）: リポジトリの「Releases」ページ
- **最新のビルド**: 「Actions」タブ →「Build macOS DMG」→ 一番上の成功した実行 → ページ下部の **Artifacts** にある `SpeechSummarizerAI-macOS-dmg`（zip を解凍すると DMG が出てきます。保存期間は 90 日）

### 2. インストールと初回起動

1. DMG を開き、「Speech Summarizer AI」を「Applications」フォルダへドラッグします。
2. アプリケーションフォルダ（または Launchpad）から「Speech Summarizer AI」をダブルクリックします。
   - 「開発元を確認できないため開けません」と出た場合は、アイコンを **右クリック →「開く」→「開く」**。
     macOS 15 以降は「システム設定 → プライバシーとセキュリティ」下部の **「このまま開く」** を押します。
     （Apple の公証を受けていないためで、初回のみ必要です）
3. マイクへのアクセスを求められたら **「許可」** します。
   拒否してしまった場合は「システム設定 → プライバシーとセキュリティ → マイク」で「Speech Summarizer AI」を ON にしてください。
4. 初回起動時に AI モデルを自動でダウンロードします（音声認識 Whisper と要約用 `mlx-community/Qwen2.5-7B-Instruct-4bit`、合計約 5GB）。2 回目以降はすぐ起動します。

### 3. （任意）オンライン会議・動画の音声も録音する

macOS には PC の再生音を直接録る仕組みが無いため、無料の仮想オーディオデバイス **BlackHole** を使います。設定しない場合はマイクの音だけを録音します。

1. `brew install blackhole-2ch` でインストール（必要なら Mac を再起動）
2. 「Audio MIDI 設定」アプリ → 左下の「＋」→「複数出力装置を作成」→ **スピーカー（またはヘッドホン）** と **BlackHole 2ch** にチェック
3. 「システム設定 → サウンド → 出力」で、作成した複数出力装置を選択

アプリは名前に `BlackHole` を含む入力デバイスを自動で PC 音として使います。

### 保存場所

| 内容 | 場所 |
| --- | --- |
| 会議データ・文字起こし・要約・AI モデル | `~/Library/Application Support/WEEL/SpeechSummarizerAI/` |
| 動作ログ（不具合調査用） | `~/Library/Logs/SpeechSummarizerAI.log` |

アンインストールはアプリをゴミ箱へ入れ、必要なら上記のフォルダも削除します。

### 録音をキーボードショートカットで操作する

アプリ起動中にもう 1 つ起動すると、録音の開始/停止が切り替わります（HP Programmable Key と同じ仕組み）。
「ショートカット」アプリで新規ショートカットに「シェルスクリプトを実行」を追加し、次を入力してキーボードショートカットを割り当てます。

```bash
open -n -a "Speech Summarizer AI"
```

### メモリが少ない Mac の場合

要約モデルは 16GB 以上のメモリを想定しています。8〜16GB の Mac では、ターミナルで次を実行してから起動すると小さいモデルを使います。

```bash
launchctl setenv SSAI_MLX_MODEL mlx-community/Qwen2.5-3B-Instruct-4bit
```

### Intel Mac の場合

配布している DMG は Apple Silicon 専用です。Intel Mac では [Mac で自分でビルドする](#mac-で自分でビルドする) 手順で作成してください。要約には MLX の代わりに Ollama を使うため、事前に次を実行しておきます。

```bash
brew install ollama
```

```bash
ollama pull qwen2.5:7b
```

（Ollama アプリを起動しておくか、`ollama serve` を実行しておきます）

---

## Mac で自分でビルドする

Python 3.11 以上と Xcode コマンドラインツールが必要です。

```bash
brew install python@3.12
```

```bash
xcode-select --install
```

リポジトリのルートで次を 1 回実行します（初回は 5〜10 分程度）。

```bash
./scripts/build_mac_app.sh
```

次の 2 つが作られます。

- `/Applications/Speech Summarizer AI.app` — そのままダブルクリックで起動できます
- `dist/SpeechSummarizerAI-<バージョン>-<arm64|x86_64>.dmg` — 他の Mac に配る用

オプション: `--no-install`（/Applications へコピーしない）、`--no-dmg`（DMG を作らない）。

### GitHub Actions で DMG を作る

`.github/workflows/build-macos-dmg.yml` が、GitHub の Mac（Apple Silicon）上で `.app` と DMG を作成します。

- **手動実行:** 「Actions」タブ →「Build macOS DMG」→「Run workflow」
- **リリース:** `v0.1.0` のように `v` で始まるタグを push すると、Releases に DMG が自動で添付されます

```bash
git tag v0.1.0
```

```bash
git push origin v0.1.0
```

ビルド後に、作成した `.app` に同梱ライブラリ（MLX・sounddevice・faster-whisper・PySide6 など）が読み込めるかを確認するセルフテスト（`SSAI_SELFTEST=1`）を実行します。失敗した場合はジョブが失敗し、DMG はアップロード・リリースされません。

### .app を作らずに開発用に起動する

```bash
./scripts/setup_mac.sh
```

```bash
./scripts/run_mac.command
```

この方法ではマイク許可が「ターミナル」に対して求められます。

### macOS 版の仕組み

Windows 専用の部品を次のように置き換えています。

| 機能 | Windows | macOS |
| --- | --- | --- |
| マイク録音 | PyAudioWPatch (WASAPI) | sounddevice (CoreAudio)。`audio/mac_pyaudio_compat.py` |
| PC 再生音の録音 | WASAPI ループバック | BlackHole 等の仮想オーディオデバイス（任意） |
| 要約 LLM | Foundry Local (WinML) | MLX（Apple Silicon）/ Ollama 等の OpenAI 互換サーバー（Intel）。`llm/mac_backend.py` |
| データ保存先 | `%LOCALAPPDATA%\WEEL\SpeechSummarizerAI` | `~/Library/Application Support/WEEL/SpeechSummarizerAI` |
| 実行ファイル | `speech_summarizer_ai.spec`（EXE） | `speech_summarizer_ai_mac.spec`（.app / DMG） |

### 環境変数（任意）

`.app` に渡す場合は `launchctl setenv 変数名 値` を実行してからアプリを起動します（Mac を再起動すると解除されます）。

| 変数 | 内容 |
| --- | --- |
| `SSAI_MLX_MODEL` | MLX モデルの Hugging Face リポジトリ（既定 `mlx-community/Qwen2.5-7B-Instruct-4bit`） |
| `SSAI_LLM_BACKEND` | `mlx` / `openai`。Intel Mac は自動で `openai` |
| `SSAI_OPENAI_BASE_URL` / `SSAI_OPENAI_MODEL` | OpenAI 互換サーバー（既定 `http://localhost:11434/v1` / `qwen2.5:7b`） |
| `SSAI_LOOPBACK_DEVICE` | PC 音として使う入力デバイス名（部分一致。既定は `BlackHole` 等を自動検出） |
| `SSAI_DATA_DIR` | DB・モデル・セッションの保存先 |

---

## Windows で使う

### セットアップと起動

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

録音は `sessions/<セッションID>/audio.wav` に保存されます（基準ディレクトリは後述の `project_root()`。Windows の配布版では **ユーザーデータ領域** 側の `sessions/` です）。

### Windows 実行ファイルの作成（PyInstaller）

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

---

## リポジトリ構成

- `src/speech_summarizer_ai/` — アプリ本体（`settings` / `platform_utils` / `domain` / `data` / `audio` / `stt` / `llm` / `controllers` / `ui`）。
- `resources/icons/` — アイコン（`app.svg`、Windows 用 `app.ico`、macOS 用 `app.icns`）。PyInstaller で EXE / .app に同梱される。
- `scripts/` — 開発用起動 `run_dev.py`、macOS 用 `setup_mac.sh` / `run_mac.command` / `build_mac_app.sh`。
- `packaging/` — PyInstaller 用 `hook-webrtcvad` など。
- `.github/workflows/build-macos-dmg.yml` — macOS 用 DMG を GitHub Actions でビルド。
- `pyproject.toml` — パッケージ定義。`requirements.txt`（Windows）/ `requirements-mac.txt`（macOS）— 依存関係。
- `speech_summarizer_ai.spec` — Windows 向け PyInstaller 定義。`speech_summarizer_ai_mac.spec` — macOS 向け（.app）。
- `tests/` — テスト（`test_macos_compat.py` は macOS 用の録音・要約レイヤを Windows / Linux 上でも検証できる）。
- 実行時データ（SQLite・録音・ローカルモデル）は `platform_utils.paths.project_root()` を基準に `database/`・`sessions/`・`models/` を置く。
  - **Windows:** WinRT の `ApplicationData` が使える環境（MSIX 等）ではそのローカルフォルダ。**未パッケージの EXE** などでは `%LOCALAPPDATA%\WEEL\SpeechSummarizerAI\`。
  - **macOS:** `~/Library/Application Support/WEEL/SpeechSummarizerAI/`（`SSAI_DATA_DIR` で変更可）。
  - **その他の OS:** リポジトリルート（`src` の親）。
