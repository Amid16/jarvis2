import io
import os

from PIL import Image, ImageOps

from config import WORKSPACE_DIR
from tools.workspace import (
    BACKUP_DIR_NAME,
    relative_to_workspace,
    safe_path,
)


NATIVE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff"}

# Эти форматы Office не понимает напрямую, поэтому перед вставкой
# мы незаметно перегоняем их в PNG.
CONVERTIBLE_EXTENSIONS = {".webp"}


IMAGE_EXTENSIONS = NATIVE_EXTENSIONS | CONVERTIBLE_EXTENSIONS


def _available_images(limit: int = 15) -> list:
    names = []

    for folder, subfolders, files in os.walk(os.path.abspath(WORKSPACE_DIR)):
        subfolders[:] = sorted(
            name for name in subfolders if name != BACKUP_DIR_NAME
        )

        for name in sorted(files):
            if os.path.splitext(name)[1].lower() in IMAGE_EXTENSIONS:
                names.append(
                    relative_to_workspace(os.path.join(folder, name))
                )

    return names[:limit]


def find_image(relative_path: str) -> str:
    """
    Находит картинку в workspace. Если точного имени нет, но в той же
    папке лежит ровно одна картинка с таким же именем без расширения
    (модель написала moon.jpg, а файл называется moon.png), берём её.
    """
    path = safe_path(relative_path, create_dirs=False)

    if os.path.isfile(path):
        return path

    folder = os.path.dirname(path)
    stem = os.path.splitext(os.path.basename(path))[0].casefold()
    matches = []

    if os.path.isdir(folder):
        for name in sorted(os.listdir(folder)):
            full_path = os.path.join(folder, name)
            name_stem, name_extension = os.path.splitext(name)

            if (
                os.path.isfile(full_path)
                and name_stem.casefold() == stem
                and name_extension.lower() in IMAGE_EXTENSIONS
            ):
                matches.append(full_path)

    if len(matches) == 1:
        return matches[0]

    if len(matches) > 1:
        names = ", ".join(relative_to_workspace(m) for m in matches)

        raise FileNotFoundError(
            f"Под имя '{relative_path}' подходит несколько картинок: "
            f"{names}. Укажи точное имя."
        )

    available = _available_images()
    listing = (
        ", ".join(available)
        if available
        else "в workspace нет ни одной картинки"
    )

    raise FileNotFoundError(
        f"Картинки workspace/{relative_path} нет. Картинки в "
        f"workspace: {listing}. Не угадывай имя: возьми его из "
        f"этого списка."
    )


def prepare_image(path: str):
    """
    Открывает картинку и возвращает (что_вставлять, ширина, высота).
    "Что вставлять" — это путь к файлу или, если картинку пришлось
    преобразовать (webp или фото, снятое "боком" на телефон), — поток
    в памяти. Сам файл в workspace мы никогда не меняем.
    """
    extension = os.path.splitext(path)[1].lower()

    if extension not in NATIVE_EXTENSIONS | CONVERTIBLE_EXTENSIONS:
        raise ValueError(
            f"Формат картинки '{extension or 'без расширения'}' не "
            f"поддерживается. Подходят: PNG, JPG, GIF, BMP, TIFF, WEBP."
        )

    try:
        with Image.open(path) as image:
            orientation = image.getexif().get(0x0112, 1)

            needs_conversion = (
                extension in CONVERTIBLE_EXTENSIONS
                or orientation not in (None, 1)
            )

            if not needs_conversion:
                return path, image.width, image.height

            fixed = ImageOps.exif_transpose(image)

            if fixed.mode not in ("RGB", "RGBA", "L", "LA", "P"):
                fixed = fixed.convert("RGB")

            buffer = io.BytesIO()
            fixed.save(buffer, format="PNG")
            buffer.seek(0)

            return buffer, fixed.width, fixed.height

    except OSError as error:
        raise ValueError(f"Не удалось открыть картинку: {error}")


def check_image_file(image: str):
    """
    Проверяет заранее, что картинка лежит в workspace и открывается.
    Возвращает текст проблемы или None, если всё в порядке.
    """
    try:
        path = find_image(image)
        prepare_image(path)
    except (ValueError, FileNotFoundError) as error:
        return str(error)

    return None
