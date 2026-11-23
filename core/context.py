class Conversation:
    def __init__(
        self,
        system_prompt: str | None = None,
        user_context: str | None = None
    ):
        self.messages = []

        if system_prompt:
            self.messages.append({
                "role": "system",
                "content": system_prompt
            })

        if user_context:
            self.messages.append({
                "role": "system",
                "content": user_context
            })

    def add_user_message(self, content: str):
        self.messages.append({
            "role": "user",
            "content": content
        })

    def add_assistant_message(self, content: str):
        self.messages.append({
            "role": "assistant",
            "content": content
        })

    def get_messages(self):
        return self.messages

    def get_messages_trimmed(self, max_chars: int):
        """
        Системные сообщения и самые свежие реплики, которые помещаются
        в max_chars символов. Нужно, чтобы долгий разговор (особенно в
        окне, которое открыто часами) не переполнил контекст модели и
        не вытеснил из него системный промпт.
        """
        system = [m for m in self.messages if m["role"] == "system"]
        rest = [m for m in self.messages if m["role"] != "system"]

        kept = []
        total = 0

        for message in reversed(rest):
            size = len(message["content"])

            if kept and total + size > max_chars:
                break

            kept.append(message)
            total += size

        kept.reverse()

        # Разговор не должен начинаться с ответа без вопроса.
        while len(kept) > 1 and kept[0]["role"] != "user":
            kept.pop(0)

        return system + kept

    def clear(self):
        self.messages.clear()