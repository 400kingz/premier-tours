from __future__ import annotations

from functools import lru_cache

from app.db import TourDB
from app.queue import RenderQueue
from app.services.storage import MediaStore


@lru_cache
def get_db() -> TourDB:
    return TourDB()


@lru_cache
def get_queue() -> RenderQueue:
    return RenderQueue()


@lru_cache
def get_store() -> MediaStore:
    return MediaStore()
