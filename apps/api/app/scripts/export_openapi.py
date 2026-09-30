"""Print the OpenAPI document (used to generate the web app's TS types)."""

import json
import os
import sys


def main() -> None:
    os.environ.setdefault("ENVIRONMENT", "test")
    from app.main import app

    json.dump(app.openapi(), sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
