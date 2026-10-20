import { useRef, useState } from "react";
import { Link, Navigate, useNavigate, useParams } from "react-router-dom";
import {
  ArrowLeft,
  ArrowUpRight,
  FileText,
  GitBranch,
  Play,
  Square,
  Terminal,
  Trash2,
  Unlink,
  X,
} from "lucide-react";
import type { Action, Detail } from "@/api";
import { useConsole } from "@/lib/console";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
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
  RawData,
  State,
  Values,
  taskLabel,
} from "@/components/shared";
import {
  ConfirmationDialog,
  type Confirmation,
} from "@/components/confirmation";

const sections = [
  "services",
  "operations",
  "configuration",
  "resources",
  "cleanup",
];

export function EnvironmentDetail() {
  const { id, tab = "services" } = useParams();
  const { detail, loading } = useConsole();
  if (loading || (detail && detail.id !== id)) return <Loading />;
  if (!detail)
    return (
      <Empty
        title="Environment unavailable"
        action={
          <Button asChild variant="outline">
            <Link to="/environments">Back to environments</Link>
          </Button>
        }
      >
        This environment is no longer registered, or its details could not be
        loaded. Refresh to try again.
      </Empty>
    );
  if (!sections.includes(tab))
    return (
      <Navigate
        replace
        to={`/environments/${encodeURIComponent(detail.id)}/services`}
      />
    );
  return <DetailContent key={detail.id} detail={detail} tab={tab} />;
}

