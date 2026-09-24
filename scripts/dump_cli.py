"""Write docs/cli-reference.json from the live sfvf parser."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from app.paths import APP_ROOT
    from app.serve import cli_reference

    target = APP_ROOT / "docs" / "cli-reference.json"
    text = json.dumps(cli_reference(), indent=2, sort_keys=True) + "\n"
    target.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
