import { useEffect, useId, useState } from "react";
import { Link, NavLink } from "react-router-dom";
import {
  ChevronDown,
  ChevronRight,
  FolderGit2,
  FolderOpen,
  GitBranch,
  KeyRound,
  LayoutDashboard,
  Plus,
  Search,
} from "lucide-react";
import type { Overview } from "@/api";
import { taskLabel } from "@/components/shared";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  attentionReasons,
  checkoutKind,
  compareEnvironments,
  environmentPath,
  runningServices,
} from "@/lib/environments";

export function useProjectNavigation(data: Overview, target?: string) {
  const [search, setSearch] = useState("");
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set());
  const project = data.taskenvs.find((task) => task.id === target)?.project;
  const first = data.projects[0]?.id || data.taskenvs[0]?.project;
  useEffect(() => {
    const id = project || first;
    if (id)
      setExpanded((current) =>
        current.has(id) ? current : new Set([...current, id]),
      );
  }, [project, first, target]);
  return {
    search,
    setSearch,
    expanded,
    toggle: (id: string) =>
      setExpanded((current) => {
        const next = new Set(current);
        if (next.has(id)) next.delete(id);
        else next.add(id);
        return next;
      }),
  };
}

type NavigationState = ReturnType<typeof useProjectNavigation>;
export function ProjectNavigation({
  data,
  target,
  navigation,
  onNavigate,
  onAdd,
  onRegister,
  busy,
}: {
  data: Overview;
  target?: string;
  navigation: NavigationState;
  onNavigate: () => void;
  onAdd: (project: string, trigger: HTMLButtonElement) => void;
  onRegister: (trigger: HTMLButtonElement) => void;
  busy: boolean;
}) {
  const { search, setSearch, expanded, toggle } = navigation;
  const prefix = useId();
  const ids = [
    ...new Set([
      ...data.projects.map((p) => p.id),
      ...data.taskenvs.map((t) => t.project),
    ]),
  ];
  return (
    <div className="project-navigation">
      <nav className="primary-navigation" aria-label="Main navigation">
        <NavLink to="/dashboard" onClick={onNavigate}>
          <LayoutDashboard />
          Overview
        </NavLink>
      </nav>
      <div className="project-tree-search search-field">
        <Search />
        <Input
          aria-label="Search all projects and checkouts"
          placeholder="Search projects, branches or paths…"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
      </div>
      <div className="project-tree" aria-label="Projects and checkouts">
        <h2 className="tree-heading">Projects and checkouts</h2>
        {ids.map((id, index) => {
          const tasks = data.taskenvs
            .filter(
              (task) =>
                task.project === id &&
                `${id} ${task.branch || "detached"} ${task.path} ${task.id}`
                  .toLowerCase()
                  .includes(search.toLowerCase()),
            )
            .sort(compareEnvironments(target));
          if (
            search &&
            !tasks.length &&
            !id.toLowerCase().includes(search.toLowerCase())
          )
            return null;
          const open = expanded.has(id) || !!search;
          const region = `${prefix}-project-${index}`;
          return (
            <section className="tree-project" key={id}>
              <div className="tree-project-header">
                <button
                  type="button"
                  className="tree-project-toggle"
                  aria-expanded={open}
                  aria-controls={region}
                  onClick={() => toggle(id)}
                >
                  {open ? <ChevronDown /> : <ChevronRight />}
                  <FolderGit2 />
                  <span>{id}</span>
                </button>
                {data.projects.some((project) => project.id === id) && (
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    aria-label={`Add checkout to ${id}`}
                    title="Add checkout"
                    disabled={busy}
                    onClick={(event) => onAdd(id, event.currentTarget)}
                  >
                    <Plus />
                  </Button>
                )}
              </div>
              <div id={region} className="tree-children" hidden={!open}>
                {tasks.slice(0, 6).map((task) => {
                  const attention = attentionReasons(task);
                  const running = runningServices(task);
                  return (
                    <Link
                      key={task.id}
                      className={`tree-checkout${task.id === target ? " selected" : ""}`}
                      to={environmentPath(task)}
                      aria-current={task.id === target ? "page" : undefined}
                      aria-label={`Open ${taskLabel(task)} in ${id}`}
                      title={`${taskLabel(task)} · ${task.path}`}
                      onClick={onNavigate}
                    >
                      {task.main ? <FolderOpen /> : <GitBranch />}
                      <span className="tree-checkout-copy">
                        <span>{taskLabel(task)}</span>
                        <small>
                          {task.state !== "present"
                            ? `Checkout: ${task.state}`
                            : checkoutKind(task)}
                        </small>
                      </span>
                      <span
                        className={`tree-status ${attention.length ? "tree-status-warning" : running ? "tree-status-running" : ""}`}
                        role="img"
                        aria-label={
                          attention.length
                            ? attention.join(". ")
                            : `${running} services running`
                        }
                      />
                    </Link>
                  );
                })}
                {!tasks.length && (
                  <p className="tree-empty muted">
                    {search
                      ? "No matching checkouts"
                      : "No connected checkouts"}
                  </p>
                )}
                <Link
                  className="tree-view-all"
                  to={`/environments?project=${encodeURIComponent(id)}${search ? `&q=${encodeURIComponent(search)}` : ""}`}
                  onClick={onNavigate}
                >
                  {search ? "View matching checkouts" : "View all checkouts"}
                  <ChevronRight />
                </Link>
              </div>
            </section>
          );
        })}
        {!ids.length && (
          <p className="tree-empty muted">
            Register a project to connect your first checkout.
          </p>
        )}
        {!!ids.length &&
          search &&
          !ids.some((id) =>
            `${id} ${data.taskenvs
              .filter((task) => task.project === id)
              .map((task) => `${task.branch} ${task.path} ${task.id}`)
              .join(" ")}`
              .toLowerCase()
              .includes(search.toLowerCase()),
          ) && (
            <p className="tree-empty muted">
              No matching projects or checkouts.
            </p>
          )}
      </div>
      <div className="tree-footer">
        <nav aria-label="Shared settings">
          <NavLink to="/secrets" onClick={onNavigate}>
            <KeyRound />
            Secrets
          </NavLink>
        </nav>
        <Button
          className="register-project"
          variant="ghost"
          aria-label="Register a project"
          disabled={busy}
          onClick={(event) => onRegister(event.currentTarget)}
        >
          <Plus />
          Register project
        </Button>
        <p className="muted small">
          Shared with your CLI. Services keep running when you leave.
        </p>
      </div>
    </div>
  );
}
