import json
import re
import urllib.request
from datetime import datetime

from config import (
    OLLAMA_URL,
    OLLAMA_CHAT_MODEL,
    OLLAMA_AGENT_MODEL,
    CHAT_TEMPERATURE,
    AGENT_TEMPERATURE,
    CHAT_NUM_CTX,
    AGENT_NUM_CTX,
    SHOW_TOKEN_USAGE,
    OLLAMA_TIMEOUT,
)
from ai.provider import AIProvider
from ai.prompts.loader import load_prompt
from core.events import emit
from tools.web_search import web_search
from tools.office import create_docx, create_xlsx, create_pptx
from tools.python_file import write_python_file
from tools.skills import draft_skill
from tools.files import list_workspace_files, rename_workspace_file
from tools.pptx_images import add_image_to_pptx
from tools.docx_images import add_image_to_docx


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": (
                "Ищет актуальную информацию в интернете. Используй, "
                "когда для ответа нужны свежие или неизвестные тебе "
                "данные: новости, текущие события, курсы, факты про "
                "конкретные продукты, версии, даты и так далее. Не "
                "используй для того, что ты и так знаешь."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Поисковый запрос"
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_docx",
            "description": (
                "Создаёт документ Word (.docx) в рабочей папке "
                "пользователя. Используй, когда просят подготовить "
                "документ, отчёт, текстовый файл в формате Word. "
                "Чтобы вставить картинку из папки workspace, напиши "
                "в нужном месте текста метку [[image: имя_файла]] "
                "или с подписью [[image: имя_файла | Подпись]]. "
                "Имена файлов бери из list_workspace_files, не "
                "придумывай их."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {
                        "type": "string",
                        "description": "Имя файла, например report.docx"
                    },
                    "title": {
                        "type": "string",
                        "description": "Заголовок документа"
                    },
                    "content": {
                        "type": "string",
                        "description": (
                            "Текст документа. Абзацы разделяй "
                            "двойным переносом строки. Картинка — "
                            "метка вида [[image: cat.png | Подпись]] "
                            "на месте, где она должна стоять."
                        )
                    }
                },
                "required": ["filename", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_xlsx",
            "description": (
                "Создаёт таблицу Excel (.xlsx) в рабочей папке "
                "пользователя. Используй для таблиц, списков с "
                "колонками, простых расчётов в виде таблицы."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {
                        "type": "string",
                        "description": "Имя файла, например data.xlsx"
                    },
                    "sheet_title": {
                        "type": "string",
                        "description": "Название листа"
                    },
                    "rows": {
                        "type": "array",
                        "description": (
                            "Строки таблицы. Каждая строка — "
                            "список значений одной строки, первая "
                            "строка обычно заголовки колонок."
                        ),
                        "items": {
                            "type": "array",
                            "items": {}
                        }
                    }
                },
                "required": ["filename", "rows"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_pptx",
            "description": (
                "Создаёт презентацию PowerPoint (.pptx) в рабочей "
                "папке пользователя. Используй для слайдов, "
                "презентаций, докладов. Поддерживает цвет фона и "
                "цвет текста — цвета указывай в формате HEX без "
                "решётки, например FF0000 для красного. Если фон "
                "тёмный или насыщенный, обязательно задай светлый "
                "цвет текста (title_color и bullet_color), иначе "
                "текст будет не прочитать. Картинки на слайды берутся "
                "только из папки workspace: имена файлов бери из "
                "list_workspace_files, не придумывай их."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {
                        "type": "string",
                        "description": "Имя файла, например slides.pptx"
                    },
                    "background_color": {
                        "type": "string",
                        "description": (
                            "Цвет фона по умолчанию для всех "
                            "слайдов, HEX без решётки, "
                            "например 1F1F1F. Необязательно."
                        )
                    },
                    "slides": {
                        "type": "array",
                        "description": "Список слайдов",
                        "items": {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string"},
                                "bullets": {
                                    "type": "array",
                                    "items": {"type": "string"}
                                },
                                "title_color": {
                                    "type": "string",
                                    "description": (
                                        "Цвет заголовка, HEX без "
                                        "решётки. Необязательно."
                                    )
                                },
                                "bullet_color": {
                                    "type": "string",
                                    "description": (
                                        "Цвет текста пунктов, HEX "
                                        "без решётки. Необязательно."
                                    )
                                },
                                "bg_color": {
                                    "type": "string",
                                    "description": (
                                        "Свой цвет фона для этого "
                                        "конкретного слайда, "
                                        "переопределяет "
                                        "background_color. "
                                        "Необязательно."
                                    )
                                },
                                "font_size": {
                                    "type": "number",
                                    "description": (
                                        "Размер шрифта пунктов в "
                                        "пунктах (pt). Необязательно."
                                    )
                                },
                                "image": {
                                    "type": "string",
                                    "description": (
                                        "Имя файла картинки из папки "
                                        "workspace, например "
                                        "cat.png или photos/cat.jpg. "
                                        "Необязательно."
                                    )
                                },
                                "image_position": {
                                    "type": "string",
                                    "enum": [
                                        "right", "left", "bottom", "full"
                                    ],
                                    "description": (
                                        "Где разместить картинку: "
                                        "right — справа от текста "
                                        "(по умолчанию), left — слева, "
                                        "bottom — под текстом, full — "
                                        "на весь слайд позади текста."
                                    )
                                }
                            }
                        }
                    }
                },
                "required": ["filename", "slides"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "write_python_file",
            "description": (
                "Сохраняет Python-код в файл в рабочей папке "
                "пользователя. Файл только сохраняется, но НЕ "
                "запускается."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {
                        "type": "string",
                        "description": "Имя файла, например script.py"
                    },
                    "code": {
                        "type": "string",
                        "description": "Полный код файла"
                    }
                },
                "required": ["filename", "code"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "draft_skill",
            "description": (
                "Сохраняет предложенный код НОВОГО инструмента для "
                "самого себя как черновик в отдельной папке. "
                "Черновик не подключается и не выполняется "
                "автоматически — только сохраняется, чтобы "
                "пользователь мог его просмотреть и подключить "
                "вручную. Используй, когда для задачи не хватает "
                "существующего инструмента и стоит предложить новый."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {
                        "type": "string",
                        "description": "Имя файла черновика"
                    },
                    "code": {
                        "type": "string",
                        "description": "Код предлагаемого инструмента"
                    },
                    "description": {
                        "type": "string",
                        "description": "Для чего нужен этот инструмент"
                    }
                },
                "required": ["filename", "code", "description"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_workspace_files",
            "description": (
                "Показывает, какие файлы лежат в рабочей папке "
                "workspace (только чтение). Вызывай перед вставкой "
                "картинки, чтобы узнать точные имена файлов, или "
                "когда пользователь спрашивает, что у него есть."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "subfolder": {
                        "type": "string",
                        "description": (
                            "Подпапка внутри workspace. "
                            "Необязательно."
                        )
                    },
                    "only_images": {
                        "type": "boolean",
                        "description": (
                            "true — показать только картинки."
                        )
                    }
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "add_image_to_pptx",
            "description": (
                "Вставляет картинку из workspace на слайд УЖЕ "
                "СУЩЕСТВУЮЩЕЙ презентации, не пересоздавая её. "
                "Прежняя версия презентации автоматически "
                "сохраняется в workspace/_backup. Используй, когда "
                "просят добавить или заменить картинку в готовой "
                "презентации."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {
                        "type": "string",
                        "description": "Имя презентации, например slides.pptx"
                    },
                    "slide_number": {
                        "type": "integer",
                        "description": "Номер слайда, начиная с 1"
                    },
                    "image": {
                        "type": "string",
                        "description": (
                            "Имя файла картинки в workspace"
                        )
                    },
                    "position": {
                        "type": "string",
                        "enum": ["right", "left", "bottom", "full"],
                        "description": (
                            "right — справа от текста (по умолчанию), "
                            "left — слева, bottom — под текстом, "
                            "full — на весь слайд позади текста."
                        )
                    },
                    "replace_existing": {
                        "type": "boolean",
                        "description": (
                            "true — заменить картинку, которая уже "
                            "есть на этом слайде."
                        )
                    }
                },
                "required": ["filename", "slide_number", "image"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "add_image_to_docx",
            "description": (
                "Вставляет картинку из workspace в УЖЕ СУЩЕСТВУЮЩИЙ "
                "документ Word, не пересоздавая его. Прежняя версия "
                "документа автоматически сохраняется в "
                "workspace/_backup. Используй, когда просят добавить "
                "картинку в готовый документ."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {
                        "type": "string",
                        "description": "Имя документа, например report.docx"
                    },
                    "image": {
                        "type": "string",
                        "description": "Имя файла картинки в workspace"
                    },
                    "position": {
                        "type": "string",
                        "enum": ["start", "end"],
                        "description": (
                            "start — в начало документа, end — в "
                            "конец (по умолчанию). Игнорируется, если "
                            "указан after_text."
                        )
                    },
                    "after_text": {
                        "type": "string",
                        "description": (
                            "Часть текста абзаца, после которого "
                            "нужно вставить картинку. Необязательно."
                        )
                    },
                    "caption": {
                        "type": "string",
                        "description": "Подпись под картинкой. Необязательно."
                    },
                    "width_cm": {
                        "type": "number",
                        "description": (
                            "Ширина картинки в сантиметрах. "
                            "Необязательно: по умолчанию подбирается "
                            "автоматически."
                        )
                    }
                },
                "required": ["filename", "image"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "rename_workspace_file",
            "description": (
                "Переименовывает файл внутри рабочей папки workspace. "
                "Расширение должно остаться тем же, существующий файл "
                "не заменяется. Содержимое файла не меняется — это не "
                "способ создать новый файл с новым содержимым."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {
                        "type": "string",
                        "description": "Текущее имя файла в workspace"
                    },
                    "new_name": {
                        "type": "string",
                        "description": (
                            "Новое имя. Если расширение не указано, "
                            "останется прежнее."
                        )
                    }
                },
                "required": ["filename", "new_name"]
            }
        }
    }
]

# Параметр overwrite нужен всем инструментам, которые создают файл.
# Описываем его один раз и добавляем во все четыре схемы.
OVERWRITE_PROPERTY = {
    "type": "boolean",
    "description": (
        "true — заменить уже существующий файл (старая версия "
        "автоматически сохранится в workspace/_backup). Ставь true "
        "ТОЛЬКО если в задаче явно разрешена перезапись."
    )
}

for _tool in TOOLS:
    if _tool["function"]["name"] in (
        "create_docx", "create_xlsx", "create_pptx", "write_python_file"
    ):
        _tool["function"]["parameters"]["properties"]["overwrite"] = (
            OVERWRITE_PROPERTY
        )

TOOL_FUNCTIONS = {
    "web_search": lambda args: web_search(
        args.get("query", "")
    ),
    "create_docx": lambda args: create_docx(
        args.get("filename", ""),
        args.get("title", ""),
        args.get("content", ""),
        bool(args.get("overwrite", False))
    ),
    "create_xlsx": lambda args: create_xlsx(
        args.get("filename", ""),
        args.get("sheet_title", ""),
        args.get("rows", []),
        bool(args.get("overwrite", False))
    ),
    "create_pptx": lambda args: create_pptx(
        args.get("filename", ""),
        args.get("slides", []),
        args.get("background_color"),
        bool(args.get("overwrite", False))
    ),
    "write_python_file": lambda args: write_python_file(
        args.get("filename", ""),
        args.get("code", ""),
        bool(args.get("overwrite", False))
    ),
    "draft_skill": lambda args: draft_skill(
        args.get("filename", ""),
        args.get("code", ""),
        args.get("description", "")
    ),
    "rename_workspace_file": lambda args: rename_workspace_file(
        args.get("filename", ""),
        args.get("new_name", "")
    ),
    "list_workspace_files": lambda args: list_workspace_files(
        args.get("subfolder", ""),
        bool(args.get("only_images", False))
    ),
    "add_image_to_docx": lambda args: add_image_to_docx(
        args.get("filename", ""),
        args.get("image", ""),
        args.get("position") or "end",
        args.get("after_text") or "",
        args.get("caption") or "",
        args.get("width_cm")
    ),
    "add_image_to_pptx": lambda args: add_image_to_pptx(
        args.get("filename", ""),
        args.get("slide_number", 1),
        args.get("image", ""),
        args.get("position") or "right",
        bool(args.get("replace_existing", False))
    ),
}

# Сколько кругов может сделать агент (qwen3:14b) на одну задачу.
# Защита от зацикливания.
MAX_AGENT_ROUNDS = 5

# Сколько раз за один ответ чат-модель может отдать задачу агенту.
MAX_DELEGATIONS = 3

# Перезапись файла разрешена, только если об этом прямо сказано в задаче
# (например, "перезапись существующего файла разрешена"). "Не" или "без"
# перед словом отменяют разрешение. Проверяет это код, а не модель.
OVERWRITE_PERMISSION = re.compile(
    r"(?<!не )(?<!без )перезапи[сш]", re.IGNORECASE
)
OVERWRITE_DENIAL = re.compile(r"нельзя|запрещ|не разреш", re.IGNORECASE)


def overwrite_allowed(task: str) -> bool:
    return bool(
        OVERWRITE_PERMISSION.search(task)
        and not OVERWRITE_DENIAL.search(task)
    )

# Единственный инструмент чат-модели (qwen3:8b). Это не "настоящий"
# инструмент, а передача задачи агенту. Текст описания важен: именно
# по нему модель решает, когда звать агента, а когда справиться самой.
RUN_AGENT_TOOL = {
    "type": "function",
    "function": {
        "name": "run_agent",
        "description": (
            "Передаёт задачу агенту — исполнителю с инструментами. "
            "Агент умеет: искать информацию в интернете; создавать "
            "файлы Word, Excel, PowerPoint и Python-файлы в папке "
            "workspace; вставлять картинки из workspace в презентации "
            "и документы; смотреть список файлов и переименовывать "
            "файлы в workspace. Это "
            "ЕДИНСТВЕННЫЙ способ что-то реально сделать: сам ты не "
            "можешь ни искать в интернете, ни создавать файлы.\n\n"
            "Вызывай ТОЛЬКО когда для ответа действительно нужно одно "
            "из этих действий. НЕ вызывай для: обычного разговора, "
            "объяснений, советов, мнений, шуток, вопросов, на которые "
            "ты можешь ответить сам или по памяти о пользователе, "
            "перевода и правки текста, который пользователь просто "
            "хочет прочитать в чате, обсуждения планов. Всё, что "
            "можешь сделать сам, делай сам.\n\n"
            "В задачу включай только то, о чём пользователь просил: не "
            "добавляй запасные варианты, другие форматы и лишние "
            "действия (например, поиск картинки в интернете, если "
            "её нет в workspace). Если пользователь разрешил заменить "
            "уже существующий файл, прямо напиши в задаче: "
            "«перезапись существующего файла разрешена».\n\n"
            "Формат файла называй точно так, как сказал "
            "пользователь (Word, PowerPoint, Excel), и не "
            "подменяй один другим. Расширение картинки не "
            "выдумывай: если пользователь его не назвал, пиши "
            "имя как есть.\n\n"
            "Агент не видит переписку и ничего не знает о "
            "пользователе. Поэтому в task опиши задачу полностью и "
            "самодостаточно: что сделать, точные имена файлов, нужный "
            "текст или подробный план содержимого, цвета, расположение "
            "картинок, язык — всё важное из разговора. Если "
            "пользователь уже дал текст, передай его дословно. Если "
            "без важной детали задачу не выполнить — сначала спроси "
            "пользователя, а не отправляй агенту догадки."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": (
                        "Полное самодостаточное описание задачи для "
                        "агента, на русском языке."
                    )
                }
            },
            "required": ["task"]
        }
    }
}


