import os
import re
import threading
import warnings

import torch
import winsound

from core.events import emit
from voice.text_prep import prepare_for_speech


MODEL_URL = "https://models.silero.ai/models/tts/ru/v5_ru.pt"

MODEL_LOCAL_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    "models",
    "silero_v5_ru.pt"
)

SAMPLE_RATE = 48000
SPEAKER = "xenia"

# Держим с запасом ниже внутреннего лимита Silero в 1000 символов.
MAX_CHARS_PER_CHUNK = 900


def _split_into_chunks(text: str) -> list[str]:
    sentences = re.split(r"(?<=[.!?])\s+", text)

    chunks = []
    current = ""

    for sentence in sentences:
        if len(current) + len(sentence) + 1 > MAX_CHARS_PER_CHUNK:
            if current:
                chunks.append(current.strip())
            current = sentence
        else:
            current = f"{current} {sentence}".strip()

    if current:
        chunks.append(current.strip())

    return chunks


class TextToSpeech:
    def __init__(self):
        self.device = torch.device("cpu")
        torch.set_num_threads(4)

        self._stop_requested = threading.Event()

        os.makedirs(
            os.path.dirname(MODEL_LOCAL_PATH),
            exist_ok=True
        )

        if not os.path.isfile(MODEL_LOCAL_PATH):
            emit(
                "tts",
                "Скачиваю голосовую модель Silero "
                "(один раз, дальше будет работать без интернета)..."
            )
            torch.hub.download_url_to_file(
                MODEL_URL,
                MODEL_LOCAL_PATH
            )

        # У этой версии PyTorch есть безобидное предупреждение про
        # устаревший TypedStorage внутри самого загрузчика Silero.
        # Прячем только его, а не все предупреждения вообще.
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message="TypedStorage is deprecated"
            )

            self.model = torch.package.PackageImporter(
                MODEL_LOCAL_PATH
            ).load_pickle("tts_models", "model")

        self.model.to(self.device)

    def speak(self, text: str):
        if not text.strip():
            return

        self._stop_requested.clear()

        prepared_text = prepare_for_speech(text)

        for chunk in _split_into_chunks(prepared_text):
            if self._stop_requested.is_set():
                break

            if not chunk.strip():
                continue

            wav_path = self.model.save_wav(
                text=chunk,
                speaker=SPEAKER,
                sample_rate=SAMPLE_RATE
            )

            winsound.PlaySound(wav_path, winsound.SND_FILENAME)

            os.remove(wav_path)

    def stop(self):
        """Прерывает озвучку, которая сейчас играет (можно из другого потока)."""
        self._stop_requested.set()
        winsound.PlaySound(None, winsound.SND_PURGE)
