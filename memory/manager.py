from memory.database import Database
from memory.search import MemorySearch
from memory.decision import MemoryDecision
import re
from core.events import emit
from memory.deduplication import calculate_keyword_similarity, get_keywords


# Факты, у которых может быть только ОДНО актуальное значение.
# Если приходит новое значение, старая запись обновляется (UPDATE).
SINGLE_VALUE_FACTS = {
    "name": (
        "Имя пользователя: ",
    ),
    "residence": (
        "Пользователь живёт в ",
        "Пользователь переехал в ",
        "Пользователь переехала в ",
    ),
}


class MemoryManager:
    def __init__(self):
        self.database = Database()
        self.search_engine = MemorySearch(self.database)
        self.decision = MemoryDecision()

    def remember(self, content: str):
        emit("memory", f"Checking: {content}", level="debug")

        # Шаг 1. Факты с одним значением (имя, город):
        # обновляем старую запись без поиска и без AI.
        fact_type = self._get_fact_type(content)

        if fact_type:
            for memory_id, existing_content, _ in self.database.get_memories():
                if self._get_fact_type(existing_content) != fact_type:
                    continue

                if existing_content.strip().lower() == content.strip().lower():
                    return "DUPLICATE"

                if self.database.update_memory(memory_id, content):
                    return "UPDATE"

        # Шаг 2. Ищем похожие воспоминания.
        similar_memories = self.search(
            content,
            limit=5
        )

        for memory in similar_memories:
            emit(
                "memory",
                f"Candidate [{memory[0]}]: {memory[1]}",
                level="debug"
            )
            emit(
                "memory",
                f"Semantic similarity: {memory[3]:.4f}",
                level="debug"
            )

            keyword_similarity = calculate_keyword_similarity(
                content,
                memory[1]
            )

            emit(
                "memory",
                f"Keyword similarity: {keyword_similarity:.4f}",
                level="debug"
            )

        if not similar_memories:
            self.database.add_memory(content)
            return "NEW"

        # Шаг 3. Очевидные дубли.
        for memory in similar_memories:
            existing_content = memory[1]
            semantic_similarity = memory[3]

            keyword_similarity = calculate_keyword_similarity(
                content,
                existing_content
            )

            if keyword_similarity >= 0.75:
                return "DUPLICATE"

            if semantic_similarity >= 0.97:
                return "DUPLICATE"

        # Шаг 4. Если информация явно новая — сохраняем сразу.
        if self._is_obviously_new(content, similar_memories):
            self.database.add_memory(content)
            return "NEW"

        # Шаг 5. Остались неоднозначные случаи — спрашиваем AI.
        emit("memory", "Спорный случай, спрашиваю qwen3:4b...")

        decision = self.decision.classify_memory(
            content,
            similar_memories
        )

        decision_type = decision["type"]

        if decision_type == "DUPLICATE":
            return "DUPLICATE"

        if decision_type == "UPDATE":
            memory_id = decision.get("memory_id")

            if not isinstance(memory_id, int):
                self.database.add_memory(content)
                return "NEW"

            updated = self.database.update_memory(
                memory_id,
                content
            )

            if updated:
                return "UPDATE"

            self.database.add_memory(content)
            return "NEW"

        self.database.add_memory(content)
        return "NEW"

    def process_dialog(self, dialog_text: str):
        """Ищет факты в последних сообщениях диалога и сохраняет их."""
        try:
            facts = self.decision.extract_facts(dialog_text)
        except Exception as error:
            emit(
                "memory",
                f"Анализ диалога не удался: {error}",
                level="warning"
            )
            return []

        if not facts:
            emit("memory", "Анализ диалога: новых фактов нет")
            return []

        results = []

        for fact in facts:
            result = self.remember(fact)

            emit(
                "memory",
                f"Из диалога {result}: {fact}",
                result=result,
                fact=fact
            )

            results.append((fact, result))

        return results

    def _get_fact_type(self, content: str):
        for fact_type, prefixes in SINGLE_VALUE_FACTS.items():
            for prefix in prefixes:
                if content.startswith(prefix):
                    return fact_type

        return None

    def _is_obviously_new(self, content: str, memories):
        content_keywords = get_keywords(content)

        for memory in memories:
            existing_keywords = get_keywords(memory[1])

            common_keywords = content_keywords & existing_keywords

            if len(common_keywords) >= 2:
                return False

        return True

    def delete(self, memory_id: int):
        return self.database.delete_memory(memory_id)

    def process_message(self, user_message: str):
        if not self._looks_like_memory(user_message):
            return False

        memory = self._extract_memory(user_message)

        if not memory:
            return False

        result = self.remember(memory)

        emit(
            "memory",
            f"{result}: {memory}",
            result=result,
            memory=memory
        )

        return result

    def _extract_memory(self, user_message: str):
        text = user_message.strip()

        patterns = (
            ("меня зовут ", "Имя пользователя: "),
            ("я люблю ", "Пользователь любит "),
            ("мне нравится ", "Пользователю нравится "),
            ("я изучаю ", "Пользователь изучает "),
            ("я учусь ", "Пользователь учится "),
            ("я занимаюсь ", "Пользователь занимается "),
            ("я разрабатываю ", "Пользователь разрабатывает "),
            ("я делаю ", "Пользователь делает "),
            ("я играю ", "Пользователь играет "),
            ("моя цель ", "Цель пользователя: "),
            ("я хочу научиться ", "Пользователь хочет научиться "),
            ("я построил ", "Пользователь построил "),
            ("я построила ", "Пользователь построила "),
            ("я создал ", "Пользователь создал "),
            ("я создала ", "Пользователь создала "),
            ("я сделал ", "Пользователь сделал "),
            ("я сделала ", "Пользователь сделала "),
            ("я живу в ", "Пользователь живёт в "),
            ("я переехал в ", "Пользователь переехал в "),
            ("я переехала в ", "Пользователь переехала в "),
        )

        lower_text = text.lower()

        for prefix, replacement in patterns:
            if lower_text.startswith(prefix):
                value = text[len(prefix):].strip()

                if value:
                    return replacement + value

        return None

    def _looks_like_memory(self, text: str):
        text = text.lower().strip()

        memory_patterns = (
            r"\bя люблю\b",
            r"\bмне нравится\b",
            r"\bя изучаю\b",
            r"\bя учусь\b",
            r"\bя занимаюсь\b",
            r"\bя разрабатываю\b",
            r"\bя делаю\b",
            r"\bя играю\b",
            r"\bменя зовут\b",
            r"\bмоего .* зовут\b",
            r"\bмоя цель\b",
            r"\bя хочу научиться\b",
            r"\bя построил\b",
            r"\bя построила\b",
            r"\bя создал\b",
            r"\bя создала\b",
            r"\bя сделал\b",
            r"\bя сделала\b",
            r"\bя живу в\b",
            r"\bя переехал в\b",
            r"\bя переехала в\b",
        )

        for pattern in memory_patterns:
            if re.search(pattern, text):
                return True

        return False

    def get_all(self):
        return self.database.get_memories()

    def search(self, query: str, limit: int = 5):
        return self.search_engine.search(query, limit)

    def find_forget_candidates(self, query: str, limit: int = 3):
        return self.search(query, limit)

    def select_forget_candidates(self, query: str, memories):
        return self.decision.select_forget_candidates(
            query,
            memories
        )

    def close(self):
        self.database.close()
