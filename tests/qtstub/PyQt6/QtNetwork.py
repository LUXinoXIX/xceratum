from ._base import QObject, pyqtSignal


class QLocalSocket(QObject):
    def connectToServer(self, name):
        pass

    def waitForConnected(self, ms):
        return False


class QLocalServer(QObject):
    newConnection = pyqtSignal()

    @staticmethod
    def removeServer(name):
        pass

    def listen(self, name):
        return True
