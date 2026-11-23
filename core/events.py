"""
Шина событий JARVIS.

Модули ядра (память, агент, голос) не знают, кто именно их слушает —
консоль или окно. Поэтому вместо print() они вызывают emit(...), а
интерфейс подписывается на события и показывает их так, как ему удобно.

Каналы событий (channel):
  agent, tools, ollama, memory, stt, tts, error — технические сообщения
  status — состояние JARVIS (text = idle, thinking, agent, memory,
           listening, transcribing, speaking)
  note   — короткая пометка для пользователя ("Новая информация
           сохранена в память.")

Уровни (level): debug, info, warning, error.
"""

import threading
from dataclasses import dataclass, field


# Подписи технических каналов в консоли: [Agent], [Tools] и так далее.
CONSOLE_LABELS = {
    "agent": "Agent",
    "tools": "Tools",
    "ollama": "Ollama",
    "memory": "Memory",
    "stt": "STT",
    "tts": "TTS",
    "error": "Error",
}


@dataclass
class Event:
    channel: str
    text: str
    level: str = "info"
    data: dict = field(default_factory=dict)


class EventBus:
    def __init__(self):
        self._subscribers = []
        self._lock = threading.Lock()

        # Печатать технические события в консоль, как раньше.
        # Окну это обычно не нужно: bus.console_enabled = False
        self.console_enabled = True

        # Последнее состояние JARVIS (см. канал status).
        self.status = "idle"

    def subscribe(self, callback):
        """
        Подписывает функцию callback(event) на все события.
        Возвращает функцию для отписки.

        ВАЖНО: события приходят из рабочих потоков. Окну на PyQt6 нужно
        передавать их в главный поток через сигнал (см. docs).
        """
        with self._lock:
            self._subscribers.append(callback)

        def unsubscribe():
            with self._lock:
                if callback in self._subscribers:
                    self._subscribers.remove(callback)

        return unsubscribe

    def emit(self, channel: str, text: str, level: str = "info", **data):
        if channel == "status":
            data["previous"] = self.status
            self.status = text

        event = Event(channel, text, level, data)

        label = CONSOLE_LABELS.get(channel)

        if self.console_enabled and label:
            print(f"[{label}] {text}")

        with self._lock:
            subscribers = list(self._subscribers)

        for callback in subscribers:
            try:
                callback(event)
            except Exception as error:
                # Ошибка в интерфейсе не должна ломать работу ядра.
                print(f"[Events] Ошибка в обработчике событий: {error}")

        return event


bus = EventBus()


def emit(channel: str, text: str, level: str = "info", **data):
    return bus.emit(channel, text, level, **data)
