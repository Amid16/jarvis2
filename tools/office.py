from docx import Document
from openpyxl import Workbook
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.util import Pt

import os
import re

from tools.workspace import (
    safe_path,
    backup_file,
    exists_refusal,
)
from tools.pptx_images import check_image, place_image
from tools.images import check_image_file, find_image
from tools.docx_images import split_content, add_picture_paragraphs


# Минимум слов в документе (заголовок, текст и подписи вместе).
# Меньше — почти наверняка модель забыла передать текст.
MIN_DOCUMENT_WORDS = 3


def _count_words(text: str) -> int:
    return len(re.findall(r"\w+", text))


def _backup_note(path: str, existed: bool) -> str:
    """Если файл заменяется, сначала сохраняем копию старой версии."""
    if not existed:
        return ""

    return f". Прежняя версия сохранена в workspace/{backup_file(path)}"


def create_docx(
    filename: str,
    title: str = "",
    content: str = "",
    overwrite: bool = False
) -> str:
    if not filename.endswith(".docx"):
        filename += ".docx"

    path = safe_path(filename)

    existed = os.path.exists(path)

    if existed and not overwrite:
        return exists_refusal(filename)

    blocks = split_content(content)

    words = _count_words(title)

    for block in blocks:
        words += _count_words(block[1] if block[0] == "text" else block[2])

    if words < MIN_DOCUMENT_WORDS:
        return (
            "Документ не создан: в нём почти нет текста (content пустой "
            "или слишком короткий). Напиши полный текст документа в "
            "content (абзацы разделяй пустой строкой) и повтори вызов."
        )

    # Сначала проверяем все картинки: если какой-то нет или она не
    # открывается, не создаём документ наполовину.
    for block in blocks:
        if block[0] != "image":
            continue

        problem = check_image_file(block[1])

        if problem:
            return f"Документ не создан. {problem}"

    document = Document()

    if title:
        document.add_heading(title, level=1)

    for block in blocks:
        if block[0] == "text":
            document.add_paragraph(block[1])
        else:
            _, image_name, caption = block

            add_picture_paragraphs(
                document,
                find_image(image_name),
                caption
            )

    note = _backup_note(path, existed)
    document.save(path)

    return f"Word-документ создан: workspace/{filename}{note}"


def create_xlsx(
    filename: str,
    sheet_title: str,
    rows: list,
    overwrite: bool = False
) -> str:
    if not filename.endswith(".xlsx"):
        filename += ".xlsx"

    path = safe_path(filename)

    existed = os.path.exists(path)

    if existed and not overwrite:
        return exists_refusal(filename)

    if not rows:
        return (
            "Таблица не создана: rows пустой. Передай строки таблицы "
            "(первая строка — заголовки) и повтори вызов."
        )

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = sheet_title or "Sheet1"

    for row in rows:
        sheet.append(row)

    note = _backup_note(path, existed)
    workbook.save(path)

    return f"Excel-файл создан: workspace/{filename}{note}"


def _normalize_hex_color(hex_color: str) -> str:
    return hex_color.strip().lstrip("#").upper()


def _apply_text_color(text_frame, hex_color: str):
    color = RGBColor.from_string(_normalize_hex_color(hex_color))

    for paragraph in text_frame.paragraphs:
        for run in paragraph.runs:
            run.font.color.rgb = color


def _apply_font_size(text_frame, font_size: float):
    for paragraph in text_frame.paragraphs:
        for run in paragraph.runs:
            run.font.size = Pt(font_size)


def _set_slide_background(slide, hex_color: str):
    fill = slide.background.fill
    fill.solid()
    fill.fore_color.rgb = RGBColor.from_string(
        _normalize_hex_color(hex_color)
    )


def create_pptx(
    filename: str,
    slides: list,
    background_color: str = None,
    overwrite: bool = False
) -> str:
    """
    slides: список словарей вида
    {
        "title": "...",
        "bullets": ["пункт 1", "пункт 2"],
        "title_color": "FF0000",      # необязательно
        "bullet_color": "333333",     # необязательно
        "bg_color": "1F1F1F",         # необязательно, свой фон слайда
        "font_size": 24,              # необязательно, в пунктах
        "image": "cat.png",           # необязательно, файл из workspace
        "image_position": "right"     # right, left, bottom или full
    }
    background_color — фон по умолчанию для всех слайдов,
    если у слайда не указан свой bg_color.
    """
    if not filename.endswith(".pptx"):
        filename += ".pptx"

    path = safe_path(filename)

    existed = os.path.exists(path)

    if existed and not overwrite:
        return exists_refusal(filename)

    if not slides:
        return (
            "Презентация не создана: список slides пуст. Передай "
            "слайды (title и bullets) и повтори вызов."
        )

    # Сначала проверяем все картинки: если какой-то нет или она
    # не открывается, не создаём презентацию наполовину.
    for number, slide_data in enumerate(slides, start=1):
        image = slide_data.get("image")

        if not image:
            continue

        problem = check_image(
            image,
            slide_data.get("image_position") or "right"
        )

        if problem:
            return (
                f"Презентация не создана. Слайд {number}: {problem}"
            )

    presentation = Presentation()
    layout = presentation.slide_layouts[1]

    for slide_data in slides:
        slide = presentation.slides.add_slide(layout)

        bg_color = slide_data.get("bg_color") or background_color

        if bg_color:
            _set_slide_background(slide, bg_color)

        title_shape = slide.shapes.title
        title_shape.text = slide_data.get("title", "")

        if slide_data.get("title_color"):
            _apply_text_color(
                title_shape.text_frame,
                slide_data["title_color"]
            )

        bullets = slide_data.get("bullets", [])
        body = slide.placeholders[1].text_frame

        if bullets:
            body.text = bullets[0]

            for bullet in bullets[1:]:
                paragraph = body.add_paragraph()
                paragraph.text = bullet

        if slide_data.get("image"):
            place_image(
                presentation,
                slide,
                find_image(slide_data["image"]),
                slide_data.get("image_position") or "right"
            )

        if slide_data.get("bullet_color"):
            _apply_text_color(body, slide_data["bullet_color"])

        if slide_data.get("font_size"):
            _apply_font_size(body, slide_data["font_size"])

    note = _backup_note(path, existed)
    presentation.save(path)

    return f"PowerPoint-презентация создана: workspace/{filename}{note}"
