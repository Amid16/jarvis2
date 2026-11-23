import os
import re
import shutil
from datetime import datetime

from config import WORKSPACE_DIR, AGENT_ALLOW_OUTSIDE_WORKSPACE


BACKUP_DIR_NAME = "_backup"


def ensure_workspace():
    os.makedirs(WORKSPACE_DIR, exist_ok=True)


def _looks_absolute(path: str) -> bool:
    if os.path.isabs(path):
        return True

    # Путь с буквой диска Windows (C:\... или C:/...) —
    # проверяем явно, чтобы это ловилось даже при тестах не
    # на Windows, и чтобы os.path.join не мог отбросить
    # рабочую папку из-за такого пути.
    if re.match(r"^[a-zA-Z]:[\\/]", path):
        return True

    # Сетевой путь \\server\share
    if path.startswith("\\\\") or path.startswith("//"):
        return True

    return False


def safe_path(relative_path: str, create_dirs: bool = True) -> str:
    """
    Превращает имя файла в безопасный путь внутри workspace.
    Не даёт агенту выйти за пределы рабочей папки — ни через
    "..\\" в имени файла, ни через абсолютный путь.
    """
    ensure_workspace()

    if _looks_absolute(relative_path) and not AGENT_ALLOW_OUTSIDE_WORKSPACE:
        raise ValueError(
            f"Путь '{relative_path}' — абсолютный путь. "
            f"Операции разрешены только внутри рабочей папки "
            f"workspace."
        )

    candidate = os.path.normpath(
        os.path.join(WORKSPACE_DIR, relative_path)
    )

    workspace_abs = os.path.abspath(WORKSPACE_DIR)
    candidate_abs = os.path.abspath(candidate)

    inside_workspace = (
        candidate_abs == workspace_abs
        or candidate_abs.startswith(workspace_abs + os.sep)
    )

    if not inside_workspace and not AGENT_ALLOW_OUTSIDE_WORKSPACE:
        raise ValueError(
            f"Путь '{relative_path}' выходит за пределы рабочей "
            f"папки workspace. Операция запрещена."
        )

    if create_dirs:
        os.makedirs(
            os.path.dirname(candidate_abs),
            exist_ok=True
        )

    return candidate_abs


def safe_existing_file(relative_path: str) -> str:
    """
    Безопасный путь к файлу, который уже должен лежать в workspace.
    Ничего не создаёт — если файла нет, понятно говорит об этом.
    """
    path = safe_path(relative_path, create_dirs=False)

    if not os.path.isfile(path):
        raise FileNotFoundError(
            f"Файла workspace/{relative_path} нет. Посмотри, какие "
            f"файлы есть, инструментом list_workspace_files."
        )

    return path


def relative_to_workspace(path: str) -> str:
    relative = os.path.relpath(path, os.path.abspath(WORKSPACE_DIR))

    return relative.replace(os.sep, "/")


def backup_file(path: str) -> str:
    """
    Копирует файл в workspace/_backup/ с отметкой времени.
    Вызывается перед тем, как изменить существующий файл, чтобы
    старую версию всегда можно было вернуть.
    Возвращает путь к копии относительно workspace.
    """
    backup_dir = os.path.join(WORKSPACE_DIR, BACKUP_DIR_NAME)
    os.makedirs(backup_dir, exist_ok=True)

    stem, extension = os.path.splitext(os.path.basename(path))
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    destination = os.path.join(
        backup_dir,
        f"{stem}_{stamp}{extension}"
    )

    # Две правки в одну секунду не должны затирать копии друг друга.
    counter = 2

    while os.path.exists(destination):
        destination = os.path.join(
            backup_dir,
            f"{stem}_{stamp}_{counter}{extension}"
        )
        counter += 1

    shutil.copy2(path, destination)

    return relative_to_workspace(destination)


def exists_refusal(filename: str) -> str:
    """Сообщение для модели, когда файл уже есть, а перезапись не разрешена."""
    return (
        f"Файл workspace/{filename} уже существует. Не перезаписывай "
        f"его сам и не выбирай другое имя: сообщи об этом в отчёте, "
        f"чтобы пользователь решил — заменить файл или выбрать другое "
        f"имя. Если в задаче явно разрешена перезапись, повтори вызов "
        f"с overwrite=true."
    )
