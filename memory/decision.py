import json
import re
import time
import requests

from core.events import emit

# Имя файла с расширением (computer.png, report.docx, script.py и т.п.).
# Такие "факты" — не про пользователя, а результат работы инструментов.
FILE_NAME_PATTERN = re.compile(
    r"\b[\w\-]+\.(png|jpe?g|gif|bmp|tiff?|webp|pptx?|docx?|xlsx?|"
    r"csv|txt|pdf|py)\b",
    re.IGNORECASE
)

RETRY_DELAY_SECONDS = 4

# Сколько секунд ждать ответа Ollama при решениях по памяти.
MEMORY_REQUEST_TIMEOUT = 300

# Температура 0 (жадная генерация) у Qwen может уйти в бесконечный повтор
# одних и тех же токенов — тогда Ollama обрывает запрос ошибкой 500
# "token repeat limit reached". Поэтому чуть выше нуля, плюс потолок
# длины ответа: нужные нам JSON-ответы короткие.
MEMORY_TEMPERATURE = 0.2
MEMORY_MAX_TOKENS = 300
MEMORY_OPTIONS = {
    "temperature": MEMORY_TEMPERATURE,
    "num_predict": MEMORY_MAX_TOKENS
}

# При повторе температура повышается: тот же запрос при том же значении
# дал бы тот же самый сбой.
RETRY_TEMPERATURE = 0.4


def _warmer(kwargs: dict) -> dict:
    """Копия запроса с повышенной температурой (для повтора)."""
    payload = dict(kwargs.get("json") or {})
    options = dict(payload.get("options") or {})

    options["temperature"] = max(
        options.get("temperature", 0),
        RETRY_TEMPERATURE
    )

    payload["options"] = options

    return {**kwargs, "json": payload}


def _post_with_retry(url, **kwargs):
    """
    Обычный requests.post, но при ошибке сервера Ollama (5xx) показывает
    её настоящий текст (по умолчанию он скрыт) и один раз повторяет запрос
    с чуть большей температурой.
    """
    kwargs.setdefault("timeout", MEMORY_REQUEST_TIMEOUT)

    response = requests.post(url, **kwargs)

    if response.status_code >= 500:
        emit(
            "memory",
            f"Ollama вернула ошибку {response.status_code}: "
            f"{response.text[:300]}",
            level="warning"
        )
        emit(
            "memory",
            f"Повторяю запрос через {RETRY_DELAY_SECONDS} с "
            f"(температура повыше)..."
        )

        time.sleep(RETRY_DELAY_SECONDS)

        response = requests.post(url, **_warmer(kwargs))

        if response.status_code >= 500:
            emit(
                "memory",
                f"Повтор тоже не удался: {response.status_code}: "
                f"{response.text[:300]}",
                level="warning"
            )

    return response


