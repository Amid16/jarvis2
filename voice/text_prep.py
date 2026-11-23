import re

from num2words import num2words


TIME_PATTERN = re.compile(r"\b([01]?\d|2[0-3]):([0-5]\d)\b")
NUMBER_PATTERN = re.compile(r"\d+")
ENGLISH_WORD_PATTERN = re.compile(r"[A-Za-z]+")

# Многобуквенные сочетания проверяются раньше одиночных букв,
# иначе, например, "sh" превратится в "с"+"х" вместо "ш".
MULTI_LETTER_MAP = (
    ("tion", "шн"),
    ("sion", "жн"),
    ("sh", "ш"),
    ("ch", "ч"),
    ("ck", "к"),
    ("ph", "ф"),
    ("wh", "в"),
    ("qu", "кв"),
    ("th", "з"),
    ("ng", "нг"),
    ("oo", "у"),
    ("ee", "и"),
    ("ea", "и"),
    ("igh", "ай"),
    ("ai", "эй"),
    ("ay", "эй"),
    ("ey", "эй"),
    ("oy", "ой"),
    ("ou", "ау"),
    ('youtube', 'ютуб'),
    ('computer', 'компьютер'),
    ('presentation', 'презентация'),
    ('png', 'пнг')
)

SINGLE_LETTER_MAP = {
    "a": "а", "b": "б", "c": "к", "d": "д", "e": "е", "f": "ф",
    "g": "г", "h": "х", "i": "и", "j": "дж", "k": "к", "l": "л",
    "m": "м", "n": "н", "o": "о", "p": "п", "q": "к", "r": "р",
    "s": "с", "t": "т", "u": "а", "v": "в", "w": "в", "x": "кс",
    "y": "й", "z": "з",
}


def _transliterate_word(word: str) -> str:
    lower = word.lower()
    result = []
    i = 0

    while i < len(lower):
        matched = False

        for pattern, replacement in MULTI_LETTER_MAP:
            if lower.startswith(pattern, i):
                result.append(replacement)
                i += len(pattern)
                matched = True
                break

        if not matched:
            result.append(SINGLE_LETTER_MAP.get(lower[i], lower[i]))
            i += 1

    return "".join(result)


def transliterate_english(text: str) -> str:
    """
    Грубо переводит латиницу в кириллицу для озвучки.
    Это приблизительная фонетическая транскрипция "на глаз",
    а не словарный перевод — на сложных словах будет неточно.
    """
    return ENGLISH_WORD_PATTERN.sub(
        lambda match: _transliterate_word(match.group()),
        text
    )


def normalize_time(text: str) -> str:
    def replace(match):
        hours = int(match.group(1))
        minutes = int(match.group(2))

        hours_word = num2words(hours, lang="ru")
        minutes_word = (
            num2words(minutes, lang="ru") if minutes else "ноль"
        )

        return f"{hours_word} {minutes_word}"

    return TIME_PATTERN.sub(replace, text)


def normalize_numbers(text: str) -> str:
    def replace(match):
        return num2words(int(match.group()), lang="ru")

    return NUMBER_PATTERN.sub(replace, text)


def prepare_for_speech(text: str) -> str:
    # Время нужно обработать раньше обычных чисел, иначе
    # "18:47" сначала попадёт под общее правило для чисел.
    text = normalize_time(text)
    text = normalize_numbers(text)
    text = transliterate_english(text)

    return text
