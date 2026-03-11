from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol

from src.notify_telegram import TelegramNotifier, build_notifier


class Notifier(Protocol):
    def send(self, message: str) -> None: ...


@dataclass
class TelegramNotifierAdapter:
    notifier: TelegramNotifier

    def send(self, message: str) -> None:
        self.notifier.send(message)


def build_telegram_notifier(token_env: str, chat_id_env: str) -> Optional[Notifier]:
    notifier = build_notifier(token_env, chat_id_env)
    if not notifier:
        return None
    return TelegramNotifierAdapter(notifier=notifier)

