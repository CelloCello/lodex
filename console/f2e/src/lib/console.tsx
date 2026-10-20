import { createContext, useContext, useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { act, ApiError, type Action } from "@/api";
import {
  consoleQueryKey,
  overviewQueryOptions,
  taskenvQueryOptions,
} from "@/lib/queries";

const ordinaryWrites = [
  "project.add",
  "project.rename",
  "project.pin",
  "project.delete",
  "worktree.create",
  "worktree.attach",
  "worktree.remove",
  "worktree.forget",
  "prepare",
  "run",
  "cleanup",
  "service.start",
  "service.stop",
  "env.export",
  "port.set",
] as const;

type OrdinaryWrite = Omit<Action, "action" | "value"> &
  (
    | {
        action: Exclude<(typeof ordinaryWrites)[number], "port.set">;
        value?: never;
      }
    | { action: "port.set"; value: string }
  );

function isOrdinaryWrite(action: Action): action is OrdinaryWrite {
  return (
    (action.action === "port.set"
      ? typeof action.value === "string"
      : action.value === undefined) &&
    ordinaryWrites.some((name) => name === action.action) &&
    (!["worktree.remove", "worktree.forget", "project.delete"].includes(
      action.action,
    ) ||
      action.yes === true)
  );
}

function completedNotice(
  result: Record<string, unknown>,
  action: Action,
  label: string,
) {
  const config = result.configuration as
    { method?: string; path?: string } | undefined;
  if (result.already_registered) return "Project already registered.";
  return config
    ? `${label} completed. Configuration ${config.method}: ${config.path}. ${typeof result.next_step === "string" ? result.next_step : ""}`
    : action.action === "worktree.remove"
      ? `${label} completed. The registry record is retained for inspection. Use Unregister environment to remove it.`
      : `${label} completed.`;
}

export function useConsoleState(target?: string) {
  const queryClient = useQueryClient();
  const targetRef = useRef(target);
  useEffect(() => {
    targetRef.current = target;
  }, [target]);
  const overview = useQuery(overviewQueryOptions);
  const hasTarget =
    !!target && !!overview.data?.taskenvs.some((t) => t.id === target);
  const task = useQuery({
    ...taskenvQueryOptions(target),
    enabled: hasTarget,
  });
  const data = overview.data ?? { projects: [], taskenvs: [], secrets: [] };
  const detail = hasTarget ? (task.data ?? null) : null;
  const loading = overview.isLoading || (hasTarget && task.isLoading);
  // Cached data keeps its original observation time while a refetch is pending.
  const observedAt = hasTarget
    ? Math.min(overview.dataUpdatedAt, task.dataUpdatedAt)
    : overview.dataUpdatedAt;
  const observed = observedAt ? new Date(observedAt) : null;
  const [specialBusy, setSpecialBusy] = useState("");
  const [specialError, setSpecialError] = useState("");
  const [notice, setNotice] = useState("");
  const writing = useRef(false);
  const mutation = useMutation({
    mutationFn: ({ action }: { action: OrdinaryWrite; label: string }) =>
      act(action),
    retry: false,
    networkMode: "always",
    gcTime: 0,
    onSuccess: (result, { action, label }) =>
      setNotice(completedNotice(result, action, label)),
    // Returning this promise keeps the mutation pending until observation finishes,
    // even when a failed response may have left side effects on the server.
    onSettled: () => refresh(),
  });
  const busy =
    specialBusy || (mutation.isPending ? mutation.variables.label : "");
  const [dismissedErrors, setDismissedErrors] = useState<(Error | null)[]>([]);
  const currentError = [
    mutation.error,
    hasTarget ? task.error : null,
    overview.error,
  ].find((error) => error && !dismissedErrors.includes(error));
  const error = specialError || currentError?.message || "";

  function setError(message: string) {
    setSpecialError(message);
    if (!message)
      setDismissedErrors([mutation.error, overview.error, task.error]);
  }

  async function refresh() {
    // Refresh membership first: an action may have forgotten the selected task.
    // Keep inactive detail entries stale, without querying removed registrations.
    await queryClient.cancelQueries({ queryKey: consoleQueryKey });
    await queryClient.invalidateQueries({
      queryKey: consoleQueryKey,
      refetchType: "none",
    });
    try {
      const current = await queryClient.query(overviewQueryOptions);
      const id = targetRef.current;
      if (id && current.taskenvs.some((task) => task.id === id))
        await queryClient.query(taskenvQueryOptions(id));
    } catch {
      // Active query errors are shown separately; a read failure must not turn a
      // successful write into a failed mutation or replace its original error.
    }
  }

  async function perform(action: Action, label: string, readOnly = false) {
    if (!readOnly && writing.current) return;
    const ordinary = !readOnly && isOrdinaryWrite(action);
    if (!readOnly) {
      writing.current = true;
      if (!ordinary) setSpecialBusy(label);
    }
    setError("");
    setNotice("");
    try {
      if (ordinary) return await mutation.mutateAsync({ action, label });
      // Secrets, Logs and previews never enter the mutation or query cache.
      const result = await act(action);
      if (!readOnly) {
        setNotice(completedNotice(result, action, label));
      }
      return result;
    } catch (e) {
      if (!ordinary) setError(e instanceof Error ? e.message : String(e));
    } finally {
      if (!readOnly) {
        if (!ordinary) {
          await refresh();
          setSpecialBusy("");
        }
        writing.current = false;
      }
    }
  }

  return {
    data,
    detail,
    loading,
    busy,
    error,
    errorDetails:
      currentError instanceof ApiError ? currentError.details : undefined,
    notice,
    observed,
    refresh,
    perform,
    setError,
    setNotice,
  };
}

type ConsoleState = ReturnType<typeof useConsoleState>;
export const ConsoleContext = createContext<ConsoleState | null>(null);
export function useConsole() {
  const value = useContext(ConsoleContext);
  if (!value) throw new Error("Console provider is missing");
  return value;
}
