import threading


class DataModel:
    """Thread-safe nested dict addressed by JSON-pointer-style paths ("/trains/E/0")."""

    def __init__(self, data=None):
        self._data = data if data is not None else {}
        self._lock = threading.Lock()

    @staticmethod
    def _parts(path):
        return [p for p in path.split("/") if p != ""]

    def get(self, path, default=None):
        with self._lock:
            node = self._data
            for part in self._parts(path):
                if isinstance(node, dict) and part in node:
                    node = node[part]
                elif isinstance(node, list) and part.isdigit() and int(part) < len(node):
                    node = node[int(part)]
                else:
                    return default
            return node

    def set(self, path, value):
        parts = self._parts(path)
        with self._lock:
            if not parts:
                self._data = value
                return
            node = self._data
            for part in parts[:-1]:
                node = node.setdefault(part, {})
            node[parts[-1]] = value
