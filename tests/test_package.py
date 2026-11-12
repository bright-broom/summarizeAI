"""パッケージのインポートとバージョン情報のスモークテスト。"""

import speech_summarizer_ai


def test_import() -> None:
    """``speech_summarizer_ai`` がインポートでき、``__version__`` が定義されていることを確認する。

    Returns:
        None
    """
    assert speech_summarizer_ai.__version__
