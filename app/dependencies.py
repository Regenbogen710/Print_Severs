from fastapi import Request

from app.printer import WindowsPrinter
from app.queue_store import QueueStore


def get_store(request: Request) -> QueueStore:
    return request.app.state.store


def get_printer(request: Request) -> WindowsPrinter:
    return request.app.state.printer
