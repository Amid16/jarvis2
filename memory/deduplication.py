import re


STOP_WORDS = {
    "я", "мне", "мой", "моя", "мои", "мое",
    "ты", "он", "она", "мы", "вы",
    "это", "этот", "эта", "эти",
    "и", "а", "но", "или",
    "в", "на", "с", "из", "к", "у",
    "для", "по", "о", "об",
    "очень", "сейчас",
    "пользователь", "пользователю", "пользователя",
}


def get_keywords(text: str) -> set[str]:
    words = re.findall(
        r"[а-яёa-z0-9]+",
        text.lower()
    )

    return {
        word
        for word in words
        if word not in STOP_WORDS and len(word) > 2
    }


def calculate_keyword_similarity(
    text_a: str,
    text_b: str
) -> float:
    keywords_a = get_keywords(text_a)
    keywords_b = get_keywords(text_b)

    if not keywords_a or not keywords_b:
        return 0.0

    intersection = keywords_a & keywords_b
    union = keywords_a | keywords_b

    return len(intersection) / len(union)
