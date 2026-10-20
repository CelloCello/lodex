import type { Operation, Service, Task } from "@/api";

export const environmentPath = (task: Task) =>
  `/environments/${encodeURIComponent(task.id)}/services`;

export function latestOperation(task: Task): Operation | undefined {
  return task.operations.reduce<Operation | undefined>(
    (latest, operation) =>
      !latest || operation.started_at > latest.started_at ? operation : latest,
    undefined,
  );
}

export function attentionReasons(task: Task): string[] {
  const reasons: string[] = [];
  if (task.state !== "present") reasons.push(`Worktree: ${task.state}`);
  if (task.config_status !== "valid")
    reasons.push(`Configuration: ${task.config_status}`);
  for (const service of task.services)
    if (["failed", "unknown"].includes(service.state))
      reasons.push(`${service.name}: ${service.state}`);
  const latest = latestOperation(task);
  if (latest && ["failed", "interrupted", "unknown"].includes(latest.state))
    reasons.push(`Latest ${latest.command}: ${latest.state}`);
  return reasons;
}

export const runningServices = (task: Task) =>
  task.services.filter((service) => service.state === "running").length;

export const worktreeKind = (task: Task) =>
  task.main ? "Main" : task.owned ? "Created by Lodex" : "Attached";

export function compareEnvironments(selected?: string) {
  const priority = (task: Task) =>
    task.main
      ? 0
      : task.id === selected
        ? 1
        : attentionReasons(task).length
          ? 2
          : runningServices(task)
            ? 3
            : 4;
  return (a: Task, b: Task) =>
    priority(a) - priority(b) ||
    (a.branch || a.path).localeCompare(b.branch || b.path) ||
    a.id.localeCompare(b.id);
}

export const serviceGroups = [
  { key: "running", label: "Running" },
  { key: "stopped", label: "Stopped / exited" },
  { key: "failed", label: "Failed" },
  { key: "unknown", label: "Unknown / other" },
  { key: "transitioning", label: "Starting / stopping" },
  { key: "external", label: "Legacy external" },
] as const;

export function serviceGroup(service: Service) {
  if (["stopped", "exited"].includes(service.state)) return "stopped";
  if (["starting", "stopping"].includes(service.state)) return "transitioning";
  if (["running", "failed", "external"].includes(service.state))
    return service.state as "running" | "failed" | "external";
  return "unknown";
}

export function serviceCounts(tasks: Task[]) {
  const counts = {
    running: 0,
    stopped: 0,
    failed: 0,
    unknown: 0,
    transitioning: 0,
    external: 0,
  };
  for (const task of tasks)
    for (const service of task.services) counts[serviceGroup(service)]++;
  return counts;
}
