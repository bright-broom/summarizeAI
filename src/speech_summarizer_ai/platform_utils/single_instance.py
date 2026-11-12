"""単一プロセス（セカンド起動で既存ウィンドウを前面化）。"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication

_SINGLE_INSTANCE_SERVER_NAME = "WEEL_SpeechSummarizerAI_single_instance"


class InstanceActivationRelay(QObject):
    """2 回目起動からのローカルソケット通知。"""

    activate_requested = Signal()
    toggle_recording_requested = Signal()


def attach_single_instance(app: QApplication) -> InstanceActivationRelay | None:
    """単一インスタンス用のローカルサーバーを張る。

    セカンド起動時は先行プロセスへ接続して ``None`` を返す（呼び出し側は即終了）。

    Args:
        app: アプリケーションインスタンス（サーバ・リレーの親）。

    Returns:
        InstanceActivationRelay | None: 先行インスタンスでは前面化用シグナルを持つリレー。
            セカンドインスタンスでは ``None``。
    """
    probe = QLocalSocket()
    probe.connectToServer(_SINGLE_INSTANCE_SERVER_NAME)
    if probe.waitForConnected(500):
        probe.write(b"\x01")
        probe.flush()
        probe.waitForBytesWritten(1000)
        probe.disconnectFromServer()
        return None

    probe.abort()

    QLocalServer.removeServer(_SINGLE_INSTANCE_SERVER_NAME)
    server = QLocalServer(app)
    relay = InstanceActivationRelay(app)

    def _emit_activation() -> None:
        while server.hasPendingConnections():
            conn = server.nextPendingConnection()
            if conn is not None:
                conn.disconnectFromServer()
                conn.deleteLater()
        relay.activate_requested.emit()
        relay.toggle_recording_requested.emit()

    server.newConnection.connect(_emit_activation)

    if not server.listen(_SINGLE_INSTANCE_SERVER_NAME):
        server.deleteLater()
        return relay

    setattr(app, "_single_instance_server", server)
    return relay