function DetailContent({ detail, tab }: { detail: Detail; tab: string }) {
  const { busy, perform } = useConsole();
  const navigate = useNavigate();
  const [confirmation, setConfirmation] = useState<Confirmation | null>(null);
  const [logs, setLogs] = useState<{
    title: string;
    text: string;
    loading: boolean;
  } | null>(null);
  const logRequest = useRef(0);
  const logPanel = useRef<HTMLElement>(null);
  const services = [
    ...new Set([
      ...(detail.configured_services || []),
      ...detail.services.map((s) => s.name),
    ]),
  ];
  const operations = [...detail.operations].sort((a, b) =>
    b.started_at.localeCompare(a.started_at),
  );
  const working = operations.filter((op) =>
    ["running", "starting"].includes(op.state),
  );
  async function showLogs(action: Action, title: string) {
    const version = ++logRequest.current;
    setLogs({ title, text: "", loading: true });
    requestAnimationFrame(() => logPanel.current?.focus());
    const result = await perform(action, title, true);
    if (version === logRequest.current)
      setLogs({
        title,
        text: result
          ? String(result.tail || "No output recorded.")
          : "Could not load output. See the error above and retry explicitly.",
        loading: false,
      });
  }
  async function preview(action: Action) {
    const result = await perform(action, "Preview", true);
    if (result) setConfirmation({ action, preview: result });
  }
  function run(name: string) {
    navigate(`/environments/${encodeURIComponent(detail.id)}/operations`);
    void perform(
      {
        action: name === "prepare" ? "prepare" : "run",
        name,
        target: detail.id,
      },
      `Run ${name}`,
    );
  }
  return (
    <div className="detail">
      <Link
        className="back-link"
        to={`/environments?project=${encodeURIComponent(detail.project)}`}
      >
        <ArrowLeft size={14} />
        {detail.project} environments
      </Link>
      <div className="detail-heading">
        <div>
          <div className="detail-title">
            <GitBranch size={24} />
            <h1>{taskLabel(detail)}</h1>
          </div>
          <div className="detail-meta">
            <State value={detail.state} checkout />
            <span>
              {detail.main
                ? "Main checkout"
                : detail.owned
                  ? "Managed worktree"
                  : "Attached checkout"}
            </span>
            <code>ID {detail.id}</code>
          </div>
        </div>
      </div>
      <div className="checkout-path">
        <span className="muted">Checkout</span>
        <code>{detail.path}</code>
      </div>
      {detail.configuration_error && (
        <div role="alert" className="feedback feedback-error">
          <strong>Configuration needs attention</strong>
          <p>{detail.configuration_error.message}</p>
          <p>Recorded services and resources remain available below.</p>
        </div>
      )}
      {!!working.length && !busy && (
        <div className="feedback" role="status">
          {working.length} operation in progress. Open Operations to inspect
          recorded results; reopening this page does not rerun commands.
        </div>
      )}
      <Tabs
        activationMode="manual"
        value={tab}
        onValueChange={(value) => {
          setLogs(null);
          logRequest.current++;
          navigate(`/environments/${encodeURIComponent(detail.id)}/${value}`);
        }}
      >
        <TabsList className="detail-tabs" aria-label="Environment sections">
          {sections.map((value) => (
            <TabsTrigger key={value} value={value}>
              {value === "cleanup"
                ? "Cleanup & removal"
                : value[0].toUpperCase() + value.slice(1)}
            </TabsTrigger>
          ))}
        </TabsList>
        <TabsContent value="services">
          <div className="section-heading">
            <div>
              <h2>
                Services <span className="muted">{services.length}</span>
              </h2>
              <p className="muted">
                Start, inspect and stop this environment’s processes.
              </p>
            </div>
            <span className="small muted">Observed every 3 seconds</span>
          </div>
          {!services.length ? (
            <Empty
              title="No services configured"
              action={
                <Button
                  variant="outline"
                  onClick={() =>
                    navigate(
                      `/environments/${encodeURIComponent(detail.id)}/operations`,
                    )
                  }
                >
                  View commands <ArrowUpRight />
                </Button>
              }
            >
              This repository may only need prepare or verify. Add services to
              its project.toml when needed.
            </Empty>
          ) : (
            <div className="service-list">
              {services.map((name) => {
                const service = detail.services.find((s) => s.name === name);
                const canStart =
                  !busy &&
                  detail.configured_services?.includes(name) &&
                  detail.state === "present" &&
                  !["running", "starting", "stopping", "unknown"].includes(
                    service?.state || "",
                  );
                const canStop =
                  !busy &&
                  service &&
                  !["stopped", "exited", "failed"].includes(service.state);
                return (
                  <div className="service-row" key={name}>
                    <div className="service-info">
                      <div className="service-name">
                        <Terminal size={17} />
                        <h3>{name}</h3>
                        <State value={service?.state || "not started"} />
                      </div>
                      {service?.url && (
                        <a
                          className="service-url"
                          href={service.url}
                          target="_blank"
                          rel="noreferrer"
                        >
                          {service.url}
                          <ArrowUpRight size={14} />
                        </a>
                      )}
                      {service?.warning && (
                        <p className="muted small">{service.warning}</p>
                      )}
                    </div>
                    {service?.state !== "external" && (
                      <div className="actions">
                        <Button
                          variant="outline"
                          size="sm"
                          disabled={!canStart}
                          title={
                            !canStart
                              ? "Requires a valid configuration, available checkout and resolved service state"
                              : undefined
                          }
                          onClick={() =>
                            void perform(
                              {
                                action: "service.start",
                                target: detail.id,
                                name,
                              },
                              `Start ${name}`,
                            )
                          }
                        >
                          <Play />
                          Start
                        </Button>
                        <Button
                          variant="outline"
                          size="sm"
                          disabled={!canStop}
                          onClick={() =>
                            void perform(
                              {
                                action: "service.stop",
                                target: detail.id,
                                name,
                              },
                              `Stop ${name}`,
                            )
                          }
                        >
                          <Square />
                          Stop
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          disabled={!service}
                          onClick={() =>
                            void showLogs(
                              {
                                action: "service.logs",
                                target: detail.id,
                                name,
                              },
                              `${name} logs`,
                            )
                          }
                        >
                          <FileText />
                          Logs
                        </Button>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </TabsContent>
        <TabsContent value="operations">
          <div className="section-heading">
            <div>
              <h2>Repository commands</h2>
              <p className="muted">
                Run the commands configured in this checkout. Cleanup has its
                own section.
              </p>
            </div>
          </div>
          <div className="command-bar">
            {(detail.commands || [])
              .filter((n) => n !== "cleanup")
              .map((name) => (
                <Button
                  key={name}
                  variant={name === "prepare" ? "default" : "outline"}
                  disabled={!!busy || detail.state !== "present"}
                  onClick={() => run(name)}
                >
                  <Play />
                  {name}
                </Button>
              ))}
            {!detail.commands?.some((n) => n !== "cleanup") && (
              <p className="muted">
                No runnable commands available. Check this checkout’s
                configuration.
              </p>
            )}
          </div>
          <div className="section-heading">
            <div>
              <h2>Execution history</h2>
              <p className="muted">
                Recorded outcomes across the CLI and console.
              </p>
            </div>
          </div>
          {!operations.length ? (
            <Empty title="No operations yet">
              Run a configured command above. Its output and exit status will
              appear here.
            </Empty>
          ) : (
            <div className="data-panel">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Command</TableHead>
                    <TableHead>State</TableHead>
                    <TableHead>Started</TableHead>
                    <TableHead>Exit code</TableHead>
                    <TableHead>
                      <span className="sr-only">Output</span>
                    </TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {operations.map((op) => (
                    <TableRow key={op.id}>
                      <TableCell className="font-medium">
                        {op.command}
                      </TableCell>
                      <TableCell>
                        <State value={op.state} />
                      </TableCell>
                      <TableCell>
                        {new Date(op.started_at).toLocaleString()}
                      </TableCell>
                      <TableCell>
                        <code>{op.exit_code ?? "—"}</code>
                      </TableCell>
                      <TableCell className="text-right">
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() =>
                            void showLogs(
                              { action: "operation.logs", target: op.id },
                              `${op.command} logs`,
                            )
                          }
                        >
                          <FileText />
                          Logs
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
          {operations.some((op) =>
            ["unknown", "interrupted"].includes(op.state),
          ) && (
            <p className="feedback feedback-warning">
              An operation has an interrupted or unknown outcome. Inspect its
              output and resources before explicitly running it again.
            </p>
          )}
        </TabsContent>
        <TabsContent value="configuration">
          <Configuration detail={detail} />
        </TabsContent>
        <TabsContent value="resources">
          <div className="section-heading">
            <div>
              <h2>Known resources</h2>
              <p className="muted">
                Repository-reported observations, not a complete resource
                inventory.
              </p>
            </div>
          </div>
          {!detail.known_resources.length ? (
            <Empty title="No resources reported">
              Resources reported by repository commands will appear here.
            </Empty>
          ) : (
            <div className="data-panel">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Name / ID</TableHead>
                    <TableHead>Kind</TableHead>
                    <TableHead>Scope</TableHead>
                    <TableHead>State</TableHead>
                    <TableHead>Observed</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {detail.known_resources.map((r, i) => (
                    <TableRow key={i}>
                      <TableCell>
                        {r.name}
                        <code className="cell-secondary">{r.id}</code>
                      </TableCell>
                      <TableCell>{r.kind}</TableCell>
                      <TableCell>{r.scope}</TableCell>
                      <TableCell>
                        <State value={r.state} />
                      </TableCell>
                      <TableCell>
                        {r.observed_at
                          ? new Date(r.observed_at).toLocaleString()
                          : "—"}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
          <RawData value={detail.known_resources} />
        </TabsContent>
        <TabsContent value="cleanup">
          <div className="section-heading">
            <div>
              <h2>Cleanup and removal</h2>
              <p className="muted">
                These are separate actions. Review the scope before each one.
              </p>
            </div>
          </div>
          <div className="danger-list">
            <div>
              <div>
                <h3>Run repository cleanup</h3>
                <p className="muted">
                  Executes the repo’s cleanup command. It does not automatically
                  stop services or delete the worktree.
                </p>
                {!detail.cleanup.available && (
                  <p className="small muted">
                    {detail.cleanup.reason || "No cleanup command available."}
                  </p>
                )}
              </div>
              <Button
                variant="outline"
                disabled={
                  !!busy ||
                  !detail.cleanup.available ||
                  detail.state !== "present"
                }
                onClick={() =>
                  setConfirmation({
                    action: { action: "cleanup", target: detail.id },
                    preview: {
                      path: detail.path,
                      services: detail.services,
                      known_resources: detail.known_resources,
                      warning:
                        "Runs the repository cleanup command. Stop services first; this may delete project data.",
                    },
                  })
                }
              >
                <Play />
                Run cleanup
              </Button>
            </div>
            <div>
              <div>
                <h3>Remove worktree</h3>
                <p className="muted">
                  Deletes a Lodex-managed checkout, including ignored files. The
                  Git branch and registry record are retained.
                </p>
                {(!detail.owned ||
                  detail.main ||
                  detail.state !== "present") && (
                  <p className="small muted">
                    Removal requires an available, Lodex-managed worktree. Main
                    and attached checkouts cannot be removed.
                  </p>
                )}
              </div>
              <Button
                variant="outline"
                className="text-destructive"
                disabled={
                  !!busy ||
                  !detail.owned ||
                  detail.main ||
                  detail.state !== "present"
                }
                onClick={() =>
                  void preview({ action: "worktree.remove", target: detail.id })
                }
              >
                <Trash2 />
                Preview removal
              </Button>
            </div>
            <div>
              <div>
                <h3>Forget registration</h3>
                <p className="muted">
                  Removes the registry entry. Files, services, external
                  resources and shared secrets remain.
                </p>
              </div>
              <Button
                variant="outline"
                disabled={!!busy}
                onClick={() =>
                  void preview({ action: "worktree.forget", target: detail.id })
                }
              >
                <Unlink />
                Forget registration
              </Button>
            </div>
          </div>
        </TabsContent>
      </Tabs>
      {logs && (
        <section
          ref={logPanel}
          tabIndex={-1}
          className="log-panel"
          aria-label={logs.title}
        >
          <div className="section-heading">
            <h2>
              <Terminal size={16} />
              {logs.title}
            </h2>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                logRequest.current++;
                setLogs(null);
              }}
            >
              <X />
              Close logs
            </Button>
          </div>
          <p className="muted small">
            Output snapshot. Select Logs again to refresh.
          </p>
          <pre aria-live="polite">
            {logs.loading ? "Loading output…" : logs.text}
          </pre>
        </section>
      )}
      <ConfirmationDialog
        confirmation={confirmation}
        onClose={() => setConfirmation(null)}
        onDone={() => {
          if (
            confirmation?.action.action === "worktree.remove" ||
            confirmation?.action.action === "worktree.forget"
          )
            navigate("/environments");
          else
            navigate(
              `/environments/${encodeURIComponent(detail.id)}/operations`,
            );
        }}
      />
    </div>
  );
}

function Configuration({ detail }: { detail: Detail }) {
  const { data, busy, perform } = useConsole();
  return (
    <>
      <div className="section-heading">
        <div>
          <h2>Configuration</h2>
          <p className="muted">
            Edit this checkout’s TOML. Each new operation reads the file
            directly.
          </p>
        </div>
      </div>
      <dl className="configuration-paths">
        <dt>Local file</dt>
        <dd>
          <code>{detail.configuration_path}</code>
        </dd>
        <dt>Source</dt>
        <dd>
          <code>
            {detail.config_source?.source ||
              data.projects.find((p) => p.id === detail.project)?.source ||
              "Local configuration"}
          </code>
        </dd>
      </dl>
      {detail.environment && (
        <>
          <div className="section-heading">
            <div>
              <h2>Resolved environment</h2>
              <p className="muted">
                Allocated values and current configuration. Secret values are
                excluded.
              </p>
            </div>
            <Button
              variant="outline"
              disabled={!!busy}
              onClick={() =>
                void perform(
                  { action: "env.export", target: detail.id },
                  "Export .env",
                )
              }
            >
              <FileText />
              Export .env
            </Button>
          </div>
          <div className="data-panel">
            <Values values={detail.environment.values} />
          </div>
          <div className="section-heading">
            <div>
              <h2>Secret references</h2>
              <p className="muted">
                Manage stored values on the{" "}
                <Link className="text-link" to="/secrets">
                  Secrets page
                </Link>
                .
              </p>
            </div>
          </div>
          {Object.keys(detail.environment.secret_refs).length ? (
            <div className="data-panel">
              <Values
                values={detail.environment.secret_refs}
                label="Reference"
              />
            </div>
          ) : (
            <p className="muted">No secret references configured.</p>
          )}
          <section className="form-section mt-8">
            <h2>Port allocation</h2>
            <p className="muted">
              Update a port key declared in project.toml. This does not restart
              running services.
            </p>
            <form
              className="inline-form"
              onSubmit={(e) => {
                e.preventDefault();
                const fields = new FormData(e.currentTarget);
                void perform(
                  {
                    action: "port.set",
                    target: detail.id,
                    name: String(fields.get("name")),
                    value: String(fields.get("value")),
                  },
                  "Update port",
                );
              }}
            >
              <label>
                Port key
                <Input name="name" required placeholder="PORT" />
              </label>
              <label>
                Port
                <Input
                  name="value"
                  type="number"
                  min="1"
                  max="65535"
                  required
                />
              </label>
              <Button variant="outline" disabled={!!busy}>
                Set port
              </Button>
            </form>
          </section>
        </>
      )}
    </>
  );
}
