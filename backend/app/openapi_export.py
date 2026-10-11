"""Write the API's OpenAPI schema as JSON, for the web app's generated types (`make types`).

    python -m app.openapi_export [OUTPUT_PATH]     # default: stdout

Needs no environment: the schema does not depend on settings values, so placeholder settings
are used and nothing connects to Postgres or Redis (the app lifespan never runs).
"""

import json
import sys
from pathlib import Path
from typing import Any

from app.config import Settings
from app.main import create_app


def openapi_schema() -> dict[str, Any]:
    # model_construct skips validation: only fields read while building the app are set, and no
    # real secret is involved.
    settings = Settings.model_construct(log_level="WARNING", log_json=True, cors_origins=[])
    return create_app(settings).openapi()


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    text = json.dumps(openapi_schema(), indent=2, ensure_ascii=False) + "\n"
    if args:
        Path(args[0]).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
