# Как подключить окно (PyQt6) к JARVIS

Ядро JARVIS не знает, какой у него интерфейс. Консоль (`main.py`) и твоё
окно используют один и тот же класс `Jarvis` из `core/jarvis.py`.

```
Окно PyQt6 ──► Jarvis (core/jarvis.py) ──► ИИ, память, агент, голос
     ▲                    │
     └──── события ◄──────┘   (core/events.py)
```

В самом ядре нет ни одной строчки Qt и нет `print` — всё, что раньше шло
в консоль, теперь приходит окну событиями.

## Три правила, без которых окно зависнет или упадёт

1. **Методы ядра блокируют поток.** `handle_message()` может работать
   минуты (агент!). Вызывай их только из рабочего потока (`QThread`),
   а не из потока окна.
2. **События приходят из рабочего потока.** Нельзя трогать виджеты
   прямо из подписчика. Передавай событие в окно через сигнал Qt
   (`pyqtSignal`), как в примере ниже.
3. **Один запрос за раз.** Если вызвать `handle_message()` во время
   работы, вернётся `Reply(kind="busy")`. Блокируй кнопку «Отправить»,
   пока не пришёл ответ.

## Что есть в ядре

| Что | Зачем |
|---|---|
| `Jarvis(background_memory=True)` | Создать ядро. `True` — память сохраняется в фоне, ответ приходит сразу |
| `handle_message(text) -> Reply` | Главный метод. Команды памяти, ответ, агент. Не бросает исключений |
| `Reply.text`, `.kind`, `.notes` | `kind`: `chat`, `command`, `confirmation`, `error`, `busy`, `empty` |
| `speak(text)` / `stop_speaking()` | Озвучка. `speak` блокирует до конца, `stop_speaking` можно из любого потока |
| `start_listening()` / `stop_listening() -> str` | Микрофон: начать запись и закончить (вернёт текст) |
| `cancel_listening()` | Отменить запись |
| `list_memories()`, `delete_memory(id)`, `remember(text)` | Для панели «Память» вместо команд |
| `new_chat()` | Начать разговор заново (память остаётся) |
| `shutdown()` | Завершение: дожидается запроса, сохраняет память, закрывает базу |
| `busy`, `status` | Занят ли JARVIS и что делает |
| `preload_voice()` | Заранее загрузить голосовые модели (долго; по умолчанию они грузятся при первом использовании) |

`kind == "confirmation"` значит, что JARVIS ждёт «да» или «нет» (команда
`забудь:`). Просто отправь следующее сообщение пользователя как обычно.

## События

Подписка: `bus.subscribe(функция)`. Функция получает `Event` с полями
`channel`, `text`, `level` (`debug`, `info`, `warning`, `error`) и `data`.

| Канал | Что это |
|---|---|
| `status` | Состояние в `text`: `idle`, `thinking`, `agent`, `memory`, `listening`, `transcribing`, `speaking`. В `data["previous"]` — прежнее |
| `note` | Короткая пометка, например «Новая информация сохранена в память.» |
| `agent` | Задача для агента (`data["task"]`) и его отчёт (`data["report"]`) |
| `tools` | Вызов инструмента (`data["name"]`, `data["arguments"]`) |
| `memory`, `ollama`, `stt`, `tts`, `error` | Технические сообщения, удобны для панели журнала |

`bus.console_enabled = False` выключает дублирование в консоль.

## Минимальный пример

Не запускал: в той среде, где я это писал, нет PyQt6 (проверен только
синтаксис). Само ядро и работу из рабочего потока я проверил отдельно.
Считай это заготовкой.

```python
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


class MainWindow(QMainWindow):
    send_requested = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("JARVIS")

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.line = QLineEdit()
        self.button = QPushButton("Отправить")
        self.line.setEnabled(False)
        self.button.setEnabled(False)

        layout = QVBoxLayout()
        layout.addWidget(self.log)
        layout.addWidget(self.line)
        layout.addWidget(self.button)
        central = QWidget()
        central.setLayout(layout)
        self.setCentralWidget(central)

        self.thread = QThread()
        self.worker = JarvisWorker()
        self.worker.moveToThread(self.thread)

        self.thread.started.connect(self.worker.start)
        self.worker.ready.connect(self.on_ready)
        self.worker.reply_ready.connect(self.on_reply)
        self.worker.event_received.connect(self.on_event)
        self.send_requested.connect(self.worker.send)

        self.button.clicked.connect(self.submit)
        self.line.returnPressed.connect(self.submit)

        self.statusBar().showMessage("Загружаюсь...")
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
```

## Голос в окне

- Озвучка: после `reply_ready` вызови `jarvis.speak(reply.text)` (только
  для `reply.kind == "chat"`) тоже в рабочем потоке. Сначала покажи текст,
  потом говори.
- Кнопка «Стоп»: `jarvis.stop_speaking()` и `jarvis.cancel_listening()`
  безопасно вызывать **прямо из потока окна**, они ничего не ждут. Через
  очередь рабочего потока они бы не сработали: тот занят озвучкой.
- Голосу лучше отдельный рабочий поток. Иначе запись с микрофона не
  начнётся, пока агент занят запросом.

## Что сейчас нельзя

- **Ответ приходит целиком**, а не по буквам (потоковой выдачи нет).
- **Прервать запрос к модели нельзя**: максимум, что защищает окно от
  вечного ожидания, это `OLLAMA_TIMEOUT` в `config.py`.
- Ядро работает с **одним пользователем и одним разговором**.

## Если что-то пошло не так

- Окно «молчит»: смотри события `error` и `warning`, они приходят
  с понятным текстом.
- Пустая память после запуска окна: проверь `data\database\jarvis.db`
  в папке проекта. Путь теперь считается от папки проекта, а не от
  папки запуска.
