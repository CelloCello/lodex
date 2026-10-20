import { Link, useSearchParams } from "react-router-dom";
import { ArrowRight, ArrowUpRight, FolderGit2 } from "lucide-react";
import { useConsole } from "@/lib/console";
import {
  attentionReasons,
  environmentPath,
  runningServices,
  serviceCounts,
  serviceGroups,
} from "@/lib/environments";
import { Empty, Loading, PageHeading, taskLabel } from "@/components/shared";
import { Button } from "@/components/ui/button";
import { EnvironmentForm } from "@/components/environment-form";

export function Dashboard() {
  const { data, loading } = useConsole();
  const [query, setQuery] = useSearchParams();
  const focus = ["attention", "running", "all"].includes(
    query.get("focus") || "",
  )
    ? query.get("focus")!
    : "attention";
  const counts = serviceCounts(data.taskenvs);
  const serviceTotal = Object.values(counts).reduce(
    (sum, count) => sum + count,
    0,
  );
  const attention = data.taskenvs.filter(
    (task) => attentionReasons(task).length,
  );
  const available = data.taskenvs.filter(
    (task) => task.state === "present",
  ).length;
  const projects = [
    ...new Set([
      ...data.projects.map((project) => project.id),
      ...data.taskenvs.map((task) => task.project),
    ]),
  ].map((id) => {
    const tasks = data.taskenvs.filter((task) => task.project === id);
    return { id, tasks, counts: serviceCounts(tasks) };
  });
  const maximum = Math.max(
    1,
    ...projects.map((project) =>
      Object.values(project.counts).reduce((sum, value) => sum + value, 0),
    ),
  );
  const queue = data.taskenvs.filter((task) =>
    focus === "running"
      ? runningServices(task) > 0
      : focus === "attention"
        ? attentionReasons(task).length > 0
        : true,
  );
  const projectLink = (id: string) =>
    `/environments?project=${encodeURIComponent(id)}`;
  if (loading) return <Loading />;
  return (
    <>
      <PageHeading title="Overview" />
      {!data.projects.length && !data.taskenvs.length ? (
        <Empty
          title="No projects yet"
          action={<EnvironmentForm kind="project" />}
        >
          Add a Git repository to get started.
        </Empty>
      ) : (
        <>
          <div className="overview-metrics" aria-label="Environment statistics">
            <Link to="?focus=running" className="overview-metric">
              <span>Running services</span>
              <strong>{counts.running}</strong>
              <small>{serviceTotal} recorded services</small>
            </Link>
            <Link to="?focus=attention" className="overview-metric">
              <span>Needs attention</span>
              <strong className="metric-warning">{attention.length}</strong>
            </Link>
            <Link to="/environments" className="overview-metric">
              <span>Environments</span>
              <strong>{data.taskenvs.length}</strong>
              <small>
                {available} available · {data.taskenvs.length - available}{" "}
                unavailable
              </small>
            </Link>
          </div>
          <div className="overview-grid">
            <section
              className="overview-section"
              aria-labelledby="service-distribution"
            >
              <h2 id="service-distribution">Services</h2>
              <p className="muted small">Recorded states by project.</p>
              <div className="service-distribution">
                {projects.map((project) => {
                  let offset = 0;
                  const total = Object.values(project.counts).reduce(
                    (sum, count) => sum + count,
                    0,
                  );
                  const summary =
                    serviceGroups
                      .filter((group) => project.counts[group.key])
                      .map(
                        (group) =>
                          `${project.counts[group.key]} ${group.label.toLowerCase()}`,
                      )
                      .join(", ") || "No recorded services";
                  return (
                    <Link
                      key={project.id}
                      to={projectLink(project.id)}
                      className="distribution-row"
                      aria-label={`${project.id}: ${summary}. View environments`}
                    >
                      <span className="distribution-project">{project.id}</span>
                      <svg
                        className="distribution-bar"
                        viewBox="0 0 100 12"
                        preserveAspectRatio="none"
                        aria-hidden="true"
                      >
                        <rect
                          width="100"
                          height="12"
                          className="distribution-track"
                        />
                        {serviceGroups.map((group) => {
                          const width =
                            (project.counts[group.key] / maximum) * 100;
                          const x = offset;
                          offset += width;
                          return (
                            <rect
                              key={group.key}
                              x={x}
                              width={width}
                              height="12"
                              className={`service-fill-${group.key}`}
                            />
                          );
                        })}
                      </svg>
                      <span className="distribution-total">{total}</span>
                    </Link>
                  );
                })}
              </div>
              <ul className="distribution-legend" aria-label="Service counts">
                {serviceGroups
                  .filter((group) => counts[group.key])
                  .map((group) => (
                    <li key={group.key}>
                      <span
                        className={`service-swatch service-fill-${group.key}`}
                        aria-hidden="true"
                      />
                      {group.label}: {counts[group.key]}
                    </li>
                  ))}
              </ul>
              {!serviceTotal && (
                <p className="muted small">No services recorded yet.</p>
              )}
            </section>
            <section
              className="overview-section"
              aria-labelledby="attention-queue"
            >
              <div className="overview-section-heading">
                <h2 id="attention-queue">Activity</h2>
                <span className="muted small">{queue.length} environments</span>
              </div>
              <div
                className="focus-filters"
                aria-label="Filter environment focus"
              >
                {[
                  ["attention", "Needs attention"],
                  ["running", "Running services"],
                  ["all", "All"],
                ].map(([key, label]) => (
                  <Button
                    key={key}
                    variant={focus === key ? "secondary" : "ghost"}
                    size="sm"
                    aria-pressed={focus === key}
                    onClick={() => setQuery({ focus: key })}
                  >
                    {label}
                  </Button>
                ))}
              </div>
              {queue.slice(0, 5).map((task) => (
                <Link
                  className="focus-row"
                  key={task.id}
                  to={environmentPath(task)}
                  aria-label={`${task.project} / ${taskLabel(task)}`}
                >
                  <div>
                    <small className="muted">{task.project}</small>
                    <strong>{taskLabel(task)}</strong>
                    <span
                      className={
                        focus === "attention" ? "focus-reason" : "muted small"
                      }
                    >
                      {focus === "attention"
                        ? attentionReasons(task).join(" · ")
                        : `${runningServices(task)} services running · ${task.state}`}
                    </span>
                  </div>
                  <ArrowUpRight size={16} />
                </Link>
              ))}
              {!queue.length && (
                <p className="focus-empty muted">
                  No environments match this view.
                </p>
              )}
              {queue.length > 5 && (
                <Button variant="ghost" size="sm" asChild>
                  <Link
                    to={`/environments${focus === "all" ? "" : `?status=${focus}`}`}
                  >
                    Show all <ArrowRight />
                  </Link>
                </Button>
              )}
              <p className="muted small overview-footnote">
                Running environments can still need attention.
              </p>
            </section>
          </div>
          <section
            className="overview-section project-overview"
            aria-labelledby="project-overview"
          >
            <div className="overview-section-heading">
              <h2 id="project-overview">Projects</h2>
              <Button asChild variant="ghost" size="sm">
                <Link to="/projects">
                  All projects <ArrowRight />
                </Link>
              </Button>
            </div>
            {projects.map((project) => {
              const present = project.tasks.filter(
                (task) => task.state === "present",
              ).length;
              return (
                <Link
                  className="project-overview-row"
                  key={project.id}
                  to={projectLink(project.id)}
                >
                  <span>
                    <FolderGit2 size={17} />
                    <strong>{project.id}</strong>
                  </span>
                  <span className="muted small">
                    {project.tasks.length
                      ? `${project.tasks.length} environment${project.tasks.length === 1 ? "" : "s"}${present < project.tasks.length ? ` · ${project.tasks.length - present} unavailable` : ""}`
                      : "No environments"}
                  </span>
                  <ArrowRight size={16} />
                </Link>
              );
            })}
          </section>
        </>
      )}
    </>
  );
}
