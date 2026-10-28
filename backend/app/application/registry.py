from typing import Optional
from app.application.runtime import JunctionRuntime


class JunctionRegistry:
    def __init__(self):
        self._runtimes: dict[str, JunctionRuntime] = {}

    def register(self, runtime: JunctionRuntime) -> None:
        self._runtimes[runtime.junction_id] = runtime

    def get(self, junction_id: str) -> Optional[JunctionRuntime]:
        return self._runtimes.get(junction_id)

    def list_all(self) -> list[JunctionRuntime]:
        return list(self._runtimes.values())

    def unregister(self, junction_id: str) -> Optional[JunctionRuntime]:
        return self._runtimes.pop(junction_id, None)


registry = JunctionRegistry()
