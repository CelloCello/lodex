import { useEffect, useId, useRef, useState } from "react";
import { Link, NavLink } from "react-router-dom";
import { DropdownMenu } from "radix-ui";
import { hasDuplicateProjectLabel, projectLabel } from "@/lib/projects";
import {
  ChevronDown,
  ChevronRight,
  FolderGit2,
  FolderOpen,
  GitBranch,
  KeyRound,
  LayoutDashboard,
  Plus,
  MoreHorizontal,
  Search,
  Pencil,
  Pin,
  PinOff,
  Trash2,
} from "lucide-react";
import type { Overview } from "@/api";
import { taskLabel } from "@/components/shared";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  attentionReasons,
  compareEnvironments,
  environmentPath,
  runningServices,
} from "@/lib/environments";

export function useProjectNavigation(
  data: Overview,
  target?: string,
  selectedProject?: string,
) {
  const [search, setSearch] = useState("");
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set());
  const project =
    selectedProject ||
    data.taskenvs.find((task) => task.id === target)?.project;
  const first =
    data.projects.find((project) => project.pinned)?.id ||
    data.projects[0]?.id ||
    data.taskenvs[0]?.project;
  useEffect(() => {
    const id = project || first;
    if (id)
      setExpanded((current) =>
        current.has(id) ? current : new Set([...current, id]),
      );
  }, [project, first, target]);
  return {
    project,
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
  onEdit,
  onPin,
  onDelete,
  busy,
}: {
  data: Overview;
  target?: string;
  navigation: NavigationState;
  onNavigate: () => void;
  onAdd: (project: string, trigger: HTMLButtonElement) => void;
  onRegister: (trigger: HTMLButtonElement) => void;
  onEdit: (project: string, trigger: HTMLButtonElement) => void;
  onPin: (project: string, pinned: boolean) => void;
  onDelete: (project: string, trigger: HTMLButtonElement) => void;
  busy: boolean;
}) {
  const { search, setSearch, expanded, toggle, project } = navigation;
  const prefix = useId();
  const menuTriggers = useRef(new Map<string, HTMLButtonElement>());
  const editing = useRef(false);
  const pinnedIds = new Set(
    data.projects
      .filter((project) => project.pinned)
      .map((project) => project.id),
  );
  const ids = [
    ...new Set([
      ...data.projects.map((p) => p.id),
      ...data.taskenvs.map((t) => t.project),
    ]),
  ].sort((a, b) => Number(pinnedIds.has(b)) - Number(pinnedIds.has(a)));
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
          aria-label="Search all projects and environments"
          placeholder="Search…"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
      </div>
      <div className="project-tree" aria-label="Projects and environments">
        <div className="tree-heading-row">
          <h2 className="tree-heading">Projects</h2>
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label="Add a project"
            title="Add project"
            disabled={busy}
            onClick={(event) => onRegister(event.currentTarget)}
          >
            <Plus />
          </Button>
        </div>
        {ids.map((id, index) => {
          const label = projectLabel(data.projects, id);
          const identity = label === id ? id : `${label} (${id})`;
          const ambiguous = hasDuplicateProjectLabel(data.projects, label);
          const tasks = data.taskenvs
            .filter(
              (task) =>
                task.project === id &&
                `${id} ${label} ${task.branch || "detached"} ${task.path} ${task.id}`
                  .toLowerCase()
                  .includes(search.toLowerCase()),
            )
            .sort(compareEnvironments(target));
          if (
            search &&
            !tasks.length &&
            !`${id} ${label}`.toLowerCase().includes(search.toLowerCase())
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
                  aria-label={`Toggle ${id}`}
                  onClick={() => toggle(id)}
                >
                  {open ? <ChevronDown /> : <ChevronRight />}
                </button>
                <Link
                  className="tree-project-link"
                  to={`/environments?project=${encodeURIComponent(id)}`}
                  aria-label={`Open project ${identity}`}
                  aria-current={!target && project === id ? "page" : undefined}
                  onClick={onNavigate}
                  title={identity}
                >
                  <FolderGit2 />
                  <span>
                    <span>{label}</span>
                    {ambiguous && <small>{id}</small>}
                  </span>
                  {pinnedIds.has(id) && (
                    <Pin className="project-pin" aria-label="Pinned" />
                  )}
                </Link>
                {data.projects.some((project) => project.id === id) && (
                  <>
                    <DropdownMenu.Root modal={false}>
                      <DropdownMenu.Trigger asChild>
                        <Button
                          ref={(node) => {
                            if (node) menuTriggers.current.set(id, node);
                            else menuTriggers.current.delete(id);
                          }}
                          variant="ghost"
                          size="icon-sm"
                          aria-label={`Project menu for ${identity}`}
                          title="Project menu"
                          className="project-menu-trigger"
                          aria-disabled={busy}
                          onPointerDown={(event) => {
                            if (busy) event.preventDefault();
                          }}
                          onKeyDown={(event) => {
                            if (
                              busy &&
                              ["Enter", " ", "ArrowDown"].includes(event.key)
                            )
                              event.preventDefault();
                          }}
                        >
                          <MoreHorizontal />
                        </Button>
                      </DropdownMenu.Trigger>
                      <DropdownMenu.Portal>
                        <DropdownMenu.Content
                          className="project-menu"
                          align="end"
                          sideOffset={4}
                          onCloseAutoFocus={(event) => {
                            if (editing.current) {
                              event.preventDefault();
                              editing.current = false;
                            }
                          }}
                        >
                          <DropdownMenu.Item
                            className="project-menu-item"
                            onSelect={() => {
                              const trigger = menuTriggers.current.get(id);
                              if (trigger) {
                                editing.current = true;
                                onEdit(id, trigger);
                              }
                            }}
                          >
                            <Pencil aria-hidden="true" />
                            Edit
                          </DropdownMenu.Item>
                          <DropdownMenu.Item
                            className="project-menu-item"
                            onSelect={() => onPin(id, !pinnedIds.has(id))}
                          >
                            {pinnedIds.has(id) ? (
                              <PinOff aria-hidden="true" />
                            ) : (
                              <Pin aria-hidden="true" />
                            )}
                            {pinnedIds.has(id) ? "Unpin" : "Pin"}
                          </DropdownMenu.Item>
                          <DropdownMenu.Separator className="project-menu-separator" />
                          <DropdownMenu.Item
                            className="project-menu-item text-destructive"
                            onSelect={() => {
                              const trigger = menuTriggers.current.get(id);
                              if (trigger) {
                                editing.current = true;
                                onDelete(id, trigger);
                              }
                            }}
                          >
                            <Trash2 aria-hidden="true" />
                            Delete
                          </DropdownMenu.Item>
                        </DropdownMenu.Content>
                      </DropdownMenu.Portal>
                    </DropdownMenu.Root>
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      aria-label={`Add environment to ${identity}`}
                      title="Add environment"
                      disabled={busy}
                      onClick={(event) => onAdd(id, event.currentTarget)}
                    >
                      <Plus />
                    </Button>
                  </>
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
                      aria-label={`Open ${taskLabel(task)} in ${identity}`}
                      title={`${taskLabel(task)} · ${task.path}`}
                      onClick={onNavigate}
                    >
                      {task.main ? <FolderOpen /> : <GitBranch />}
                      <span className="tree-checkout-copy">
                        <span>{taskLabel(task)}</span>
                        {task.state !== "present" && (
                          <small>
                            {task.state === "identity_mismatch"
                              ? "Replaced"
                              : task.state === "missing"
                                ? "Missing"
                                : "Unavailable"}
                          </small>
                        )}
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
                      ? "No matching environments"
                      : "No registered environments"}
                  </p>
                )}
                {tasks.length > 6 && (
                  <Link
                    className="tree-view-all"
                    to={`/environments?project=${encodeURIComponent(id)}${search ? `&q=${encodeURIComponent(search)}` : ""}`}
                    onClick={onNavigate}
                  >
                    Show all
                    <ChevronRight />
                  </Link>
                )}
              </div>
            </section>
          );
        })}
        {!ids.length && (
          <p className="tree-empty muted">Add a project to get started.</p>
        )}
        {!!ids.length &&
          search &&
          !ids.some((id) =>
            `${id} ${projectLabel(data.projects, id)} ${data.taskenvs
              .filter((task) => task.project === id)
              .map((task) => `${task.branch} ${task.path} ${task.id}`)
              .join(" ")}`
              .toLowerCase()
              .includes(search.toLowerCase()),
          ) && (
            <p className="tree-empty muted">
              No matching projects or environments.
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
        <p className="muted small">Shared with your CLI.</p>
      </div>
    </div>
  );
}
