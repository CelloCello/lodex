# Herdr TUI

Use only in the actual selected TUI caller context: check `HERDR_ENV=1` and read
the upstream Herdr skill. Use returned pane IDs in that socket/session, not the
user's focused pane. Current syntax comes from `herdr --help`, `herdr pane` and
`herdr agent`; do not invoke a mutating command with defaults for discovery.

## Controller

Create a distinct pane in the manager context, preserving focus and using the
source cwd. In it run the foreground `lodex service delegate --target ID --service
NAME --json` with the observed `LODEX_HOME` and installed Lodex executable. It is
a trusted controller process, not a worker agent or a one-turn manager command.
Wait for its `listening` result and retain controller pane, grant, credential,
socket and runtime paths. A detached viewing client does not end this controller;
closing its pane does. Do not put it in a pane the user intends to close with B.

## Interactive worker

After `worktree worker-config` succeeds, split from A with explicit cwd/focus:

```sh
herdr pane split --current --direction right --cwd /absolute/taskenv --no-focus
```

Choose a suitable split direction from actual layout. In the returned pane, run
the draft's `launcher_argv` followed by:

```text
--policy /absolute/worker-policies/ID.json --runtime tui --task-file /absolute/task.txt
```

Use `herdr pane run PANE_ID COMMAND` with a shell-quoted command (`shlex.join` on
POSIX). Use the observed interpreter/module arguments exactly. This short command
loads the full reviewed settings outside the terminal's canonical input buffer;
do not paste the much longer `agent_argv` into a shell or drop permissions to fit.
The guard starts Codex interactively with the first task in its native argv and
holds the taskenv's writer lock through subsequent turns.

`pane run` acknowledges admission, not agent readiness or task receipt. Observe
that pane with `pane read`/`agent get`; once detected, use `agent wait`/`agent read`
and, optionally, `agent rename PANE_ID NAME`. Do not launch again after timeout
or prompt a booting/blocked agent. Confirm the assigned task arrived before a
productive follow-up. Do not claim screen detection proves its sandbox loaded.

Send later work with `herdr agent prompt PANE_ID TEXT --wait --timeout MS` and
use bounded reads. A settled turn keeps B/C interactive. Direct user work in B/C
must be reflected in A's next observation, not overwritten by A's older task.

Record the native Codex session UUID when actually observed; do not infer it from
a pane ID or agent name. Hooks are disabled by the generated worker draft, so
some integration metadata may be unavailable; use supported status/history
inspection rather than granting workers the Herdr control socket to report it.

## Resume and finish

Follow [lifecycle](lifecycle.md): exit and confirm the old worker first, then run
the short launcher with the new policy and `--resume NATIVE_UUID`, in the same
taskenv and an available pane. Observe its actual new identity/settings. Closing
the old pane does not revoke a grant or remove a Lodex worktree. Cleanup and
controller teardown are explicit, separate operations.
