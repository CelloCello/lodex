import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ArrowUpRight, GitBranch, Search } from "lucide-react";
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

export function Environments() {
  const { data, loading } = useConsole();
  const [query, setQuery] = useSearchParams();
  const search = query.get("q") || "";
  const project = query.get("project") || "";
  const status = query.get("status") || "";
  function filter(key: string, value: string) {
    const next = new URLSearchParams(query);
    if (value) next.set(key, value);
    else next.delete(key);
    setQuery(next, { replace: true });
  }
  const tasks = data.taskenvs.filter(
    (t) =>
      (!project || t.project === project) &&
      `${t.project} ${t.branch || "detached"} ${t.path} ${t.id}`
        .toLowerCase()
        .includes(search.toLowerCase()) &&
      (!status ||
        (status === "running"
          ? t.services.some((s) => s.state === "running")
          : status === "attention"
            ? t.state !== "present" ||
              t.config_status !== "valid" ||
              t.services.some((s) => ["failed", "unknown"].includes(s.state))
            : t.state === "present")),
  );
  return (
    <>
      <PageHeading
        title="Environments"
        description="Your local checkouts, services and command results."
      >
        <EnvironmentForm kind="attach" project={project || undefined} />
        <EnvironmentForm kind="create" project={project || undefined} />
      </PageHeading>
      <div className="filters">
        <div className="search-field">
          <Search />
          <Input
            aria-label="Search environments"
            placeholder="Search branch, project or path…"
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
              {p.id}
            </option>
          ))}
        </select>
        <select
          aria-label="Filter by status"
          value={status}
          onChange={(e) => filter("status", e.target.value)}
        >
          <option value="">All statuses</option>
          <option value="running">Has running services</option>
          <option value="present">Checkout available</option>
          <option value="attention">Needs attention</option>
        </select>
      </div>
      {loading ? (
        <Loading />
      ) : !data.taskenvs.length ? (
        <Empty
          title="Connect your first environment"
          action={
            data.projects.length ? (
              <EnvironmentForm kind="create" />
            ) : (
              <Button asChild>
                <Link to="/projects">
                  Register a project <ArrowUpRight />
                </Link>
              </Button>
            )
          }
        >
          Register a repository, then create a worktree or attach an existing
          checkout for you and your coding agent.
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
                <TableHead>Project</TableHead>
                <TableHead>Checkout</TableHead>
                <TableHead>Services</TableHead>
                <TableHead>Latest operation</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {tasks.map((task) => {
                const latest = [...task.operations].sort((a, b) =>
                  b.started_at.localeCompare(a.started_at),
                )[0];
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
                          {task.project} ·{" "}
                          {
                            task.services.filter((s) => s.state === "running")
                              .length
                          }{" "}
                          services running
                        </span>
                        <State value={task.state} checkout />
                        {latest && (
                          <span>
                            {latest.command}: {latest.state}
                          </span>
                        )}
                      </div>
                    </TableCell>
                    <TableCell>
                      {task.project}
                      <div className="cell-secondary">
                        {task.main
                          ? "Main checkout"
                          : task.owned
                            ? "Managed worktree"
                            : "Attached checkout"}
                      </div>
                    </TableCell>
                    <TableCell>
                      <State value={task.state} checkout />
                      {task.config_status !== "valid" && (
                        <div className="cell-secondary text-destructive">
                          Configuration: {task.config_status}
                        </div>
                      )}
                    </TableCell>
                    <TableCell>
                      <span className="service-count">
                        {
                          task.services.filter((s) => s.state === "running")
                            .length
                        }{" "}
                        running
                      </span>
                      <div className="cell-secondary">
                        {task.services.length} recorded
                      </div>
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
                        <span className="muted">No operations yet</span>
                      )}
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
          <div className="table-footer">
            {tasks.length} {tasks.length === 1 ? "environment" : "environments"}
            <span>Closing the console leaves services running.</span>
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
    `${p.id} ${p.source_checkout}`.toLowerCase().includes(search.toLowerCase()),
  );
  return (
    <>
      <PageHeading
        title="Projects"
        description="Local repositories and their configuration sources."
      >
        <EnvironmentForm kind="project" />
      </PageHeading>
      <div className="filters">
        <div className="search-field">
          <Search />
          <Input
            aria-label="Search projects"
            placeholder="Search name or repository path…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
      </div>
      {loading ? (
        <Loading />
      ) : !projects.length ? (
        <Empty
          title={
            search ? "No matching projects" : "Register a local repository"
          }
        >
          Each project connects a Git repository to its environments.
          Registration does not create or prepare a checkout.
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
                    {p.id}
                    <ArrowUpRight size={16} />
                  </Link>
                </h2>
                <code className="muted break-value">{p.source_checkout}</code>
                <div className="project-source">
                  <span className="muted">Configuration source</span>
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
