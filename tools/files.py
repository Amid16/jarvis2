import os

from config import WORKSPACE_DIR
from tools.workspace import (
    BACKUP_DIR_NAME,
    ensure_workspace,
    relative_to_workspace,
    safe_existing_file,
    safe_path,
)


IMAGE_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff", ".webp"
}

MAX_LISTED_FILES = 200


def list_workspace_files(
    subfolder: str = "",
    only_images: bool = False
) -> str:
    """Показывает, какие файлы лежат в рабочей папке (только чтение)."""
    ensure_workspace()

    try:
        root = (
            safe_path(subfolder, create_dirs=False)
            if subfolder
            else os.path.abspath(WORKSPACE_DIR)
        )
    except ValueError as error:
        return str(error)

    if not os.path.isdir(root):
        return f"Папки workspace/{subfolder} нет."

    lines = []

    for folder, subfolders, files in os.walk(root):
        # Папку с резервными копиями в списке не показываем.
        subfolders[:] = [
            name for name in subfolders if name != BACKUP_DIR_NAME
        ]
        subfolders.sort()

        for name in sorted(files):
            extension = os.path.splitext(name)[1].lower()

            if only_images and extension not in IMAGE_EXTENSIONS:
                continue

            full_path = os.path.join(folder, name)
            size_kb = max(1, os.path.getsize(full_path) // 1024)

            lines.append(
                f"{relative_to_workspace(full_path)} ({size_kb} КБ)"
            )

            if len(lines) >= MAX_LISTED_FILES:
                break

        if len(lines) >= MAX_LISTED_FILES:
            break

    if not lines:
        if only_images:
            return (
                "В workspace нет картинок. Пользователю нужно "
                "положить картинки в папку workspace рядом с JARVIS."
            )

        return "В workspace пока нет файлов."

    return "Файлы в workspace:\n" + "\n".join(lines)


def rename_workspace_file(filename: str, new_name: str) -> str:
    """
    Переименовывает файл внутри workspace. Ничего не удаляет и не
    заменяет: если файл с новым именем уже есть, отказывает.
    """
    try:
        source = safe_existing_file(filename)
    except (ValueError, FileNotFoundError) as error:
        return str(error)

    old_extension = os.path.splitext(source)[1]
    new_extension = os.path.splitext(new_name)[1]

    if not new_extension:
        new_name += old_extension
    elif new_extension.lower() != old_extension.lower():
        return (
            f"Расширение файла менять нельзя: было "
            f"'{old_extension or 'без расширения'}', а в новом имени "
            f"'{new_extension}'."
        )

    try:
        target = safe_path(new_name)
    except ValueError as error:
        return str(error)

    if os.path.exists(target):
        return (
            f"Файл workspace/{relative_to_workspace(target)} уже "
            f"существует, переименовывать некуда. Нужно другое имя."
        )

    old_display = relative_to_workspace(source)
    new_display = relative_to_workspace(target)

    os.rename(source, target)

    return f"Файл workspace/{old_display} переименован в workspace/{new_display}."
