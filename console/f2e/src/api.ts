export type Service = {
  name: string;
  state: string;
  url?: string;
  observed_at?: string;
  warning?: string;
};
export type Operation = {
  id: string;
  command: string;
  state: string;
  started_at: string;
  exit_code?: number;
};
export type Resource = {
  name: string;
  kind: string;
  id: string;
  state: string;
  scope: string;
  observed_at: string;
};
export type Task = {
  id: string;
  project: string;
  path: string;
  branch: string | null;
  head?: string | null;
  git_error?: string;
  state: string;
  owned: boolean;
  main: boolean;
  config_status: string;
  config_source?: { source?: string; method?: string };
  services: Service[];
  operations: Operation[];
  known_resources: Resource[];
  cleanup: { available: boolean; reason?: string };
};
export type Detail = Task & {
  configuration_path: string;
  commands?: string[];
  configured_services?: string[];
  environment?: {
    values: Record<string, string>;
    secret_refs: Record<string, string>;
  };
  configuration_error?: { code: string; message: string };
};
export type Project = { id: string; source_checkout: string; source: string };
export type Overview = {
  projects: Project[];
  taskenvs: Task[];
  secrets: string[];
};
export type Action = {
  action: string;
  target?: string;
  name?: string;
  path?: string;
  project?: string;
  ref?: string;
  branch?: string;
  config?: string;
  value?: string;
  output?: string;
  yes?: boolean;
  force?: boolean;
};

const fragment = new URLSearchParams(location.hash.slice(1));
if (fragment.has("token")) {
  sessionStorage.setItem("lodex-token", fragment.get("token")!);
  history.replaceState(null, "", location.pathname);
}

export async function request<T>(
  path: string,
  action?: Action,
  signal?: AbortSignal,
): Promise<T> {
  const response = await fetch(path, {
    signal,
    method: action ? "POST" : "GET",
    headers: {
      Authorization: `Bearer ${sessionStorage.getItem("lodex-token") || ""}`,
      ...(action ? { "Content-Type": "application/json" } : {}),
    },
    ...(action ? { body: JSON.stringify(action) } : {}),
  });
  const data = await response.json();
  if (!data.ok) {
    throw new Error(
      data.error?.message ||
        `Operation ${data.result?.state || "failed"}. Inspect its recorded result.`,
    );
  }
  return data.result as T;
}

export const getOverview = (signal?: AbortSignal) =>
  request<Overview>("/api/state", undefined, signal);
export const getDetail = (id: string, signal?: AbortSignal) =>
  request<Detail>(`/api/task/${encodeURIComponent(id)}`, undefined, signal);
export const act = (action: Action) =>
  request<Record<string, unknown>>("/api/action", action);
