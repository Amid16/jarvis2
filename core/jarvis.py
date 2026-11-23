"""
Ядро JARVIS.

Интерфейс (консоль, окно PyQt6, Telegram...) не содержит собственной
логики ИИ. Он делает три вещи:
  1. передаёт ядру текст: jarvis.handle_message(text)
  2. показывает ответ (Reply)
  3. при желании слушает события (core.events), чтобы показывать
     статус, вызовы инструментов, работу памяти.

Все долгие методы (handle_message, speak, stop_listening, shutdown)
БЛОКИРУЮТ вызвавший их поток. Окну нужно вызывать их из рабочего потока
(например, QThread), иначе оно «зависнет».
"""

import threading
import urllib.error
from dataclasses import dataclass, field
from datetime import datetime

from ai.ollama import OllamaProvider
from ai.prompts.loader import load_prompt
from config import (
    MAX_HISTORY_CHARS,
    MEMORY_ANALYZE_EVERY,
    MEMORY_DIALOG_WINDOW,
    USER_NAME,
)
from core.context import Conversation
from core.events import bus, emit
from core.user import UserProfile
from memory.manager import MemoryManager


MEMORY_NOTES = {
    "NEW": "Новая информация сохранена в память.",
    "UPDATE": "Похоже, информация изменилась. Я обновил старую запись.",
    "DUPLICATE": "Я уже это знаю.",
}


@dataclass
class Reply:
    """Результат handle_message()."""

    # Основной текст для показа пользователю.
    text: str

    # chat         — обычный ответ модели (его можно озвучить)
    # command      — результат команды памяти (запомни:, память, ...)
    # confirmation — JARVIS ждёт «да» или «нет»
    # error        — не получилось (Ollama недоступна и т.п.)
    # busy         — JARVIS ещё занят предыдущим запросом
    # empty        — пришла пустая строка, делать нечего
    kind: str = "chat"

    # Служебные пометки, например «Новая информация сохранена в память.»
    notes: list = field(default_factory=list)


@dataclass
class MemoryItem:
    id: int
    content: str
    created_at: str


