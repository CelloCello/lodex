# herdr-core and Herdr App

Use `hc --skill` and installed help for current syntax. Work in an explicitly
selected, already available local core context; carry its session/endpoint through
every command. Do not treat a TUI `HERDR_ENV` check as a core requirement. Some hc
commands auto-start a core, including schema inspection; do not probe an unrelated
default context or start/restart a user's server as a fallback.

## Separate controller from worker children

Run each foreground delegation endpoint in its own core terminal:

```sh
hc run --bg --no-parent --no-notify --name grant-b --cwd /absolute/source \
  env LODEX_HOME=/absolute/lodex-home /absolute/bin/lodex \
  service delegate --target TASKENV_ID --service NAME --json
```

Use observed values and a unique name. Wait for `listening` with the runtime's
output wait/read surface and retain the returned full terminal identity. The
controller has no parent and is outside A's B/C child set, so a long-lived endpoint
does not keep `hc wait --children all` waiting forever. Do not use `--rm` or `--keep`
to hide/restart its failures. Do not derive liveness solely from its old output.

## Interactive worker

Run the draft's `launcher_argv` with explicit worker cwd and parent A:

```text
hc run --bg --parent A_TERMINAL --outlive-parent --name task-b --cwd /absolute/taskenv
  env HC_SESSION=SELECTED_SESSION HC_SOCKET=/absolute/selected/core.sock
  LAUNCHER_ARGV... --policy /absolute/worker-policies/ID.json --runtime core
  --task-file /absolute/task.txt
```

Construct argv as an argument array or correctly quoted POSIX command, using
actual values. The launcher reads the protected policy, explicitly sets its
`CODEX_HOME`, and starts interactive Codex with `--no-daemon` and the task in
native argv. It does not depend on the core inheriting A's shell exports.
Pass the selected `HC_SESSION` and `HC_SOCKET` in the child command too: setting
them only on the `hc` client does not guarantee the worker receives them. The
guard records these values with the terminal ID for later recovery; this does
not grant the worker access to the denied control socket.
Service routing is delivered through the reviewed shell-environment settings.
There is no print/one-shot mode and no second Herdr/agent-created worktree.

If A is an existing agent outside a core terminal, select the intended local core
explicitly and use `--no-parent` for B/C instead of inventing an A terminal ID.
Track and wait on those returned addresses individually; child-group waits are
only for an actual core parent. This is a chosen entry point, not runtime fallback.

The wrapper's task argument is not hc's template first-message delivery. Inspect
the actual terminal/status/output and confirm the agent acknowledges the task;
do not reinterpret absent `first_message.sent` as either success or permission to
resend. For direct native/template launches, honor the upstream first-message
result. A timeout or lost reply requires observation before another mutation.

Use `hc wait TERMINAL --timeout SECONDS`, `hc read --lines N TERMINAL`, and
`hc get TERMINAL`. OSC status/settled state reports a turn, not task acceptance
or sandbox correctness. Use `hc send TERMINAL TEXT` for later work only after
confirming readiness; do not force through blocked UI. Use child waits for B/C,
not the no-parent controllers. Workers need no `hc send` capability: A observes
their current output and native core notifications. They retain no core socket
or broader host-control permission.

## App and recovery

App is the UI for these same core terminals. Read `herdr-app --skill` for the
installed version's presentation commands. `terminal.show` provides temporary
display. A parentless terminal may need explicit attachment before it has a tab:
when the user requests that view, inspect the intended App space, apply
`hc label TERMINAL herdr.space=OBSERVED_SPACE_ID`, inspect the resulting App tab,
then use `herdr-app do tab.select --id OBSERVED_TAB_ID`. Carry the selected core
context and App home through these commands. This presents the existing terminal;
it does not launch another agent or worktree. `agent.focus` alone can select the
sidebar agent without switching the displayed tab, so verify the visible cwd and
session before direct input. Do not attach workers to an unrelated App space.
The user can directly interact with B/C, then return to A. Closing an App window
leaves core terminals alive; closing/killing a terminal ends that program.
Attaching/detaching a viewer and `--outlive-parent` are different lifecycles.

For a main-checkout pane plus worker panes in one tab, launch each worker with
the same explicit taskenv cwd/policy above, initially without App labels. Select
the observed main tab and focus its pane, then use
`herdr-app do terminal.keep --terminal NEW_WORKER_TERMINAL --place right`
(or `down`). For an already visible worker, first use
`herdr-app do terminal.park --terminal WORKER_TERMINAL`, confirm its pane is gone
and the same core process is still live, then select/focus the destination and
keep it there. Inspect `herdr-app ls` and the worker's cwd afterward.
These operations present an existing terminal without starting another agent.
Do not use a plain `pane.split` followed by a default-cwd agent launch as a
substitute: that can leave workers sharing the main checkout. Controllers remain
in their separate hidden terminals. Taskenv identity, writer admission, service
handles and native resume do not depend on the visible tab or pane ID.

Follow [lifecycle](lifecycle.md) for grant renewal. Confirm the old program exited,
then launch the new policy with `--resume NATIVE_UUID` and focused continuation
context. Record the new terminal address against the same taskenv. A new tab does
not change an existing agent's OS grants. Never use server-wide stop/restart for
one task, guess IDs across core sessions/machines, or retry an unknown writer.
These operations target local taskenvs; remote execution needs its own paths,
permissions and validated adapter before dispatch.
