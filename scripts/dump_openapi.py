"""Write the M5 API's OpenAPI schema for the frontend (M6 plan D6, Task 2).

    docker compose run --rm ml python -m scripts.dump_openapi
    cd frontend && npm run gen:types

The app is built around a stub engine: route handlers only touch the engine
when a request arrives, so no models, database or generator are needed. The
SSE event payloads are not in OpenAPI; frontend/src/api/events.ts types them.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from src.api.app import create_app

OUTPUT = "frontend/src/api/openapi.json"


def build_schema() -> dict:
    stub = SimpleNamespace(config={"api": {"cors_origins": []}})
    # A JSON round trip so the dict matches what is read back from disk.
    return json.loads(json.dumps(create_app(stub).openapi()))


def main() -> None:
    path = Path(OUTPUT)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(build_schema(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
