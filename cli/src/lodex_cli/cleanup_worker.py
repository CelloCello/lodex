"""One restricted cleanup invocation, with inputs from the management pipe.

Runs inside the selected sandbox, replacing inherited config-set environment
values before exec. No secret values are staged to files or argv. No listening
endpoint or general command delegation service is provided.
"""

from __future__ import annotations

import json
import os
import sys


def main() -> int:
    try:
        data = sys.stdin.buffer.read(1024 * 1024 + 1)
        if len(data) > 1024 * 1024:
            raise ValueError
        payload = json.loads(data)
        argv, environment = payload["argv"], payload["environment"]
        if (
            not isinstance(argv, list)
            or not argv
            or any(not isinstance(arg, str) or not arg or "\x00" in arg for arg in argv)
            or not isinstance(environment, dict)
            or any(
                not isinstance(key, str)
                or not key
                or "=" in key
                or "\x00" in key
                or not isinstance(value, str)
                or "\x00" in value
                for key, value in environment.items()
            )
        ):
            raise ValueError
        os.execvpe(argv[0], argv, environment)
    except (KeyError, TypeError, ValueError, RecursionError, OSError):
        print("Cannot execute the restricted cleanup inputs", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
