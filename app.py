import json
import os
import random
from typing import Dict, List, Optional, Tuple

import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, request

from content import MAIN_MENU, MODULE_BUTTONS, MODULE_MENU, MODULE_ORDER, MODULES, PROJECT_ABOUT, RESOURCE_URL
from storage import (
    add_points,
    clear_state,
    ensure_user,
    get_progress,
    get_state,
    init_db,
    mark_viewed,
    save_quiz_result,
    save_reflection,
    set_state,
)

load_dotenv()

VK_GROUP_TOKEN = os.getenv("VK_GROUP_TOKEN", "")
VK_CONFIRMATION_TOKEN = os.getenv("VK_CONFIRMATION_TOKEN", "")
VK_SECRET_KEY = os.getenv("VK_SECRET_KEY", "")
VK_API_VERSION = os.getenv("VK_API_VERSION", "5.199")

app = Flask(__name__)
init_db()

TEXT_TO_MODULE = {
    "гексагон": "hexagon",
    "пазл-лабиринт": "puzzle_labyrinth",
    "зеркальный лабиринт": "mirror_labyrinth",
    "кубический вызов": "cubic_challenge",
    "деревянный замок": "wooden_castle",
}


def normalize(text: Optional[str]) -> str:
    return (text or "").strip().lower()


def build_keyboard(rows: List[List[str]], one_time: bool = False) -> str:
    keyboard = {"one_time": one_time, "buttons": []}
    for row in rows:
        buttons = []
        for title in row:
            buttons.append(
                {
                    "action": {
                        "type": "text",
                        "label": title,
                    },
                    "color": "primary",
                }
            )
        keyboard["buttons"].append(buttons)
    return json.dumps(keyboard, ensure_ascii=False)


def send_message(peer_id: int, message: str, keyboard_rows: Optional[List[List[str]]] = None) -> None:
    payload = {
        "peer_id": peer_id,
        "random_id": random.randint(1, 2_147_483_647),
        "message": message,
        "access_token": VK_GROUP_TOKEN,
        "v": VK_API_VERSION,
    }
    if keyboard_rows:
        payload["keyboard"] = build_keyboard(keyboard_rows)

    response = requests.post("https://api.vk.ru/method/messages.send", data=payload, timeout=20)
    response.raise_for_status()

    try:
        data = response.json()
        if "error" in data:
            raise RuntimeError(f"VK API error: {data['error']}")
    except ValueError:
        pass


def main_menu_message(first_name: str = "") -> str:
    prefix = f"{first_name}, " if first_name else ""
    return (
        f"{prefix}добро пожаловать в бот образовательного ресурса.\n\n"
        "Здесь можно выбрать модуль, пройти мини-тест, оставить рефлексию и посмотреть свой прогресс.\n\n"
        "Нажми «Модули», чтобы начать."
    )


def modules_message() -> str:
    lines = ["Доступные модули:"]
    for key in MODULE_ORDER:
        module = MODULES[key]
        lines.append(f"• {module['title']} — {module['short']}")
    return "\n".join(lines)


def module_card(module_key: str) -> str:
    module = MODULES[module_key]
    return (
        f"Модуль: {module['title']}\n\n"
        f"Кратко: {module['short']}\n\n"
        f"{module['tips']}\n\n"
        f"Ресурс: {RESOURCE_URL}\n\n"
        "Выбери действие на клавиатуре ниже."
    )


def recommend_next_module(module_rows) -> Optional[str]:
    done = {row["module_key"] for row in module_rows if row["completed_at"]}
    for key in MODULE_ORDER:
        if key not in done:
            return MODULES[key]["title"]
    return None


