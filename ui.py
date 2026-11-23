import sys

from PyQt6.QtCore import QMetaObject, QObject, Qt, QThread, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import (
    QApplication, QLineEdit, QMainWindow, QPushButton, QTextEdit,
    QVBoxLayout, QWidget,
)

from core.events import bus
from core.jarvis import Jarvis

STATUS_TEXT = {
    "idle": "Готов", "thinking": "Думаю...", "agent": "Агент работает...",
    "memory": "Сохраняю в память...", "listening": "Слушаю...",
    "transcribing": "Распознаю...", "speaking": "Говорю...",
}


class JarvisWorker(QObject):
    """Живёт в рабочем потоке. С ядром работаем только отсюда."""

    ready = pyqtSignal()
    reply_ready = pyqtSignal(object)      # core.jarvis.Reply
    event_received = pyqtSignal(object)   # core.events.Event

    def __init__(self):
        super().__init__()
        self.jarvis = None

    @pyqtSlot()
    def start(self):
        bus.console_enabled = False                # консоль окну не нужна
        bus.subscribe(self.event_received.emit)    # событие -> сигнал Qt
        self.jarvis = Jarvis(background_memory=True)
        self.ready.emit()

    @pyqtSlot(str)
    def send(self, text):
        self.reply_ready.emit(self.jarvis.handle_message(text))

    @pyqtSlot()
    def stop(self):
        if self.jarvis is not None:
            self.jarvis.shutdown()


def build_ui(window):
    """Создаёт все виджеты и компоновку для MainWindow.

    Никакой логики и подключений сигналов тут нет — только интерфейс.
    Виджеты сохраняются как атрибуты window, чтобы их видели слоты.
    """
    window.setWindowTitle("JARVIS")

    window.log = QTextEdit()
    window.log.setReadOnly(True)

    window.line = QLineEdit()
    window.button = QPushButton("Отправить")
    window.line.setEnabled(False)
    window.button.setEnabled(False)

    layout = QVBoxLayout()
    layout.addWidget(window.log)
    layout.addWidget(window.line)
    layout.addWidget(window.button)

    central = QWidget()
    central.setLayout(layout)
    window.setCentralWidget(central)

    window.statusBar().showMessage("Загрузлюсь...")


class MainWindow(QMainWindow):
    send_requested = pyqtSignal(str)

    def __init__(self):
        super().__init__()

        # 1. Создаём интерфейс — отдельная функция, без логики.
        build_ui(self)

        # 2. Рабочий поток и ядро.
        self.thread = QThread()
        self.worker = JarvisWorker()
        self.worker.moveToThread(self.thread)

        # 3. Подключения сигналов.
        self.thread.started.connect(self.worker.start)
        self.worker.ready.connect(self.on_ready)
        self.worker.reply_ready.connect(self.on_reply)
        self.worker.event_received.connect(self.on_event)
        self.send_requested.connect(self.worker.send)

        self.button.clicked.connect(self.submit)
        self.line.returnPressed.connect(self.submit)

        self.thread.start()

    def on_ready(self):
        self.line.setEnabled(True)
        self.button.setEnabled(True)

    def submit(self):
        text = self.line.text().strip()

        if not text:
            return

        self.line.clear()
        self.line.setEnabled(False)      # один запрос за раз
        self.button.setEnabled(False)
        self.log.append(f"Ты: {text}")
        self.send_requested.emit(text)

    def on_reply(self, reply):
        self.line.setEnabled(True)
        self.button.setEnabled(True)

        if reply.kind != "empty":
            self.log.append(f"JARVIS: {reply.text}")

    def on_event(self, event):
        if event.channel == "status":
            self.statusBar().showMessage(STATUS_TEXT.get(event.text, event.text))
        elif event.channel == "note":
            self.log.append(f"({event.text})")

    def closeEvent(self, event):
        # shutdown() дожидается текущего запроса, поэтому вызываем его
        # в рабочем потоке и ждём (окно на это время замирает).
        QMetaObject.invokeMethod(
            self.worker, "stop", Qt.ConnectionType.BlockingQueuedConnection
        )
        self.thread.quit()
        self.thread.wait()
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
