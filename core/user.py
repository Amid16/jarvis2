class UserProfile:
    def __init__(self, name: str):
        self.name = name

    def get_context(self) -> str:
        return f"Имя пользователя: {self.name}"