def progress_message(user_id: int) -> str:
    user, modules = get_progress(user_id)
    points = user["points"] if user else 0
    by_key = {row["module_key"]: row for row in modules}
    lines = [f"Твой прогресс\n\nБаллы: {points}"]
    completed = 0

    for key in MODULE_ORDER:
        module = MODULES[key]
        row = by_key.get(key)
        viewed = "✅" if row and row["viewed"] else "⬜"
        quiz = "✅" if row and row["quiz_passed"] else "⬜"
        refl = "✅" if row and row["reflection"] else "⬜"
        if row and row["completed_at"]:
            completed += 1
        lines.append(f"\n{module['title']}:\n• изучение: {viewed}\n• мини-тест: {quiz}\n• рефлексия: {refl}")

    lines.append(f"\nЗавершено модулей: {completed} из {len(MODULE_ORDER)}")
    next_module = recommend_next_module(modules)
    if next_module:
        lines.append(f"Рекомендуемый следующий модуль: {next_module}")
    else:
        lines.append("Отлично! Все модули завершены.")
    return "\n".join(lines)


def about_module_goal(module_key: str) -> str:
    module = MODULES[module_key]
    return f"Цель модуля «{module['title']}»:\n\n{module['goal']}"


def about_module_task(module_key: str) -> str:
    module = MODULES[module_key]
    return f"Задание по модулю «{module['title']}»:\n\n{module['task']}"


def quiz_intro(module_key: str) -> str:
    module = MODULES[module_key]
    return (
        f"Мини-тест по модулю «{module['title']}».\n"
        "Ответь на 3 вопроса. За успешное прохождение начисляются баллы."
    )


def render_question(module_key: str, index: int) -> Tuple[str, List[List[str]]]:
    question = MODULES[module_key]["quiz"][index]
    options = question["options"]

    text = (
        f"Вопрос {index + 1} из {len(MODULES[module_key]['quiz'])}:\n\n"
        f"{question['question']}\n\n"
        f"1. {options[0]}\n"
        f"2. {options[1]}\n"
        f"3. {options[2]}"
    )

    rows = [["1"], ["2"], ["3"], ["Главное меню"]]
    return text, rows


def parse_payload(payload: str) -> Dict[str, str]:
    data = {}
    for part in payload.split("|"):
        if "=" in part:
            key, value = part.split("=", 1)
            data[key] = value
    return data


def universal_reply(peer_id: int, text: str, first_name: str, user_id: int) -> bool:
    msg = normalize(text)

    if msg in {"начать", "старт", "start", "главное меню"}:
        clear_state(user_id)
        send_message(peer_id, main_menu_message(first_name), MAIN_MENU)
        return True

    if msg == "о проекте":
        send_message(peer_id, PROJECT_ABOUT, MAIN_MENU)
        return True

    if msg == "модули":
        send_message(peer_id, modules_message(), MODULE_BUTTONS)
        return True

    if msg == "мой прогресс":
        send_message(peer_id, progress_message(user_id), MAIN_MENU)
        return True

    if msg == "помощь":
        send_message(
            peer_id,
            "Команды через кнопки:\n"
            "• «Модули» — список конструкторов;\n"
            "• «Мини-тест» — проверка освоения;\n"
            "• «Рефлексия» — краткий вывод ученика;\n"
            "• «Мой прогресс» — просмотр результатов.\n\n"
            "Можно писать и обычным текстом: «старт», «модули», «мой прогресс».",
            MAIN_MENU,
        )
        return True

    if msg == "открыть ресурс":
        send_message(peer_id, f"Открой образовательный ресурс: {RESOURCE_URL}", MODULE_MENU)
        return True

    if msg in TEXT_TO_MODULE:
        module_key = TEXT_TO_MODULE[msg]
        first_open = mark_viewed(user_id, module_key)
        if first_open:
            add_points(user_id, 2)
        set_state(user_id, "module", f"module={module_key}")
        send_message(peer_id, module_card(module_key), MODULE_MENU)
        return True

    return False


