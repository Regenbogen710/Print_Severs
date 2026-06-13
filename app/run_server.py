from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
import threading

import uvicorn

from app.config import get_settings


def start_parent_monitor() -> None:
    parent_pid = os.getenv("PRINT_SERVER_PARENT_PID")
    if os.name != "nt" or not parent_pid:
        return

    try:
        pid = int(parent_pid)
    except ValueError:
        return

    def monitor() -> None:
        synchronize = 0x00100000
        infinite = 0xFFFFFFFF
        wait_failed = 0xFFFFFFFF
        kernel32 = ctypes.windll.kernel32

        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel32.WaitForSingleObject.restype = wintypes.DWORD
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL

        handle = kernel32.OpenProcess(synchronize, False, pid)
        if not handle:
            return
        try:
            result = kernel32.WaitForSingleObject(handle, infinite)
        finally:
            kernel32.CloseHandle(handle)
        if result == wait_failed:
            return
        os._exit(0)

    thread = threading.Thread(target=monitor, name="parent-monitor", daemon=True)
    thread.start()


def main() -> None:
    start_parent_monitor()
    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
    )


if __name__ == "__main__":
    main()
