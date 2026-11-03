# Controller, renewal and cleanup

Normal work keeps A/B/C interactive. A can coordinate while each taskenv's
controller authorizes B/C service requests independently. A turn finishing is not
agent exit, grant revocation or environment removal. A window detach is distinct
from closing its terminal. Check the chosen runtime's close/parent behavior.

## Replace one grant and resume

1. Coordinate a pause with the affected B/C. Save its taskenv, latest instructions,
   completed steps, runtime address and **observed native agent session UUID**.
   Inspect existing services and uncertain launches through trusted handles;
   keep the peer taskenv running. Do not restart services because an endpoint died.
2. Gracefully exit the affected agent after saving context. Confirm the old
   program exited in its runtime and the launch-guard record is `exited`. A pane
   returning to a shell is different from a still-running/suspended agent. The
   guard's `worker_unknown` error deliberately blocks retries after an unconfirmed
   exit; inspect and reconcile the old runtime, never delete the guard record
   or trust a PID/port as proof it is safe to start a second writer.
   A recorded `launch_failed` means no child process was created. After repairing
   that launch, retry under the same writer guard: a first launch needs no native
   UUID, while a failed resume still needs its original UUID. A program that was
   created but whose exit could not be confirmed remains blocked.
   A child can also exit before creating a native conversation. For an initial
   launch with a positive exit code, the guard records `native_admission=absent`
   only when its before/after local-storage receipts match and no native ID for
   the checkout is present. That failed launch can be repaired and retried without
   inventing a UUID. A missing UUID or a nonzero exit alone never grants a retry.
   Existing native IDs, changed or unverifiable storage, signals and successful
   exits still require reconciliation/resume; an explicit resume always retains
   its original UUID requirement. Never erase the guard record to bypass this.
3. Revoke the old grant if still active; create a new foreground controller for
   the same taskenv and explicitly selected services. Capture the new credential,
   socket, runtime and controller handle. Existing services retain their old
   trusted handles; they are not moved into the new grant's runtime.
4. If the recipe changed, review and prepare the same taskenv again. Otherwise
   reuse the successful prepare snapshot only while its recipe still matches.
   Draft a new `worktree worker-config` using the new grant and reviewed scope.
   Its unique permission profile reopens the new paths; it does not carry old
   grants into the worker's filesystem/socket allowances.
5. Launch the guard with the **new policy**, `--resume NATIVE_UUID`, and a focused
   continuation task file in the same checkout. Use its returned actual new
   pane/terminal; update A's mapping. Do not use `resume --last`, silently start a
   new conversation, create another taskenv or resubmit the entire original task.
6. Check the new agent's effective settings, cwd, tools and route. Confirm service
   inspect/stop/start work, old authorization fails and the peer remains unchanged.
   Resume productive work only after those checks. Native resume support restores
   conversation history, not old OS grants; App tab selection does not refresh it.

The receipt reader targets the inspected Codex local layout: rollout headers,
`state_5.sqlite` IDs/cwd, and `thread_history_1.sqlite` thread metadata. Known peer
threads are excluded, so A/C's normal turns do not invalidate B's receipt. New
unattributed history changes still block retry. It does not read message bodies
or use a History index as authorization. Unsupported schemas, redirected stores,
unreadable or worker-writable history and scan limits yield unknown. Indexed
compressed rollouts need no decompression; unindexed `.jsonl.zst` headers use an
existing `zstd` if available, otherwise remain unknown. No package is installed.
Decoder lookup excludes relative and worker-writable PATH entries and rejects a
worker-writable resolved executable. Its environment contains no project inputs.
Only IDs and metadata fingerprints enter the management record. Native/managed
storage changes need revalidation; this is not a universal Codex storage adapter.

## Explicit teardown

Agree on scope and stop editing. Inspect modified cleanup scripts and the
project's ordering requirements: cleanup may need its running services or settings.
Run the recipe in B/C under its existing permissions, or let A collect a recorded
result from an equivalent restricted short-lived runner:

```sh
lodex cleanup --target TASKENV_ID --worker-policy /absolute/worker-policies/ID.json --json
```

This keeps registry/log/result collection in the manager and executes only
`commands.cleanup` in the saved worker sandbox. It also works after the original
agent has exited. Only that operation's private result file is opened for the
runner beneath central state; central records and other environments stay denied.
The outer sandbox launcher uses only trusted management environment inputs.
Project variables and secrets are delivered through the private pipe to the
command inside the sandbox, so loader settings cannot execute repo code before
the restrictions apply.
Secret references must still match the prepared handoff. A changed reference is
rejected before the manager resolves any secret; review and prepare a new policy
when the cleanup needs a different secret scope. Cleanup script edits alone do
not grant access to additional central secrets.
Ordinary `lodex cleanup` still uses caller permissions. A must not use that
administrative path as a retry for a worker-modified script or a denied operation.
The service endpoint has no generic command/cleanup authorization API.

If cleanup fails or its results cannot be verified, retain checkout, services
and controller/handles for inspection. Do not continue with revoke/remove or
retry with a management profile. Review any genuinely necessary extra capability
against the actual code and targets, then obtain that specific authorization.

After cleanup and required service stop/terminal recording/ACK succeed, revoke
the grant and end its controller terminal. Only then perform separately authorized
Git/worktree removal with its preview/protections. Stop only identified processes;
do not remove runtime observations while they are needed for live services or
pending terminal ACKs. Keeping a checkout for reading does not require keeping
the controller forever. Machine reboot and automatic conversation recovery are
outside this workflow's guarantees.
