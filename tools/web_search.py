from ddgs import DDGS


MAX_RESULTS = 5


def web_search(query: str) -> str:
    query = query.strip()

    if not query:
        return "Пустой поисковый запрос."

    try:
        results = DDGS().text(query, max_results=MAX_RESULTS)
    except Exception as error:
        return f"Не удалось выполнить поиск: {error}"

    if not results:
        return "Ничего не найдено."

    lines = []

    for index, item in enumerate(results, start=1):
        title = item.get("title", "")
        body = item.get("body", "")
        href = item.get("href", "")

        lines.append(
            f"{index}. {title}\n{body}\nИсточник: {href}"
        )

    return "\n\n".join(lines)
