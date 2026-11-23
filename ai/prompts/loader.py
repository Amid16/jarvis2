from pathlib import Path


PROMPTS_DIR = Path(__file__).parent


def load_prompt(name: str) -> str:
    prompt_file = PROMPTS_DIR / f"{name}.txt"

    if not prompt_file.exists():
        raise FileNotFoundError(
            f"Промпт не найден: {prompt_file}"
        )

    return prompt_file.read_text(encoding="utf-8").strip()