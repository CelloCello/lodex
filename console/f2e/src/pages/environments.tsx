import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ArrowUpRight, GitBranch, Search, Pencil } from "lucide-react";
import { useConsole } from "@/lib/console";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Empty,
  Loading,
  PageHeading,
  State,
  taskLabel,
} from "@/components/shared";
import { EnvironmentForm } from "@/components/environment-form";
import { projectLabel } from "@/lib/projects";
import {
  attentionReasons,
  compareEnvironments,
  latestOperation,
  worktreeKind,
} from "@/lib/environments";

export function Environments({
  onEdit,
}: {
  onEdit: (project: string, trigger: HTMLButtonElement) => void;
}) {
  const { data, loading, busy } = useConsole();
  const [query, setQuery] = useSearchParams();
  const search = query.get("q") || "";
  const project = query.get("project") || "";
  const status = query.get("status") || "";
  const currentProject = data.projects.find((item) => item.id === project);
  const hasEnvironments = data.taskenvs.some(
    (task) => !project || task.project === project,
  );
  function filter(key: string, value: string) {
    setQuery(
      (current) => {
        if (value) current.set(key, value);
        else current.delete(key);
        current.delete("page");
        return current;
      },
      { replace: true },
    );
  }
  const tasks = data.taskenvs
    .filter(
      (t) =>
        (!project || t.project === project) &&
        `${t.project} ${projectLabel(data.projects, t.project)} ${t.branch || "detached"} ${t.path} ${t.id}`
          .toLowerCase()
          .includes(search.toLowerCase()) &&
        (!status ||
          (status === "running"
            ? t.services.some((s) => s.state === "running")
            : status === "attention"
              ? attentionReasons(t).length > 0
              : t.state === "present")),
    )
    .sort(compareEnvironments());
  const pageSize = 8;
  const pages = Math.max(1, Math.ceil(tasks.length / pageSize));
  const requestedPage = Number(query.get("page") || "1");
  const page = Math.min(
    pages,
    Math.max(1, Number.isFinite(requestedPage) ? Math.floor(requestedPage) : 1),
  );
  function changePage(value: number) {
    const next = new URLSearchParams(query);
    if (value === 1) next.delete("page");
    else next.set("page", String(value));
    setQuery(next);
  }
  return (
    <>
      <PageHeading
        title={project ? projectLabel(data.projects, project) : "Environments"}
      >
        {currentProject && (
          <Button
            variant="outline"
            disabled={!!busy}
            onClick={(event) => onEdit(currentProject.id, event.currentTarget)}
          >
            <Pencil />
            Edit
          </Button>
        )}
      </PageHeading>
      {currentProject && (
        <div className="project-summary">
          <p className="muted small">
            Project ID <code>{currentProject.id}</code>
          </p>
          <code className="muted break-value" aria-label="Source worktree path">
            {currentProject.source_checkout}
          </code>
          <details className="project-details" key={currentProject.id}>
            <summary>Details</summary>
            <dl className="configuration-paths">
              <dt>Config source</dt>
              <dd>
                <code>{currentProject.source}</code>
              </dd>
            </dl>
            <p className="muted small">
              Used when configuration is missing. Existing worktrees keep their
              own settings.
            </p>
          </details>
        </div>
      )}
      <div className="environment-toolbar">
        <div className="filters">
          <div className="search-field">
            <Search />
            <Input
              aria-label="Search environments"
              placeholder="Search…"
              value={search}
              onChange={(e) => filter("q", e.target.value)}
            />
          </div>
          <select
            aria-label="Filter by project"
            value={project}
            onChange={(e) => filter("project", e.target.value)}
          >
            <option value="">All projects</option>
            {data.projects.map((p) => (
              <option key={p.id} value={p.id}>
                {projectLabel(data.projects, p.id)}
                {p.display_name && p.display_name !== p.id ? ` (${p.id})` : ""}
              </option>
            ))}
          </select>
          <select
            aria-label="Filter by status"
            value={status}
            onChange={(e) => filter("status", e.target.value)}
          >
            <option value="">All statuses</option>
            <option value="running">Services running</option>
            <option value="present">Available</option>
            <option value="attention">Needs attention</option>
          </select>
        </div>
        {(!project || currentProject) && (
          <EnvironmentForm kind="add" project={project || undefined} />
        )}
      </div>
      {loading ? (
        <Loading />
      ) : !hasEnvironments ? (
        <Empty
          title="No environments yet"
          action={
            !data.projects.length && (
              <Button asChild>
                <Link to="/projects">
                  Add project <ArrowUpRight />
                </Link>
              </Button>
            )
          }
        >
          Create a worktree or use an existing one to get started.
        </Empty>
      ) : !tasks.length ? (
        <Empty
          title="No matching environments"
          action={
            <Button variant="outline" onClick={() => setQuery({})}>
              Clear filters
            </Button>
          }
        >
          Try a different branch, project or status.
        </Empty>
      ) : (
        <div className="data-panel">
          <Table className="environment-table">
            <TableHeader>
              <TableRow>
                <TableHead>Environment</TableHead>
                {!project && <TableHead>Project</TableHead>}
                <TableHead>Worktree</TableHead>
                <TableHead>Services</TableHead>
                <TableHead>Last run</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {tasks
                .slice((page - 1) * pageSize, page * pageSize)
                .map((task) => {
                  const latest = latestOperation(task);
                  return (
                    <TableRow key={task.id}>
                      <TableCell>
                        <Link
                          className="environment-link"
                          to={`/environments/${encodeURIComponent(task.id)}/services`}
                        >
                          <GitBranch size={16} />
                          <span>{taskLabel(task)}</span>
                          <ArrowUpRight size={14} />
                        </Link>
                        <code className="path-preview" title={task.path}>
                          {task.path}
                        </code>
                        <div className="mobile-environment-summary">
                          <span>
                            {!project &&
                              `${projectLabel(data.projects, task.project)} · `}
                            {
                              task.services.filter((s) => s.state === "running")
                                .length
                            }{" "}
                            services running
                          </span>
                          <State value={task.state} worktree />
                          {task.config_status !== "valid" && (
                            <span className="text-destructive">
                              Config: {task.config_status}
                            </span>
                          )}
                          {latest && (
                            <span>
                              {latest.command}: {latest.state}
                            </span>
                          )}
                        </div>
                      </TableCell>
                      {!project && (
                        <TableCell>
                          {projectLabel(data.projects, task.project)}
                        </TableCell>
                      )}
                      <TableCell>
                        <State value={task.state} worktree />
                        {(task.main || !task.owned) && (
                          <div className="cell-secondary">
                            {worktreeKind(task)}
                          </div>
                        )}
                        {task.config_status !== "valid" && (
                          <div className="cell-secondary text-destructive">
                            Configuration: {task.config_status}
                          </div>
                        )}
                      </TableCell>
                      <TableCell>
                        {task.services.length ? (
                          <>
                            <span className="service-count">
                              {
                                task.services.filter(
                                  (s) => s.state === "running",
                                ).length
                              }{" "}
                              running
                            </span>
                            {task.services.some(
                              (service) => service.state !== "running",
                            ) && (
                              <div className="cell-secondary">
                                {task.services.length} total
                              </div>
                            )}
                          </>
                        ) : (
                          <span className="muted" title="No recorded services">
                            —
                          </span>
                        )}
                      </TableCell>
                      <TableCell>
                        {latest ? (
                          <>
                            <span>{latest.command}</span>
                            <div className="mt-1">
                              <State value={latest.state} />
                            </div>
                          </>
                        ) : (
                          <span className="muted" title="No recorded runs">
                            —
                          </span>
                        )}
                      </TableCell>
                    </TableRow>
                  );
                })}
            </TableBody>
          </Table>
          <div className="table-footer">
            <span className="pagination-count">
              {(page - 1) * pageSize + 1}–
              {Math.min(page * pageSize, tasks.length)} of {tasks.length}{" "}
              environments
            </span>
            <div className="actions" aria-label="Environment pagination">
              <Button
                variant="outline"
                size="sm"
                disabled={page === 1}
                onClick={() => changePage(page - 1)}
              >
                Previous
              </Button>
              <span className="pagination-page">
                {page} / {pages}
              </span>
              <Button
                variant="outline"
                size="sm"
                disabled={page === pages}
                onClick={() => changePage(page + 1)}
              >
                Next
              </Button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

export function Projects() {
  const { data, loading } = useConsole();
  const [search, setSearch] = useState("");
  const projects = data.projects.filter((p) =>
    `${p.id} ${p.display_name || ""} ${p.source_checkout}`
      .toLowerCase()
      .includes(search.toLowerCase()),
  );
  return (
    <>
      <PageHeading title="Projects">
        <EnvironmentForm kind="project" />
      </PageHeading>
      <div className="filters">
        <div className="search-field">
          <Search />
          <Input
            aria-label="Search projects"
            placeholder="Search…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
      </div>
      {loading ? (
        <Loading />
      ) : !projects.length ? (
        <Empty title={search ? "No matching projects" : "No projects yet"}>
          Each project connects a Git repository to its environments.
          Registration does not create or prepare an environment.
        </Empty>
      ) : (
        <div className="project-list">
          {projects.map((p) => (
            <section className="project-row" key={p.id}>
              <div className="project-info">
                <h2>
                  <Link
                    to={`/environments?project=${encodeURIComponent(p.id)}`}
                  >
                    {p.display_name || p.id}
                    <ArrowUpRight size={16} />
                  </Link>
                </h2>
                <p className="muted small">
                  Project ID <code>{p.id}</code>
                </p>
                <code className="muted break-value">{p.source_checkout}</code>
                <div className="project-source">
                  <span className="muted">Config source</span>
                  <code>{p.source}</code>
                </div>
              </div>
              <div className="project-actions">
                <Button asChild variant="ghost">
                  <Link
                    to={`/environments?project=${encodeURIComponent(p.id)}`}
                  >
                    {data.taskenvs.filter((t) => t.project === p.id).length}{" "}
                    environments <ArrowUpRight />
                  </Link>
                </Button>
                <div className="actions">
                  <EnvironmentForm kind="attach" project={p.id} />
                  <EnvironmentForm kind="create" project={p.id} />
                </div>
              </div>
            </section>
          ))}
        </div>
      )}
    </>
  );
}