class MemoryDecision:
    def __init__(self, model: str = "qwen3:4b"):
        self.model = model
        self.url = "http://localhost:11434/api/chat"

    def should_remember(self, user_message: str):
        prompt = f"""
You are a memory filter.

Decide whether the user's message contains useful long-term personal information.

Remember:
- name
- preferences
- interests
- skills being learned
- long-term projects
- long-term goals
- stable personal facts

Do not remember:
- questions
- greetings
- temporary actions
- casual conversation
- information useful only for the current chat

Return ONLY valid JSON:

{{"should_remember":true,"memory":"short fact"}}

or:

{{"should_remember":false,"memory":""}}

User message:
{user_message}
"""

        response = _post_with_retry(
            self.url,
            json={
                "model": self.model,
                "messages": [
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                "stream": False,
                "options": MEMORY_OPTIONS
            }
        )

        response.raise_for_status()

        data = response.json()

        answer = data["message"]["content"].strip()

        return self._parse_response(answer)
    
    def _parse_response(self, answer: str):
        try:
            result = json.loads(answer)

            return {
                "should_remember": bool(
                    result.get("should_remember", False)
                ),
                "memory": result.get("memory", "").strip()
            }

        except json.JSONDecodeError:
            return {
                "should_remember": False,
                "memory": ""
            }

    def select_forget_candidates(self, query: str, memories):
        if not memories:
            return []

        memories_text = "\n".join(
            f"[{memory[0]}] {memory[1]}"
            for memory in memories
        )

        prompt = f"""
Select memories that match the user's request to forget.

Use meaning, not exact words.

User request:
"{query}"

Candidates:
{memories_text}

Return ONLY valid JSON:

{{"memory_ids":[1,2]}}

If none match:

{{"memory_ids":[]}}
"""

        response = _post_with_retry(
            self.url,
            json={
                "model": self.model,
                "messages": [
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                "stream": False,
                "think": False,
                "format": "json",
                "options": MEMORY_OPTIONS
            }
        )

        response.raise_for_status()

        data = response.json()

        answer = data["message"]["content"].strip()

        try:
            result = json.loads(answer)

            memory_ids = result.get("memory_ids", [])

            return [
                int(memory_id)
                for memory_id in memory_ids
            ]

        except (json.JSONDecodeError, ValueError, TypeError):
            return []

    def extract_facts(self, dialog: str):
        prompt = f"""
You extract long-term facts about the USER from a short dialog.

Rules:
- Use ONLY what the USER wrote. Never use facts from Assistant messages.
- Combine details spread across several user messages into ONE fact.
  Example (not real data): user says "I have a cat", then "Her name is Murka"
  -> "Пользователь имеет кошку по имени Мурка".
- Keep only stable facts: name, place of living, preferences, interests,
  skills, tools and equipment the user owns or uses, projects, goals.
- NEVER create a fact about the user asking, wondering, or being curious
  about something. A question stays a question, it is NOT a fact.
  Bad (do NOT do this):
    user: "Как заточить сверло?"
    wrong fact: "Пользователь имеет вопрос о заточке сверла"
    wrong fact: "Пользователь интересуется заточкой сверла"
  Correct: extract nothing from that message.
- NEVER create a fact about the user greeting, saying hello, or making
  small talk. A greeting is NOT a fact.
  Bad (do NOT do this):
    user: "привет"
    wrong fact: "Пользователь приветствует"
  Correct: extract nothing from that message.
- Files, images, documents and presentations that appear in the dialog
  (for example a list of files the assistant showed, or a presentation
  it created) are results of the assistant's work, NOT facts about the
  user. Never turn them into facts.
  Bad (do NOT do this):
    assistant: "В папке есть computer.png и game.png"
    wrong fact: "Пользователь имеет изображение computer.png"
  Correct: extract nothing from that.
- Ignore questions, greetings, jokes, temporary actions and general knowledge.
- Copy names, brands, model numbers and other identifiers EXACTLY as the
  user typed them, character by character. Never invent, guess, or
  approximate digits or letters in them.
  Example: if the user wrote "Makita DDF484", the fact must contain
  exactly "Makita DDF484", not a similar-looking number.
- Do not guess. If unsure, return an empty list.
- Each fact is ONE short sentence in Russian that starts with "Пользователь".
- Return at most 3 facts.

Return ONLY valid JSON:

{{"facts":["..."]}}

If there is nothing to remember:

{{"facts":[]}}

Dialog:
{dialog}
"""

        response = _post_with_retry(
            self.url,
            json={
                "model": self.model,
                "messages": [
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                "stream": False,
                "think": False,
                "format": "json",
                "options": MEMORY_OPTIONS
            }
        )

        response.raise_for_status()

        data = response.json()

        try:
            result = json.loads(data["message"]["content"])
            facts = result.get("facts", [])
        except (json.JSONDecodeError, KeyError, TypeError, AttributeError):
            return []

        if not isinstance(facts, list):
            return []

        clean_facts = []

        for fact in facts:
            if not isinstance(fact, str):
                continue

            fact = fact.strip()

            if not fact or len(fact) > 200:
                continue

            if not fact.startswith(("Пользователь", "Имя пользователя: ")):
                continue

            question_markers = (
                "вопрос", "спрашива", "интересу", "хочет узнать",
                "не знает", "не понимает",
                "приветству", "здоровается", "поздоровался",
                "говорит привет"
            )

            if any(marker in fact.lower() for marker in question_markers):
                continue

            file_markers = (
                "workspace", "папк", "файл", "презентаци",
                "картинк", "изображени"
            )

            if FILE_NAME_PATTERN.search(fact):
                continue

            if any(marker in fact.lower() for marker in file_markers):
                continue

            clean_facts.append(fact)

        return clean_facts[:3]

    def classify_memory(self, content: str, memories):
        memories_text = "\n".join(
            f"[{memory[0]}] {memory[1]}"
            for memory in memories
        )

        prompt = f"""
    You are a memory manager.

    Compare the new information with existing memories.

    New information:
    "{content}"

    Existing memories:
    {memories_text}

    Choose one:

    DUPLICATE:
    The new information means essentially the same thing as an existing memory.

    UPDATE:
    The new information changes or replaces an existing fact.

    NEW:
    The new information is an additional independent fact.

    Return ONLY valid JSON.

    For DUPLICATE:
    {{"type":"DUPLICATE","memory_id":1}}

    For UPDATE:
    {{"type":"UPDATE","memory_id":1}}

    For NEW:
    {{"type":"NEW","memory_id":null}}
    """

        response = _post_with_retry(
            self.url,
            json={
                "model": self.model,
                "messages": [
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                "stream": False,
                "think": False,
                "format": "json",
                "options": MEMORY_OPTIONS
            }
        )

        response.raise_for_status()

        data = response.json()

        try:
            result = json.loads(data["message"]["content"])
        except (json.JSONDecodeError, KeyError, TypeError):
            return {"type": "NEW", "memory_id": None}

        if not isinstance(result, dict) or "type" not in result:
            return {"type": "NEW", "memory_id": None}

        return result