def handle_state(user_id: int, peer_id: int, text: str) -> bool:
    state_row = get_state(user_id)
    if not state_row:
        return False

    state = state_row["state"]
    payload = parse_payload(state_row["payload"])
    msg = text.strip()

    if state == "module":
        module_key = payload.get("module")
        if not module_key:
            return False

        command = normalize(msg)

        if command == "цель":
            send_message(peer_id, about_module_goal(module_key), MODULE_MENU)
            return True

        if command == "задание":
            send_message(peer_id, about_module_task(module_key), MODULE_MENU)
            return True

        if command == "мини-тест":
            intro = quiz_intro(module_key)
            question_text, rows = render_question(module_key, 0)
            send_message(peer_id, f"{intro}\n\n{question_text}", rows)
            set_state(user_id, "quiz", f"module={module_key}|index=0|score=0")
            return True

        if command == "рефлексия":
            set_state(user_id, "reflection", f"module={module_key}")
            send_message(
                peer_id,
                f"Напиши 2–4 предложения: что было самым сложным или самым интересным в модуле «{MODULES[module_key]['title']}»?",
                [["Главное меню"]],
            )
            return True

        return False

    if state == "quiz":
        module_key = payload.get("module")
        index = int(payload.get("index", 0))
        score = int(payload.get("score", 0))

        if not module_key:
            return False

        if index >= len(MODULES[module_key]["quiz"]):
            set_state(user_id, "module", f"module={module_key}")
            send_message(peer_id, "Тест уже завершён. Выбери следующее действие.", MODULE_MENU)
            return True

        current = MODULES[module_key]["quiz"][index]
        options = current["options"]

        answer_map = {
            "1": options[0],
            "2": options[1],
            "3": options[2],
        }

        selected_answer = answer_map.get(msg.strip())
        if selected_answer is None:
            send_message(peer_id, "Пожалуйста, выбери один из вариантов: 1, 2 или 3.", [["1"], ["2"], ["3"], ["Главное меню"]])
            return True

        if selected_answer == current["correct"]:
            score += 1

        index += 1

        if index >= len(MODULES[module_key]["quiz"]):
            total = len(MODULES[module_key]["quiz"])
            first_pass = save_quiz_result(user_id, module_key, score, total)
            if first_pass:
                add_points(user_id, 5)

            send_message(
                peer_id,
                f"Тест завершен. Результат: {score}/{total}.\n\n"
                "Чтобы модуль считался завершенным, осталось написать рефлексию.",
                MODULE_MENU,
            )
            set_state(user_id, "module", f"module={module_key}")
            return True

        question_text, rows = render_question(module_key, index)
        send_message(peer_id, question_text, rows)
        set_state(user_id, "quiz", f"module={module_key}|index={index}|score={score}")
        return True

    if state == "reflection":
        module_key = payload.get("module")
        if not module_key:
            return False

        first_reflection = save_reflection(user_id, module_key, msg)
        if first_reflection:
            add_points(user_id, 3)

        set_state(user_id, "module", f"module={module_key}")
        send_message(
            peer_id,
            f"Спасибо! Рефлексия по модулю «{MODULES[module_key]['title']}» сохранена.\n\n"
            "Теперь можешь открыть следующий модуль или посмотреть прогресс.",
            MODULE_MENU,
        )
        return True

    return False


@app.get("/")
def index():
    return jsonify({"status": "ok", "service": "vk-education-bot"})


@app.post("/")
def vk_callback():
    data = request.get_json(force=True, silent=True) or {}

    if VK_SECRET_KEY and data.get("secret") and data.get("secret") != VK_SECRET_KEY:
        return "forbidden", 403

    if data.get("type") == "confirmation":
        return VK_CONFIRMATION_TOKEN

    if data.get("type") == "message_new":
        obj = data.get("object", {})
        message = obj.get("message", {})
        peer_id = message.get("peer_id")
        user_id = message.get("from_id")
        text = message.get("text", "")

        if not peer_id or not user_id:
            return "ok"

        first_name = ""
        last_name = ""
        ensure_user(user_id, first_name, last_name)

        try:
            if not universal_reply(peer_id, text, first_name, user_id):
                if not handle_state(user_id, peer_id, text):
                    send_message(
                        peer_id,
                        "Я пока не понял сообщение. Нажми «Главное меню» или «Модули», чтобы продолжить.",
                        MAIN_MENU,
                    )
        except Exception as e:
            print(f"ERROR while handling message: {e}")
            try:
                send_message(
                    peer_id,
                    "Произошла небольшая ошибка. Нажми «Главное меню» и попробуй ещё раз.",
                    MAIN_MENU,
                )
            except Exception as inner_e:
                print(f"ERROR while sending fallback message: {inner_e}")

        return "ok"

    return "ok"


if __name__ == "__main__":
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    app.run(host=host, port=port, debug=True)
