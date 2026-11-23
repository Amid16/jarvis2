import re


STOP_WORDS = {
    "я", "ты", "он", "она", "мы", "вы",
    "а", "и", "или", "но",
    "в", "на", "из", "к", "у", "с",
    "о", "об", "от", "до", "по",
    "какой", "какая", "какое", "какие",
    "что", "где", "когда", "как",
    "мой", "моя", "моё", "мои",
    "мне", "меня", "тебе", "тебя",
    "это", "этот", "эта", "эти",
}


def normalize_word(word: str) -> str:
    """
    Приводит слово к простой нормализованной форме.

    Это пока не полноценная морфология русского языка.
    Мы используем простое удаление распространённых окончаний.
    """

    word = word.lower().strip(
        ".,!?;:\"()[]{}"
    )

    if len(word) <= 3:
        return word

    endings = (
        "ами", "ями",
        "ого", "ему", "ому",
        "ами", "ями",
        "ах", "ях",
        "ов", "ев", "ей",
        "ам", "ям",
        "ом", "ем",
        "ой", "ей",
        "ы", "и",
        "а", "я",
        "у", "ю",
        "е",
        "о",
    )

    for ending in endings:
        if word.endswith(ending) and len(word) - len(ending) >= 3:
            return word[:-len(ending)]

    return word


def get_keywords(text: str) -> set[str]:
    words = re.findall(
        r"[а-яёa-z0-9]+",
        text.lower()
    )

    keywords = set()

    for word in words:
        if word in STOP_WORDS:
            continue

        normalized = normalize_word(word)

        if normalized:
            keywords.add(normalized)

    return keywords


def calculate_keyword_match(
    query: str,
    content: str
) -> float:
    query_keywords = get_keywords(query)
    content_keywords = get_keywords(content)

    if not query_keywords:
        return 0.0

    matched_words = query_keywords & content_keywords

    return len(matched_words) / len(query_keywords)


def calculate_memory_score(
    semantic_similarity: float,
    keyword_match: float
) -> float:
    return (
        semantic_similarity * 0.7
        + keyword_match * 0.3
    )