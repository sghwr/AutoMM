"""AutoMM 远端计算和 GitHub 中转适配器。"""

from .base import AdapterError, RemoteAdapter
from .service import get_adapter

__all__ = ["AdapterError", "RemoteAdapter", "get_adapter"]