class Jarvis:
    def __init__(
        self,
        provider=None,
        memory=None,
        user_name: str = None,
        background_memory: bool = True
    ):
        """
        provider          — объект с методом chat(messages) -> str.
                            По умолчанию OllamaProvider.
        memory            — по умолчанию MemoryManager.
        background_memory — True: анализ диалога для памяти идёт в фоне,
                            ответ возвращается сразу (хорошо для окна).
                            False: анализ запускает сам интерфейс вызовом
                            run_pending_analysis() (так делает консоль,
                            чтобы сохранить прежний порядок вывода).
        """
        self.provider = provider or OllamaProvider()
        self.memory = memory or MemoryManager()
        self.user = UserProfile(user_name or USER_NAME)
        self.background_memory = background_memory

        # Одновременно ядро обрабатывает только один запрос.
        self._lock = threading.RLock()
        self._state_lock = threading.Lock()
        self._working = 0
        self._closed = False

        self._analysis_due = False
        self._analysis_running = False
        self._messages_since_analysis = 0
        self._dialog_log = []
        self._pending_forget = None

        self._tts = None
        self._stt = None
        self._voice_init_lock = threading.Lock()
        self._speak_lock = threading.Lock()

        self._new_conversation()

    # ------------------------------------------------------------------
    # Состояние
    # ------------------------------------------------------------------

    @property
    def busy(self) -> bool:
        """True, пока ядро обрабатывает запрос или сохраняет память."""
        return self._working > 0

    @property
    def status(self) -> str:
        """idle, thinking, agent, memory, listening, transcribing, speaking"""
        return bus.status

    def _begin_work(self):
        with self._state_lock:
            self._working += 1

    def _end_work(self):
        with self._state_lock:
            self._working -= 1
            idle = self._working == 0

        if idle:
            emit("status", "idle")

    def _voice_done(self):
        if not self.busy:
            emit("status", "idle")

    def _new_conversation(self):
        self.conversation = Conversation(
            system_prompt=load_prompt("chat"),
            user_context=self.user.get_context()
        )

    # ------------------------------------------------------------------
    # Главный метод
    # ------------------------------------------------------------------

    def handle_message(self, text: str) -> Reply:
        """
        Обрабатывает сообщение пользователя: команды памяти, автоматическое
        запоминание, ответ модели. Никогда не бросает исключения — при
        сбое возвращает Reply(kind="error").
        """
        text = (text or "").strip()

        if not text:
            return Reply("", kind="empty")

        if self._closed:
            return Reply("JARVIS уже завершил работу.", kind="error")

        if not self._acquire():
            return Reply(
                "JARVIS ещё занят предыдущим запросом. Подожди немного.",
                kind="busy"
            )

        self._begin_work()

        try:
            return self._handle(text)
        except Exception as error:
            emit("error", f"Необработанная ошибка: {error}", level="error")
            return Reply(f"Что-то пошло не так: {error}", kind="error")
        finally:
            self._lock.release()
            self._end_work()

            if self._analysis_due and self.background_memory:
                self._start_background_analysis()

    def _acquire(self) -> bool:
        if self._lock.acquire(blocking=False):
            return True

        if self._analysis_running:
            # Идёт сохранение в память — оно скоро закончится, ждём.
            self._lock.acquire()
            return True

        return False

    def _handle(self, text: str) -> Reply:
        lower = text.lower()

        if lower.startswith("запомни:"):
            return self._cmd_remember(text[8:].strip())

        if lower.startswith("найди:"):
            return self._cmd_search(text[6:].strip())

        if self._pending_forget is not None:
            return self._answer_forget(lower.strip())

        if lower.startswith("забудь:"):
            return self._cmd_forget(text[7:].strip())

        if lower == "память":
            return self._cmd_show_memory()

        if lower.startswith("удали память"):
            return self._cmd_delete_memory(text[len("удали память"):].strip())

        return self._chat(text)

    # ------------------------------------------------------------------
    # Обычный разговор
    # ------------------------------------------------------------------

    def _chat(self, text: str) -> Reply:
        notes = []

        memory_result = self._auto_memory(text)
        note = MEMORY_NOTES.get(memory_result)

        if note:
            notes.append(note)
            emit("note", note)

        memory_context = self._search_memory(text)

        self.conversation.add_user_message(
            self._build_user_message(text, memory_context)
        )

        emit("status", "thinking")

        try:
            answer = self.provider.chat(
                self.conversation.get_messages_trimmed(MAX_HISTORY_CHARS)
            )
        except Exception as error:
            # Не оставляем в истории вопрос без ответа.
            self.conversation.messages.pop()

            emit("error", f"Не удалось получить ответ: {error}", level="error")

            return Reply(
                self._explain_error(error),
                kind="error",
                notes=notes
            )

        self.conversation.add_assistant_message(answer)

        self._dialog_log.append(("User", text))
        self._dialog_log.append(("Assistant", answer[:300]))
        self._messages_since_analysis += 1

        if self._messages_since_analysis >= MEMORY_ANALYZE_EVERY:
            self._analysis_due = True

        return Reply(answer, kind="chat", notes=notes)

    def _build_user_message(self, text: str, memory_context) -> str:
        current_time = datetime.now().strftime("%d.%m.%Y, %H:%M")
        time_line = f"Текущие дата и время: {current_time}.\n\n"

        if not memory_context:
            return f"{time_line}Вопрос пользователя:\n{text}"

        memory_text = "\n".join(f"- {item[1]}" for item in memory_context)

        return (
            f"{time_line}"
            f"Записи из долговременной памяти пользователя. "
            f"Они могут быть не связаны с вопросом. "
            f"Используй их только если они действительно "
            f"относятся к вопросу, иначе игнорируй их "
            f"и не упоминай:\n"
            f"{memory_text}\n\n"
            f"Вопрос пользователя:\n"
            f"{text}"
        )

    def _auto_memory(self, text: str):
        try:
            return self.memory.process_message(text)
        except Exception as error:
            emit(
                "memory",
                f"Не удалось обработать память: {error}",
                level="warning"
            )
            return None

    def _search_memory(self, text: str):
        try:
            return self.memory.search(text, limit=3)
        except Exception as error:
            emit(
                "memory",
                f"Не удалось найти в памяти: {error}",
                level="warning"
            )
            return []

    def _explain_error(self, error: Exception) -> str:
        if isinstance(error, urllib.error.HTTPError):
            return (
                f"Ollama вернула ошибку {error.code}. Подробности "
                f"смотри в журнале Ollama."
            )

        if isinstance(error, (urllib.error.URLError, ConnectionError, TimeoutError)):
            return (
                "Не удалось связаться с Ollama. Проверь, что она запущена "
                "(или она слишком долго не отвечает)."
            )

        return f"Не удалось получить ответ: {error}"

    # ------------------------------------------------------------------
    # Команды памяти (то же, что умела консоль)
    # ------------------------------------------------------------------

    def _cmd_remember(self, memory_text: str) -> Reply:
        if not memory_text:
            return Reply(
                "После 'запомни:' нужно указать информацию.",
                kind="command"
            )

        self.memory.remember(memory_text)

        return Reply("Запомнил.", kind="command")

    def _cmd_search(self, search_text: str) -> Reply:
        if not search_text:
            return Reply(
                "После 'найди:' нужно указать текст для поиска.",
                kind="command"
            )

        memories = self.memory.search(search_text)

        if not memories:
            return Reply("Ничего не нашёл в памяти.", kind="command")

        lines = "\n".join(f"- {item[1]}" for item in memories)

        return Reply(f"Нашёл в памяти:\n{lines}", kind="command")

    def _cmd_show_memory(self) -> Reply:
        memories = self.memory.get_all()

        if not memories:
            return Reply("Долговременная память пуста.", kind="command")

        lines = "\n".join(
            f"[{item[0]}] {item[1]} ({item[2]})"
            for item in memories
        )

        return Reply(
            f"Моя долговременная память:\n\n{lines}",
            kind="command"
        )

    def _cmd_delete_memory(self, argument: str) -> Reply:
        try:
            memory_id = int(argument)
        except ValueError:
            return Reply(
                "Укажи ID памяти. Например: 'удали память 5'.",
                kind="command"
            )

        if self.memory.delete(memory_id):
            return Reply(
                f"Воспоминание [{memory_id}] удалено.",
                kind="command"
            )

        return Reply(
            f"Воспоминание [{memory_id}] не найдено.",
            kind="command"
        )

    def _cmd_forget(self, query: str) -> Reply:
        if not query:
            return Reply(
                "После 'забудь:' нужно указать, что именно забыть.",
                kind="command"
            )

        candidates = self.memory.find_forget_candidates(query, limit=5)

        if not candidates:
            return Reply(
                "Я не нашёл подходящих воспоминаний.",
                kind="command"
            )

        selected_ids = self.memory.select_forget_candidates(
            query,
            candidates
        )

        selected = [
            item for item in candidates
            if item[0] in selected_ids
        ]

        if not selected:
            return Reply(
                "Я не нашёл воспоминаний, которые точно соответствуют "
                "запросу.",
                kind="command"
            )

        self._pending_forget = selected

        lines = "\n".join(f"[{item[0]}] {item[1]}" for item in selected)

        return Reply(
            f"Я нашёл:\n\n{lines}\n\nУдалить эти воспоминания? (да/нет)",
            kind="confirmation"
        )

    def _answer_forget(self, answer: str) -> Reply:
        if answer in ("да", "yes", "д", "y"):
            deleted = 0

            for item in self._pending_forget:
                if self.memory.delete(item[0]):
                    deleted += 1

            self._pending_forget = None

            return Reply(f"Удалил воспоминаний: {deleted}.", kind="command")

        if answer in ("нет", "no", "н", "n"):
            self._pending_forget = None

            return Reply("Ничего не удаляю.", kind="command")

        return Reply("Ответь «да» или «нет».", kind="confirmation")

    # ------------------------------------------------------------------
    # Память для интерфейса (кнопки вместо команд)
    # ------------------------------------------------------------------

    def list_memories(self) -> list:
        with self._lock:
            return [
                MemoryItem(item[0], item[1], item[2])
                for item in self.memory.get_all()
            ]

    def remember(self, text: str) -> str:
        """Сохраняет факт напрямую. Возвращает NEW, UPDATE или DUPLICATE."""
        with self._lock:
            return self.memory.remember(text)

    def delete_memory(self, memory_id: int) -> bool:
        with self._lock:
            return bool(self.memory.delete(memory_id))

    # ------------------------------------------------------------------
    # Анализ диалога для долговременной памяти
    # ------------------------------------------------------------------

    @property
    def analysis_pending(self) -> bool:
        return self._analysis_due

    def run_pending_analysis(self):
        """
        Сохраняет в память факты из последних реплик, если подошло время.
        В режиме background_memory=True вызывается ядром само.
        """
        with self._lock:
            if self._closed or not self._analysis_due:
                return

            self._begin_work()
            self._analysis_running = True

            try:
                self._analyze_dialog()
            finally:
                self._analysis_running = False
                self._analysis_due = False
                self._messages_since_analysis = 0
                self._end_work()

    def _start_background_analysis(self):
        threading.Thread(
            target=self.run_pending_analysis,
            name="jarvis-memory",
            daemon=True
        ).start()

    def _analyze_dialog(self):
        recent = self._dialog_log[-MEMORY_DIALOG_WINDOW:]

        dialog_text = "\n".join(
            f"{role}: {text}"
            for role, text in recent
        )

        emit("status", "memory")

        try:
            self.memory.process_dialog(dialog_text)
        except Exception as error:
            emit(
                "memory",
                f"Анализ диалога не удался: {error}",
                level="warning"
            )

    # ------------------------------------------------------------------
    # Новый чат и завершение
    # ------------------------------------------------------------------

    def new_chat(self):
        """Начинает разговор заново. Долговременная память остаётся."""
        with self._lock:
            if self._messages_since_analysis > 0:
                self._begin_work()

                try:
                    self._analyze_dialog()
                finally:
                    self._end_work()

            self._pending_forget = None
            self._dialog_log = []
            self._messages_since_analysis = 0
            self._analysis_due = False
            self._new_conversation()

    def shutdown(self):
        """
        Корректно завершает работу: дожидается текущего запроса,
        сохраняет в память последние реплики, закрывает базу.
        """
        with self._lock:
            if self._closed:
                return

            if self._messages_since_analysis > 0:
                emit("memory", "Анализирую диалог перед выходом...")
                self._begin_work()

                try:
                    self._analyze_dialog()
                finally:
                    self._end_work()

            self._analysis_due = False
            self._messages_since_analysis = 0

            self.stop_speaking()
            self.cancel_listening()

            self.memory.close()
            self._closed = True

    # ------------------------------------------------------------------
    # Голос. Модели грузятся при первом использовании.
    # ------------------------------------------------------------------

    def preload_voice(self):
        """Заранее загружает озвучку и распознавание (это долго)."""
        self._get_tts()
        self._get_stt()

    def _get_tts(self):
        with self._voice_init_lock:
            if self._tts is None:
                from voice.tts import TextToSpeech
                self._tts = TextToSpeech()

            return self._tts

    def _get_stt(self):
        with self._voice_init_lock:
            if self._stt is None:
                from voice.stt import SpeechToText
                self._stt = SpeechToText()

            return self._stt

    def speak(self, text: str):
        """Озвучивает текст. Блокирует поток до конца озвучки."""
        if not (text or "").strip():
            return

        tts = self._get_tts()

        with self._speak_lock:
            emit("status", "speaking")

            try:
                tts.speak(text)
            finally:
                self._voice_done()

    def stop_speaking(self):
        """Прерывает озвучку, которая сейчас играет."""
        if self._tts is not None:
            self._tts.stop()

    def start_listening(self):
        """Начинает запись с микрофона (не блокирует)."""
        self._get_stt().start()
        emit("status", "listening")

    def stop_listening(self) -> str:
        """Заканчивает запись и возвращает распознанный текст."""
        if self._stt is None:
            return ""

        emit("status", "transcribing")

        try:
            return self._stt.stop()
        finally:
            self._voice_done()

    def cancel_listening(self):
        """Отменяет запись, ничего не распознавая."""
        if self._stt is not None:
            self._stt.cancel()
            self._voice_done()
