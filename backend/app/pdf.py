"""PyMuPDF is not thread-safe, even across documents: one PDF at a time per process. Workers do
PDF work in threads (the event loop and arq's health check stay responsive), each holding this
lock; re-entrant, so code that already holds it may call code that takes it again."""

import threading

PYMUPDF_LOCK = threading.RLock()
