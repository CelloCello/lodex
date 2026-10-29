---
name: lodex-services
description: Start, inspect, read logs and stop Lodex taskenv services across callers. Use for local service lifecycle management with existing project configuration.
---

Resolve the current absolute directory with `lodex context --target /absolute/path --json`, or use the user's explicit taskenv ID. Inspect `.lodex/project.toml` and use its named services. Commands accept `--target ID` or an absolute directory:

```
lodex service start NAME --target ID --json
lodex service list --target ID --json
lodex service inspect NAME --target ID --json
lodex service logs NAME --target ID --json
lodex service stop NAME --target ID --json
```

Inspect before starting, including after switching callers; CLI/Console exit does
not stop services. `ready_port` checks TCP; `ready_argv` exit 0 means startup-ready.
Without either, running means only that the process survived startup. Readiness
is not monitored continuously. Report readiness, URL, observation time and failures.

Configuration changes affect future starts. Stop uses the saved handle and
launch-time `stop_timeout` even without the checkout; older records default to
three seconds. Allow that grace before declaring stop unknown. Inspect interrupted
starts/unknown handles before retrying; never kill a process from a saved PID/port
alone or edit the management DB. Resolve missing configuration, scripts or secrets
before retrying; keep secret values out of argv/output. Repo cleanup and worktree
removal are separate operations; Lodex cannot stop external endpoints.
