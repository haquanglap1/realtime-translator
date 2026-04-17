"""Thread-safe ring buffer for audio chunks and metadata."""

from __future__ import annotations

import threading
from collections import deque
from typing import Any, Optional

import numpy as np


class RingBuffer:
    def __init__(self, maxsize: int = 200):
        self._buf: deque[Any] = deque(maxlen=maxsize)
        self._lock = threading.Lock()
        self._not_empty = threading.Event()

    def put(self, chunk: Any) -> None:
        with self._lock:
            if isinstance(chunk, np.ndarray):
                self._buf.append(chunk.copy())
            else:
                self._buf.append(chunk)
        self._not_empty.set()

    def get(self, timeout: float = 0.1) -> Optional[Any]:
        self._not_empty.wait(timeout=timeout)
        with self._lock:
            if self._buf:
                item = self._buf.popleft()
                if not self._buf:
                    self._not_empty.clear()
                return item
        return None

    def get_all(self) -> list[Any]:
        with self._lock:
            items = list(self._buf)
            self._buf.clear()
            self._not_empty.clear()
        return items

    def clear(self) -> None:
        with self._lock:
            self._buf.clear()
            self._not_empty.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._buf)
