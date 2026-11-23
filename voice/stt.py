import numpy as np
import sounddevice as sd
from faster_whisper import WhisperModel

from core.events import emit


SAMPLE_RATE = 16000
MODEL_SIZE = "small"


class SpeechToText:
    """
    Запись с микрофона и распознавание речи.

    Не зависит от интерфейса: start() начинает запись и сразу
    возвращает управление, stop() заканчивает запись и возвращает
    распознанный текст. Консоль ждёт между ними нажатия Enter,
    окно — нажатия кнопки.
    """

    def __init__(self):
        emit("stt", "Загружаю модель распознавания речи...")

        # device="cpu" — работает без настройки CUDA.
        # Если захочешь ускорить через видеокарту, можно
        # поменять на device="cuda", compute_type="float16",
        # но для этого понадобятся дополнительные библиотеки
        # NVIDIA (cuDNN, cuBLAS). Пока не обязательно.
        self.model = WhisperModel(
            MODEL_SIZE,
            device="cpu",
            compute_type="int8"
        )

        emit("stt", "Модель загружена.")

        self._frames = []
        self._stream = None

    @property
    def recording(self) -> bool:
        return self._stream is not None

    def start(self):
        """Начинает запись с микрофона. Не блокирует."""
        if self._stream is not None:
            return

        self._frames = []

        self._stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="float32",
            callback=self._on_audio
        )

        self._stream.start()

    def _on_audio(self, indata, frames, time, status):
        self._frames.append(indata.copy())

    def _close_stream(self):
        stream, self._stream = self._stream, None

        if stream is not None:
            stream.stop()
            stream.close()

    def cancel(self):
        """Прекращает запись и выбрасывает записанное."""
        self._close_stream()
        self._frames = []

    def stop(self) -> str:
        """Заканчивает запись и возвращает распознанный текст."""
        if self._stream is None:
            return ""

        self._close_stream()

        frames, self._frames = self._frames, []

        if not frames:
            return ""

        audio = np.concatenate(frames, axis=0).flatten()

        emit("stt", "Распознаю...")

        segments, _ = self.model.transcribe(
            audio,
            language="ru"
        )

        text = " ".join(
            segment.text.strip()
            for segment in segments
        )

        return text.strip()
