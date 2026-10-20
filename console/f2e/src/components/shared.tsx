import type { ReactNode } from "react";
import { FolderOpen } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { Task } from "@/api";

export function taskLabel(task: Task) {
  if (task.branch) return task.branch;
  if (task.state === "present" && task.head && !task.git_error)
    return "Detached HEAD";
  const directory = task.path.replace(/\/+$/, "").split("/").pop();
  return directory && !/^[a-f0-9]{16}$/i.test(directory)
    ? directory
    : task.state === "present"
      ? "Unknown branch"
      : "Unavailable worktree";
}
export function State({
  value,
  worktree = false,
}: {
  value: string;
  worktree?: boolean;
}) {
  const tone = ["running", "succeeded"].includes(value)
    ? "success"
    : ["failed", "missing", "identity_mismatch"].includes(value)
      ? "danger"
      : ["unknown", "interrupted", "starting", "stopping"].includes(value)
        ? "warning"
        : "neutral";
  return (
    <Badge variant="outline" className={`state state-${tone}`}>
      <span className="state-dot" aria-hidden="true" />
      {worktree && value === "present" ? "Available" : value}
    </Badge>
  );
}
export function PageHeading({
  title,
  description,
  children,
}: {
  title: string;
  description?: string;
  children?: ReactNode;
}) {
  return (
    <div className="page-heading">
      <div>
        <h1>{title}</h1>
        {description && <p className="muted">{description}</p>}
      </div>
      <div className="actions">{children}</div>
    </div>
  );
}
export function Empty({
  title,
  children,
  action,
}: {
  title: string;
  children: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="empty">
      <FolderOpen size={28} strokeWidth={1.4} />
      <h2>{title}</h2>
      <p className="muted">{children}</p>
      {action}
    </div>
  );
}
export function Loading() {
  return (
    <div className="loading" role="status" aria-label="Loading console">
      <Skeleton className="h-8 w-52" />
      <Skeleton className="h-12 w-full" />
      <Skeleton className="h-24 w-full" />
      <span className="sr-only">Loading…</span>
    </div>
  );
}
export function RawData({ value }: { value: unknown }) {
  return (
    <details className="raw-data">
      <summary>View raw data</summary>
      <pre>{JSON.stringify(value, null, 2)}</pre>
    </details>
  );
}
export function Values({
  values,
  label = "Value",
}: {
  values: Record<string, string>;
  label?: string;
}) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Name</TableHead>
          <TableHead>{label}</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {Object.entries(values).map(([key, value]) => (
          <TableRow key={key}>
            <TableCell>
              <code>{key}</code>
            </TableCell>
            <TableCell className="break-value">
              <code>{value}</code>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