class OllamaProvider(AIProvider):

    def chat(self, messages: list[dict]) -> str:
        """
        Каждое сообщение сначала получает чат-модель (qwen3:8b).
        Если она сама решает, что нужно действие, она вызывает
        run_agent и пишет агенту задачу. Результат возвращается ей,
        и именно она отвечает пользователю.
        """
        working_messages = list(messages)

        for _ in range(MAX_DELEGATIONS):
            result = self._request(
                working_messages,
                model=OLLAMA_CHAT_MODEL,
                tools=[RUN_AGENT_TOOL],
                temperature=CHAT_TEMPERATURE,
                num_ctx=CHAT_NUM_CTX
            )
            message = result["message"]

            tool_calls = message.get("tool_calls")

            if not tool_calls:
                return message["content"]

            working_messages.append(message)

            for call in tool_calls:
                working_messages.append({
                    "role": "tool",
                    "content": self._delegate(call)
                })

        # Слишком много передач подряд — просим ответить без агента.
        result = self._request(
            working_messages,
            model=OLLAMA_CHAT_MODEL,
            tools=None,
            temperature=CHAT_TEMPERATURE,
            num_ctx=CHAT_NUM_CTX
        )
        return result["message"]["content"]

    def _delegate(self, call: dict) -> str:
        function = call.get("function", {})
        name = function.get("name")
        arguments = function.get("arguments", {})

        if name != "run_agent":
            return (
                f"Неизвестный инструмент: {name}. Тебе доступен только "
                f"run_agent — передай задачу агенту через него."
            )

        task = str(arguments.get("task", "")).strip()

        if not task:
            return "Задача пустая. Опиши, что именно должен сделать агент."

        emit(
            "agent",
            f"Задача для агента ({OLLAMA_AGENT_MODEL}):\n{task}\n",
            task=task
        )
        emit("status", "agent")

        try:
            report = self._run_agent(task)
        except Exception as error:
            emit("agent", f"Агент не справился: {error}", level="error")
            emit("status", "thinking")

            return f"Агент не смог выполнить задачу: {error}"

        emit("agent", f"Отчёт агента: {report[:800]}\n", report=report)
        emit("status", "thinking")

        return report

    def _run_agent(self, task: str) -> str:
        """
        Агент (qwen3:14b) видит только свой системный промпт и задачу,
        написанную чат-моделью, а не всю переписку с пользователем.
        """
        now = datetime.now().strftime("%d.%m.%Y, %H:%M")

        working_messages = [
            {
                "role": "system",
                "content": (
                    f"{load_prompt('agent')}\n\n"
                    f"Текущие дата и время: {now}."
                )
            },
            {"role": "user", "content": task}
        ]

        allow_overwrite = overwrite_allowed(task)
        tool_log = []

        for _ in range(MAX_AGENT_ROUNDS):
            result = self._request(
                working_messages,
                model=OLLAMA_AGENT_MODEL,
                tools=TOOLS,
                temperature=AGENT_TEMPERATURE,
                num_ctx=AGENT_NUM_CTX
            )
            message = result["message"]

            tool_calls = message.get("tool_calls")

            if not tool_calls:
                return self._compose_report(message, tool_log)

            working_messages.append(message)

            for call in tool_calls:
                tool_result = self._run_tool(call, allow_overwrite)

                tool_log.append((
                    call.get("function", {}).get("name"),
                    tool_result
                ))

                working_messages.append({
                    "role": "tool",
                    "content": tool_result
                })

        # Если агент зациклился на вызовах инструментов — просим
        # итоговый отчёт без права снова вызвать инструмент.
        result = self._request(
            working_messages,
            model=OLLAMA_AGENT_MODEL,
            tools=None,
            temperature=AGENT_TEMPERATURE,
            num_ctx=AGENT_NUM_CTX
        )
        return self._compose_report(result["message"], tool_log)

    def _compose_report(self, message: dict, tool_log: list) -> str:
        """
        Отчёт агента для чат-модели: его текст плюс результаты
        инструментов. Результаты — это факты: даже если агент ничего не
        написал или приукрасил, чат-модель знает, что было на самом деле.
        """
        text = (message.get("content") or "").strip()

        if not text:
            thinking = (message.get("thinking") or "").strip()

            emit(
                "agent",
                f"Агент вернул пустой текст. Поля ответа: "
                f"{sorted(message.keys())}"
                + (f". Мысли модели: {thinking[:200]}" if thinking else ""),
                level="warning"
            )

            text = "Агент не написал текстовый отчёт."

        if not tool_log:
            return text

        lines = [
            f"- {name}: {str(result)[:300]}"
            for name, result in tool_log
        ]

        return (
            f"{text}\n\nРезультаты вызовов инструментов "
            f"(это факты, опирайся на них):\n" + "\n".join(lines)
        )

    def _run_tool(self, call: dict, allow_overwrite: bool = False) -> str:
        function = call.get("function", {})
        name = function.get("name")
        arguments = function.get("arguments", {})

        if (
            isinstance(arguments, dict)
            and arguments.get("overwrite")
            and not allow_overwrite
        ):
            emit(
                "agent",
                "В задаче нет разрешения на перезапись — "
                "игнорирую overwrite=true.",
                level="warning"
            )
            arguments = {**arguments, "overwrite": False}

        handler = TOOL_FUNCTIONS.get(name)

        if handler is None:
            return f"Неизвестный инструмент: {name}"

        emit(
            "tools",
            f"Вызываю: {name}({arguments})",
            name=name,
            arguments=arguments
        )

        try:
            return handler(arguments)
        except Exception as error:
            return f"Ошибка при выполнении {name}: {error}"

    def _request(
        self,
        messages: list[dict],
        model: str,
        tools: list = None,
        temperature: float = None,
        num_ctx: int = None
    ) -> dict:
        data = {
            "model": model,
            "messages": messages,
            "stream": False
        }

        if tools:
            data["tools"] = tools

        options = {}

        if temperature is not None:
            options["temperature"] = temperature

        if num_ctx is not None:
            options["num_ctx"] = num_ctx

        if options:
            data["options"] = options

        request = urllib.request.Request(
            f"{OLLAMA_URL}/api/chat",
            data=json.dumps(data).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST"
        )

        with urllib.request.urlopen(request, timeout=OLLAMA_TIMEOUT) as response:
            result = json.loads(response.read().decode("utf-8"))

        self._report_usage(model, result, num_ctx)

        return result

    def _report_usage(self, model: str, result: dict, num_ctx: int):
        """Показывает, сколько места в окне контекста заняла работа."""
        prompt_tokens = result.get("prompt_eval_count")
        answer_tokens = result.get("eval_count") or 0

        if not SHOW_TOKEN_USAGE or prompt_tokens is None:
            return

        line = (
            f"{model}: запрос {prompt_tokens} ток., "
            f"ответ {answer_tokens} ток."
        )

        if num_ctx:
            line += f" (окно {num_ctx})"

        emit(
            "ollama",
            line,
            level="debug",
            model=model,
            prompt_tokens=prompt_tokens,
            answer_tokens=answer_tokens
        )

        if num_ctx and prompt_tokens + answer_tokens >= num_ctx * 0.9:
            emit(
                "ollama",
                "ВНИМАНИЕ: окно контекста почти заполнено, "
                "ответ может обрезаться. Увеличь *_NUM_CTX в config.py.",
                level="warning"
            )
