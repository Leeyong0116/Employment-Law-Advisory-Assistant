"""The frontend's TypeScript types come from frontend/src/api/openapi.json (M6 plan D6).

This fails when the API schema changes and the committed JSON was not
regenerated. Fix: run the dump script, then `npm run gen:types` in frontend/.
"""

import json
from pathlib import Path

from scripts.dump_openapi import OUTPUT, build_schema


def test_committed_openapi_is_current():
    committed = json.loads(Path(OUTPUT).read_text(encoding="utf-8"))
    assert committed == build_schema(), (
        "frontend/src/api/openapi.json is stale: run "
        "`docker compose run --rm ml python -m scripts.dump_openapi`, then `cd frontend && npm run gen:types`"
    )


def test_schema_has_the_frontend_contract():
    schemas = build_schema()["components"]["schemas"]
    for name in ("GeneratedAnswer", "Citation", "Abstention", "Provision", "Meta", "ApiError", "AskRequest"):
        assert name in schemas
