"""One request in a foreground process; input is private stdin, never argv."""

from __future__ import annotations

import json
import sys

from lodex_console.actions import Action, execute
from lodex_core.management.common import ManagementError
from lodex_core.management.store import Registry


def main() -> None:
    store: Registry | None = None
    try:
        request = Action.model_validate_json(sys.stdin.read())
        store = Registry(read_only=request.action in ("service.logs", "operation.logs"))
        result = execute(store, request)
        ok = not isinstance(result, dict) or result.get("state") not in (
            "failed",
            "interrupted",
            "unknown",
        )
        response = {"ok": ok, "result": result}
    except ManagementError as exc:
        response = {"ok": False, "error": {"code": exc.code, "message": str(exc)}}
    except Exception:
        # Validation errors and tracebacks can contain submitted secret values.
        response = {
            "ok": False,
            "error": {
                "code": "worker_failed",
                "message": "Operation failed; inspect recorded state",
            },
        }
    finally:
        if store is not None:
            store.close()
    print(json.dumps(response))


if __name__ == "__main__":
    main()
