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

Report actual readiness, URL (if any), observation time and failures. Running without a readiness port means only that the worker survived startup; it does not prove application readiness. Services survive caller exit. Reopening a conversation does not imply starting them again. A changed project.toml affects the next operation and does not automatically restart anything. Stop uses the saved service handle even when configuration or checkout disappears.

For unknown handles or startup interruption, inspect before considering another start. Do not kill a PID merely because a saved port or PID matches. External endpoints cannot be stopped through Lodex. Missing secret/config/script errors need resolution before retry; never expose secret values in argv or output. Use `lodex cleanup --target ID --json` for repo cleanup separately, then preview worktree removal. Never directly edit the management database.

The optional `lodex console` uses the same records and operations. Closing its
page or process does not stop managed long services. After switching callers,
inspect existing service and operation records before taking another action;
an interrupted/unknown command is not automatically retried.
