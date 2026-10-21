"""Check the generator connection before a run.

    docker compose run --rm ml python -m src.generation.check

Prints the server host (never the cookie), the models it serves, and one
short test reply. Exit 2 if the OOD session has expired.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib.parse import urlparse

import yaml
from dotenv import load_dotenv

from src.generation.llm import SessionExpired, build_chat_model, invoke_with_retry, list_models


def main() -> int:
    load_dotenv()
    settings = yaml.safe_load(Path("config/config.yaml").read_text(encoding="utf-8"))["generation"]
    print("server:", urlparse(os.environ.get(settings["base_url_env"], "")).netloc or "(not set)")
    try:
        models = list_models(settings, os.environ)
        print("models:", ", ".join(models))
        if settings["model"] not in models:
            print(f"configured model {settings['model']!r} is not served")
            return 1
        reply = invoke_with_retry(build_chat_model(settings, os.environ),
                                  [("human", "Reply with exactly five words about annual leave.")], retries=0)
    except SessionExpired as error:
        print(error)
        return 2
    print(f"reply: {reply.text!r} ({reply.finish_reason}, {reply.completion_tokens} tokens)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
