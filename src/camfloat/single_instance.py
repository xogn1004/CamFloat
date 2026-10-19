"""One settings writer per profile; opening the EXE again restores its window."""
import hashlib

from PySide6.QtCore import QLockFile, QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from camfloat.camera_model import data_path


class InstanceGuard(QObject):
    activated = Signal()

    def __init__(self):
        super().__init__()
        path = data_path()
        self.name = 'CamFloat-' + hashlib.sha256(str(path).casefold().encode()).hexdigest()[:24]
        self.lock = QLockFile(str(path.with_suffix('.lock')))
        self.server = QLocalServer(self)
        self.server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        self.server.newConnection.connect(self.connection)

    def acquire(self):
        if self.lock.tryLock(0):
            QLocalServer.removeServer(self.name)
            if not self.server.listen(self.name):
                self.lock.unlock()
                raise RuntimeError('프로그램 활성화 채널을 열지 못했습니다.')
            return True
        socket = QLocalSocket(self)
        socket.connectToServer(self.name)
        if socket.waitForConnected(1000):
            socket.write(b'activate')
            socket.waitForBytesWritten(500)
            socket.disconnectFromServer()
        return False

    def connection(self):
        while self.server.hasPendingConnections():
            socket = self.server.nextPendingConnection()
            socket.disconnectFromServer()
            socket.deleteLater()
            self.activated.emit()

    def release(self):
        self.server.close()
        self.lock.unlock()
