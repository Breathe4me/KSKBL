"""Future provider contract only; this release makes no email authorization requests."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class EmailSummary:
    sender: str
    subject: str
    received_time: str
    snippet: str
    importance: str = "Unknown"
    action_required: bool | None = None
    source_url: str = ""


class EmailProvider(Protocol):
    def connect(self): ...
    def disconnect(self): ...
    def test_connection(self): ...
    def list_messages(self, limit=20): ...
    def get_message(self, message_id): ...
    def get_unread_count(self): ...
