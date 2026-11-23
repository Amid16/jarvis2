import re

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Cm, Emu, Pt

from tools.images import prepare_image, check_image_file, find_image
from tools.workspace import (
    safe_existing_file,
    backup_file,
    relative_to_workspace,
)


# Метка картинки в тексте документа:
#   [[image: cat.png]]  или  [[image: cat.png | Подпись под картинкой]]
IMAGE_MARKER = re.compile(
    r"\[\[\s*(?:image|картинка|изображение)\s*:\s*"
    r"([^\]|]+?)\s*(?:\|\s*([^\]]*?))?\s*\]\]",
    re.IGNORECASE
)

EMU_PER_INCH = 914400
SCREEN_DPI = 96

# Запасные размеры на случай нестандартного документа без полей.
FALLBACK_MAX_WIDTH = Cm(15)
FALLBACK_MAX_HEIGHT = Cm(20)

MAX_OUTLINE_ITEMS = 15


def _text_blocks(text: str):
    blocks = []

    for chunk in text.split("\n\n"):
        chunk = chunk.strip()

        if chunk:
            blocks.append(("text", chunk))

    return blocks


def split_content(content: str):
    """
    Режет текст документа на блоки:
      ("text", "абзац")
      ("image", "имя_файла", "подпись")
    Метка картинки может стоять и отдельной строкой, и внутри текста.
    """
    blocks = []
    position = 0

    for match in IMAGE_MARKER.finditer(content):
        blocks += _text_blocks(content[position:match.start()])

        blocks.append((
            "image",
            match.group(1).strip(),
            (match.group(2) or "").strip()
        ))

        position = match.end()

    blocks += _text_blocks(content[position:])

    return blocks


def _usable_size(document):
    """Сколько места на странице остаётся под картинку."""
    section = document.sections[-1]

    try:
        max_width = (
            section.page_width - section.left_margin - section.right_margin
        )
        # Берём не всю высоту, а с запасом под подпись.
        max_height = int(
            (section.page_height - section.top_margin
             - section.bottom_margin) * 0.85
        )
    except TypeError:
        return FALLBACK_MAX_WIDTH, FALLBACK_MAX_HEIGHT

    return max_width, max_height


def _picture_size(max_width, max_height, image_w, image_h, width_cm=None):
    """
    Размер картинки в EMU. Картинку не растягиваем сверх её "родного"
    размера (иначе маленький значок станет мутным пятном) и не даём
    выйти за поля или за высоту страницы.
    """
    if width_cm:
        width = int(Cm(width_cm))
    else:
        width = int(image_w / SCREEN_DPI * EMU_PER_INCH)

    width = min(width, int(max_width))
    height = int(width * image_h / image_w)

    if height > max_height:
        height = int(max_height)
        width = int(height * image_w / image_h)

    return Emu(width), Emu(height)


def add_picture_paragraphs(
    document,
    image_path: str,
    caption: str = "",
    width_cm=None
):
    """
    Добавляет в конец документа абзац с картинкой (и подпись, если
    есть). Возвращает список созданных абзацев, чтобы при необходимости
    их можно было переставить на другое место.
    """
    source, image_w, image_h = prepare_image(image_path)
    max_width, max_height = _usable_size(document)

    width, height = _picture_size(
        max_width, max_height, image_w, image_h, width_cm
    )

    picture_paragraph = document.add_paragraph()
    picture_paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    picture_paragraph.add_run().add_picture(
        source, width=width, height=height
    )

    created = [picture_paragraph]

    if caption:
        caption_paragraph = document.add_paragraph()
        caption_paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER

        try:
            caption_paragraph.style = document.styles["Caption"]
            caption_paragraph.add_run(caption)
        except KeyError:
            # В документе пользователя может не быть стиля подписи.
            run = caption_paragraph.add_run(caption)
            run.italic = True
            run.font.size = Pt(9)

        created.append(caption_paragraph)

    return created


def _outline(document) -> str:
    items = []

    for paragraph in document.paragraphs:
        text = paragraph.text.strip()

        if text:
            items.append(f"- {text[:60]}")

        if len(items) >= MAX_OUTLINE_ITEMS:
            break

    return "\n".join(items)


def add_image_to_docx(
    filename: str,
    image: str,
    position: str = "end",
    after_text: str = "",
    caption: str = "",
    width_cm=None
) -> str:
    """Вставляет картинку из workspace в уже готовый Word-документ."""
    if not filename.endswith(".docx"):
        filename += ".docx"

    if position not in ("start", "end"):
        return (
            f"Неизвестное расположение '{position}'. Доступно: start "
            f"(в начало), end (в конец). Чтобы вставить после "
            f"конкретного абзаца, укажи after_text."
        )

    try:
        width_cm = float(width_cm) if width_cm else None
    except (TypeError, ValueError):
        width_cm = None

    if width_cm is not None and width_cm <= 0:
        width_cm = None

    problem = check_image_file(image)

    if problem:
        return problem

    try:
        docx_path = safe_existing_file(filename)
    except (ValueError, FileNotFoundError) as error:
        return str(error)

    document = Document(docx_path)

    target = None

    if after_text.strip():
        needle = after_text.strip().casefold()

        for paragraph in document.paragraphs:
            if needle in paragraph.text.casefold():
                target = paragraph
                break

        if target is None:
            return (
                f"В документе нет абзаца с текстом '{after_text}'. "
                f"Вот начало документа:\n{_outline(document)}\n"
                f"Выбери фразу из этого списка или используй "
                f"position='end' или position='start'."
            )

    image_path = find_image(image)

    created = add_picture_paragraphs(
        document, image_path, caption, width_cm
    )

    # Картинка сначала добавляется в конец, потом переносится на место.
    if target is not None:
        anchor = target._p

        for paragraph in created:
            anchor.addnext(paragraph._p)
            anchor = paragraph._p

        where = f"после абзаца со словами '{after_text.strip()}'"
    elif position == "start" and len(document.paragraphs) > len(created):
        first = document.paragraphs[0]

        for paragraph in created:
            first._p.addprevious(paragraph._p)

        where = "в начало"
    else:
        where = "в конец"

    # Сначала копия старой версии, потом сохранение поверх.
    backup = backup_file(docx_path)
    document.save(docx_path)

    return (
        f"Картинка workspace/{relative_to_workspace(image_path)} "
        f"вставлена {where} документа workspace/{filename}. Прежняя "
        f"версия документа сохранена в workspace/{backup}."
    )
