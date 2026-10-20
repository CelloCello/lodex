# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Developers working with coding agents across local repositories and worktrees,
switching between terminal, agent and browser. They need to identify a local
environment, prepare it, inspect services and execution results, and stop or clean
it deliberately.
They also use session history to retrieve earlier coding-agent discussions and evidence.
The browser console is an optional companion to the independently usable CLI.

## Product Purpose

Help developers and their coding agents set up task checkouts, run project
commands and services, and recover useful context from earlier agent sessions.
A developer or agent can find the same environment by checkout path or stable ID,
inspect its recorded state, and explicitly choose the next operation. History
retrieval provides earlier discussions and evidence through a separate workflow.

Success means developers can operate multiple environments independently, understand
known results and unresolved outcomes, and recover relevant historical context.
It does not mean Lodex makes development, review or Git integration decisions for them.

## Positioning

Lodex is a local toolkit for developers working with coding agents. The CLI
provides environment and history tools; optional skills guide agents in using
them, MCP exposes read-only history retrieval, and an optional web console lets
developers inspect and operate the same local environments. These interfaces use
a shared Python core.

Environment identity and service management belong to the local environment, not
to a particular coding-agent session. Repositories describe their own commands and
services in each checkout's `.lodex/project.toml`; Lodex supplies environment values,
executes explicit requests, and records known outcomes.

Session history has separate configuration and storage under the shared
`LODEX_HOME/history` default. Environment management
does not depend on Codex, Ollama or the history index. Lodex is not a task tracker,
agent orchestrator, hosted control plane or general workflow engine.

## Operating Context

- Developers alternate between the terminal, coding agents and the local browser
  console. CLI and Console Server call the same Python core and management database.
- A project is a registered local Git repository. A taskenv associates one checkout
  with settings, allocated values, services, known resources and operation records.
  A branch name is observed context, not the environment's identity.
- Registering a project, creating or attaching a checkout, preparing it, starting
  services, cleaning resources, removing a worktree and forgetting registration are
  distinct actions. Repository capabilities determine which actions are available.
- Each operation reads the checkout's current TOML. Configuration files are local
  to each worktree; missing-file provisioning is not ongoing synchronization.
- The console is served on loopback with bundled assets. Installed use needs no
  Node.js or Vite server. Closing the console does not stop managed services.
- History indexes coding-agent transcripts for local full-text and embedding-based
  retrieval. The bundled source adapter reads Codex sessions; history indexing and
  hybrid search use Ollama, and the current MCP interface exposes history retrieval.

## Capabilities and Constraints

- Management includes project registration, worktree creation and attachment,
  per-environment values and ports, repository commands, service start/stop/URLs/logs,
  recorded results, cleanup, worktree removal and registration removal.
- Shared secrets are managed by stored name independently of projects and taskenvs.
  They are stored in plaintext in the local management SQLite database under private
  permissions. Normal queries and the console never return secret values. Updating
  a value does not change a running process's environment.
- Console access uses a per-server token and loopback/origin protections. The token
  must not become part of ordinary routes, logs or shared links. Preserve the strict
  content security policy and bundled-asset model.
- Commands require explicit submission. Reopening a page inspects recorded state;
  it must not replay writes. There is no durable queue, automatic recovery or general
  retry guarantee. Interrupted and unknown outcomes must remain distinguishable.
- Cleanup runs repository code; it does not implicitly stop services or remove a
  checkout. Worktree removal retains evidence records and the Git branch. Forgetting
  registration does not delete files, stop services or remove shared secrets.
- Main and attached checkouts are protected from worktree removal. Force removal
  is a separate, explicit choice after reviewing Git state and affected scope.
- Isolation is cooperative on one host: Lodex allocates values, repositories use
  them correctly, and real integration tests establish what is isolated. Do not
  imply arbitrary sandbox isolation, cloud coordination or universal OS support;
  process supervision and locking currently rely on POSIX APIs.

## Brand Commitments

The product name is Lodex. The Console uses shadcn/ui, with shadcn-admin as a
confirmed reference for its application structure and interaction conventions.
Those references do not expand Lodex into the admin template's example domains.
Use neutral surfaces and action colors in both light and dark modes. Reserve
green, amber and red for operational status, always accompanied by text or icons.

## Brand Personality

Direct, calm, precise. Operational facts take priority over decoration.

## Anti-references

Avoid marketing dashboards, decorative metric cards and task/agent orchestration
interfaces. Never present an unknown service or command outcome as success.

## Evidence on Hand

- [README](README.md): product workflows, requirements, installation and entry points.
- [Management reference](docs/management.md): command and configuration contracts.
- [History reference](docs/history.md): indexing, search and history MCP behavior.
- [Console guide](docs/console.md) and [frontend guide](console/f2e/README.md):
  navigation, operation semantics, UI implementation and local development.
- [Architecture](docs/architecture.md): shared core, interface boundaries and storage.
- `console/f2e/tests/` and `console/tests/browser_fixture.py`: isolated browser
  demonstrations and CLI/Console integration coverage. Generated screenshots use
  fixture data and are not evidence of real customer usage or production deployments.
- [Multi-service fixture](examples/multi_service/README.md): self-contained environment isolation validation.
  Run `uv run python scripts/verify_environments.py` to exercise two isolated
  fixture environments through the public CLI. The fixture guide documents the
  database, queue, service and cleanup checks and their limits. These checks do
  not establish isolation for another repository or external services.

Do not invent customers, testimonials, performance claims or stronger isolation
and recovery guarantees than the available evidence supports.

## Product Principles

- Start with projects and environments; show the selected checkout and identity.
- Place actions next to the state they change, with explicit progress and errors.
- Show destructive scope before confirmation; keep force removal a separate choice.
- Preserve context when an operation fails or the page reopens; never replay writes.
- Match the repository's configured capabilities, including service-free projects.

## Accessibility & Inclusion

Use semantic controls, visible keyboard focus, labelled inputs, readable contrast,
status text in addition to color, and reduced-motion support. These are implementation
baselines; formal WCAG certification is not claimed.
