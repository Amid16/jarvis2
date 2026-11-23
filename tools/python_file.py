import os

from tools.workspace import safe_path, backup_file, exists_refusal


def write_python_file(
    filename: str,
    code: str,
    overwrite: bool = False
) -> str:
    if not filename.endswith(".py"):
        filename += ".py"

    path = safe_path(filename)
    existed = os.path.exists(path)

    if existed and not overwrite:
        return exists_refusal(filename)

    note = ""

    if existed:
        note = f" Прежняя версия сохранена в workspace/{backup_file(path)}."

    with open(path, "w", encoding="utf-8") as file:
        file.write(code)

    return (
        f"Python-файл сохранён: workspace/{filename}.{note} "
        f"Он только записан на диск — JARVIS его не запускал."
    )
