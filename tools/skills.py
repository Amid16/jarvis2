import os

from tools.workspace import safe_path


SKILL_DRAFTS_DIR = "skill_drafts"


def draft_skill(filename: str, code: str, description: str) -> str:
    """
    Сохраняет предложенный код нового инструмента как черновик.

    ВАЖНО: черновик НЕ подключается и не выполняется
    автоматически. Это осознанное ограничение безопасности —
    JARVIS не должен сам себе выдавать новые возможности без
    контроля человека. Чтобы навык заработал, пользователь
    должен сам просмотреть код и подключить его вручную.
    """
    if not filename.endswith(".py"):
        filename += ".py"

    relative_path = os.path.join(SKILL_DRAFTS_DIR, filename)
    path = safe_path(relative_path)

    if os.path.exists(path):
        return (
            f"Черновик workspace/{SKILL_DRAFTS_DIR}/{filename} "
            f"уже существует. Выбери другое имя."
        )

    with open(path, "w", encoding="utf-8") as file:
        file.write(code)

    return (
        f"Черновик навыка сохранён: "
        f"workspace/{SKILL_DRAFTS_DIR}/{filename}\n"
        f"Назначение: {description}\n"
        f"Это только черновик. Он не подключён к проекту и "
        f"не будет выполняться, пока пользователь сам не "
        f"просмотрит код и не подключит его."
    )
