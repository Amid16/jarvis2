from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE, PP_PLACEHOLDER
from pptx.util import Pt

from tools.images import prepare_image, check_image_file, find_image
from tools.workspace import (
    safe_existing_file,
    backup_file,
    relative_to_workspace,
)


POSITIONS = ("right", "left", "bottom", "full")

# Промежуток между текстом и картинкой, как доля ширины слайда.
GAP_RATIO = 0.03

# Размер шрифта текста, который мы сжимаем, освобождая место картинке.
SIDE_TEXT_SIZE_PT = 22
BOTTOM_TEXT_SIZE_PT = 20


def check_image(image: str, position: str):
    """
    Проверяет заранее, что картинку можно вставить.
    Возвращает текст проблемы или None, если всё в порядке.
    """
    if position not in POSITIONS:
        return (
            f"Неизвестное расположение '{position}'. "
            f"Доступно: right, left, bottom, full."
        )

    return check_image_file(image)


def _find_body_placeholder(slide):
    for placeholder in slide.placeholders:
        placeholder_type = placeholder.placeholder_format.type

        if placeholder_type in (PP_PLACEHOLDER.BODY, PP_PLACEHOLDER.OBJECT):
            return placeholder

    return None


def _has_text(shape) -> bool:
    return (
        shape is not None
        and shape.has_text_frame
        and shape.text_frame.text.strip() != ""
    )


def _remove_shape(shape):
    element = shape._element
    element.getparent().remove(element)


def _content_area(presentation, body):
    """Область слайда под заголовком, где обычно лежит основной текст."""
    if body is not None:
        values = (body.left, body.top, body.width, body.height)

        if all(value is not None for value in values):
            return values

    width = presentation.slide_width
    height = presentation.slide_height

    return (
        int(width * 0.05),
        int(height * 0.25),
        int(width * 0.90),
        int(height * 0.68),
    )


def _fit_in_box(box, image_width, image_height):
    """Вписывает картинку в рамку без искажения и ставит по центру."""
    left, top, width, height = box

    scale = min(width / image_width, height / image_height)

    new_width = int(image_width * scale)
    new_height = int(image_height * scale)

    return (
        left + (width - new_width) // 2,
        top + (height - new_height) // 2,
        new_width,
        new_height,
    )


def _shrink_body_text(body, size_pt: int):
    """Уменьшает текст, если размер не задан явно, чтобы он влез в
    более узкую рамку."""
    for paragraph in body.text_frame.paragraphs:
        for run in paragraph.runs:
            if run.font.size is None:
                run.font.size = Pt(size_pt)


def _place_full_slide(presentation, slide, source, image_width, image_height):
    slide_width = presentation.slide_width
    slide_height = presentation.slide_height

    picture = slide.shapes.add_picture(
        source, 0, 0, slide_width, slide_height
    )

    # Картинка заполняет весь слайд, лишнее обрезается по краям —
    # так она не растягивается и не искажается.
    slide_ratio = slide_width / slide_height
    image_ratio = image_width / image_height

    if image_ratio > slide_ratio:
        crop = (1 - slide_ratio / image_ratio) / 2
        picture.crop_left = crop
        picture.crop_right = crop
    else:
        crop = (1 - image_ratio / slide_ratio) / 2
        picture.crop_top = crop
        picture.crop_bottom = crop

    # Отправляем картинку на самый задний план, под текст.
    shape_tree = slide.shapes._spTree
    shape_tree.remove(picture._element)
    shape_tree.insert(2, picture._element)


def place_image(presentation, slide, image_path: str, position: str):
    source, image_width, image_height = prepare_image(image_path)

    if position == "full":
        _place_full_slide(
            presentation, slide, source, image_width, image_height
        )
        return

    body = _find_body_placeholder(slide)
    area = _content_area(presentation, body)

    left, top, width, height = area
    gap = int(presentation.slide_width * GAP_RATIO)

    if not _has_text(body):
        # Текста нет — пустую рамку убираем, и картинка занимает
        # всё место под заголовком.
        if body is not None:
            _remove_shape(body)

        picture_box = area
    elif position == "right":
        half = (width - gap) // 2
        body.left, body.top, body.width, body.height = left, top, half, height
        picture_box = (left + half + gap, top, half, height)
        _shrink_body_text(body, SIDE_TEXT_SIZE_PT)
    elif position == "left":
        half = (width - gap) // 2
        body.left, body.top, body.width, body.height = (
            left + half + gap, top, half, height
        )
        picture_box = (left, top, half, height)
        _shrink_body_text(body, SIDE_TEXT_SIZE_PT)
    else:  # bottom
        text_height = int(height * 0.45)
        body.left, body.top, body.width, body.height = (
            left, top, width, text_height
        )
        picture_box = (
            left,
            top + text_height + gap,
            width,
            height - text_height - gap,
        )
        _shrink_body_text(body, BOTTOM_TEXT_SIZE_PT)

    x, y, picture_width, picture_height = _fit_in_box(
        picture_box, image_width, image_height
    )

    slide.shapes.add_picture(source, x, y, picture_width, picture_height)


def add_image_to_pptx(
    filename: str,
    slide_number: int,
    image: str,
    position: str = "right",
    replace_existing: bool = False
) -> str:
    """Вставляет картинку из workspace в уже готовую презентацию."""
    if not filename.endswith(".pptx"):
        filename += ".pptx"

    try:
        slide_number = int(slide_number)
    except (TypeError, ValueError):
        return "Номер слайда должен быть числом."

    problem = check_image(image, position)

    if problem:
        return problem

    try:
        pptx_path = safe_existing_file(filename)
    except (ValueError, FileNotFoundError) as error:
        return str(error)

    presentation = Presentation(pptx_path)
    total = len(presentation.slides)

    if not 1 <= slide_number <= total:
        return (
            f"В презентации {total} слайдов, слайда №{slide_number} "
            f"нет."
        )

    slide = presentation.slides[slide_number - 1]

    pictures = [
        shape for shape in slide.shapes
        if shape.shape_type == MSO_SHAPE_TYPE.PICTURE
    ]

    if pictures and not replace_existing:
        return (
            f"На слайде {slide_number} уже есть картинка. Если её "
            f"нужно заменить, вызови инструмент ещё раз с "
            f"replace_existing=true."
        )

    for picture in pictures:
        _remove_shape(picture)

    place_image(
        presentation,
        slide,
        find_image(image),
        position
    )

    # Сначала копия старой версии, потом сохранение поверх.
    backup = backup_file(pptx_path)
    presentation.save(pptx_path)

    return (
        f"Картинка workspace/{relative_to_workspace(find_image(image))} "
        f"добавлена на слайд {slide_number} презентации "
        f"workspace/{filename}. Прежняя версия презентации сохранена "
        f"в workspace/{backup}."
    )
