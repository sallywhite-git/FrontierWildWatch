import os
from typing import Optional

import requests


class TelegramNotifier:
    def __init__(self, token: str, chat_id: str) -> None:
        self.token = token
        self.chat_id = chat_id

    def send(self, message: str) -> None:
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": False,
        }
        response = requests.post(url, json=payload, timeout=20)
        response.raise_for_status()


def build_notifier(token_env: str, chat_id_env: str) -> Optional[TelegramNotifier]:
    token = os.environ.get(token_env)
    chat_id = os.environ.get(chat_id_env)
    if not token or not chat_id:
        return None
    return TelegramNotifier(token, chat_id)
