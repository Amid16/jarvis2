"""
Консольный интерфейс JARVIS.

Вся логика (память, команды, агент, голос) живёт в ядре core/jarvis.py.
Здесь только ввод с клавиатуры и вывод в консоль. Так же устроен любой
другой интерфейс, например окно на PyQt6 (см. docs/UI_INTEGRATION.md).
"""

from config import JARVIS_NAME
from core.events import bus
from core.jarvis import Jarvis


def show_event(event):
    """События, которые консоль показывает пользователю."""
    if event.channel == "note":
        print(f"JARVIS: {event.text}\n")

    elif (
        event.channel == "status"
        and event.text == "thinking"
        and event.data.get("previous") not in ("thinking", "agent")
    ):
        print("\nJARVIS думает...\n")


def listen_from_console(jarvis: Jarvis) -> str:
    jarvis.start_listening()

    print("[STT] Говорите. Нажмите Enter, чтобы закончить запись...")
    input()

    return jarvis.stop_listening()


def main():
    print(f"{JARVIS_NAME} запускается...")
    print("Введите 'exit' для выхода.\n")

    # background_memory=False: анализ диалога для памяти запускаем сами,
    # после ответа и озвучки — так порядок вывода остаётся прежним.
    jarvis = Jarvis(background_memory=False)
    jarvis.preload_voice()

    bus.subscribe(show_event)

    while True:
        user_message = input("Ты: ")

        if user_message.strip().lower() == "голос":
            user_message = listen_from_console(jarvis)

            if not user_message:
                print("JARVIS: Ничего не расслышал.\n")
                continue

            print(f"Ты (голосом): {user_message}")

        if user_message.strip().lower() in ("exit", "выход"):
            jarvis.shutdown()
            print("JARVIS завершает работу.")
            break

        reply = jarvis.handle_message(user_message)

        if reply.kind == "empty":
            continue

        print(f"JARVIS: {reply.text}\n")

        if reply.kind == "chat":
            jarvis.speak(reply.text)

        jarvis.run_pending_analysis()


if __name__ == "__main__":
    main()
