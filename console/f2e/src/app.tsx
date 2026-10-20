import { useEffect, useRef, useState } from "react";
import {
  Link,
  Navigate,
  Route,
  Routes,
  matchPath,
  useLocation,
  useNavigate,
} from "react-router-dom";
import {
  Check,
  ChevronRight,
  LoaderCircle,
  Menu,
  Monitor,
  RefreshCw,
  X,
} from "lucide-react";
import { ConsoleContext, useConsoleState } from "@/lib/console";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Environments, Projects } from "@/pages/environments";
import { EnvironmentDetail } from "@/pages/environment-detail";
import { Secrets } from "@/pages/secrets";
import { Dashboard } from "@/pages/dashboard";
import {
  ProjectNavigation,
  useProjectNavigation,
} from "@/components/project-navigation";
import { EnvironmentForm } from "@/components/environment-form";
import { taskLabel } from "@/components/shared";
import { useTheme, type Theme } from "@/lib/theme";
import { projectLabel } from "@/lib/projects";
import { ProjectNameDialog } from "@/components/project-name-dialog";
import {
  ConfirmationDialog,
  type Confirmation,
} from "@/components/confirmation";

export function App() {
  const { theme, changeTheme } = useTheme();
  const location = useLocation();
  const navigate = useNavigate();
  const [deletion, setDeletion] = useState<Confirmation | null>(null);
  const target = matchPath("/environments/:id/*", location.pathname)?.params.id;
  const projectTarget = matchPath("/projects/:id", location.pathname)?.params
    .id;
  const selectedProject =
    projectTarget ||
    (location.pathname === "/environments"
      ? new URLSearchParams(location.search).get("project") || undefined
      : undefined);
  const state = useConsoleState(target);
  const [menu, setMenu] = useState(false);
  const [form, setForm] = useState<{
    kind: "add" | "project" | "rename";
    project?: string;
  } | null>(null);
  const editingProject =
    form?.kind === "rename"
      ? state.data.projects.find((project) => project.id === form.project)
      : undefined;
  const projectNavigation = useProjectNavigation(
    state.data,
    target,
    selectedProject,
  );
  const main = useRef<HTMLElement>(null);
  const mobileMenu = useRef<HTMLButtonElement>(null);
  const formTrigger = useRef<HTMLElement | null>(null);
  function editProject(project: string, trigger: HTMLButtonElement) {
    formTrigger.current = menu ? mobileMenu.current : trigger;
    setMenu(false);
    setForm({ kind: "rename", project });
  }
  const section = location.pathname.startsWith("/projects")
    ? "Projects"
    : location.pathname.startsWith("/secrets")
      ? "Secrets"
      : location.pathname.startsWith("/environments")
        ? "Environments"
        : "Overview";
  useEffect(() => {
    setMenu(false);
  }, [location.pathname]);
  useEffect(() => {
    main.current?.focus({ preventScroll: true });
  }, [section, target, projectTarget]);
  useEffect(() => {
    document.title = `${selectedProject ? projectLabel(state.data.projects, selectedProject) : target && state.detail?.id === target ? taskLabel(state.detail) : section} · Lodex`;
  }, [
    section,
    target,
    projectTarget,
    selectedProject,
    state.data.projects,
    state.detail?.branch,
    state.detail?.id,
    state.detail?.path,
    state.detail?.state,
    state.detail?.head,
    state.detail?.git_error,
  ]);
  const navigation = (
    <ProjectNavigation
      data={state.data}
      target={target}
      navigation={projectNavigation}
      busy={!!state.busy}
      onNavigate={() => {
        setMenu(false);
        requestAnimationFrame(() =>
          main.current?.focus({ preventScroll: true }),
        );
      }}
      onAdd={(project, trigger) => {
        formTrigger.current = menu ? mobileMenu.current : trigger;
        setMenu(false);
        setForm({ kind: "add", project });
      }}
      onRegister={(trigger) => {
        formTrigger.current = menu ? mobileMenu.current : trigger;
        setMenu(false);
        setForm({ kind: "project" });
      }}
      onEdit={editProject}
      onPin={(project, pinned) => {
        void state.perform(
          { action: "project.pin", project, pinned },
          pinned ? "Pin project" : "Unpin project",
        );
      }}
      onDelete={async (project, trigger) => {
        formTrigger.current = menu ? mobileMenu.current : trigger;
        setMenu(false);
        const action = { action: "project.delete", project };
        const preview = await state.perform(
          action,
          "Preview project deletion",
          true,
        );
        if (preview) setDeletion({ action, preview });
        else formTrigger.current?.focus();
      }}
    />
  );
  return (
    <ConsoleContext.Provider value={state}>
      <a
        className="skip-link"
        href="#main-content"
        onClick={(e) => {
          e.preventDefault();
          main.current?.focus();
        }}
      >
        Skip to content
      </a>
      <div className="app-shell">
        <aside className="sidebar">
          <Link className="brand" to="/dashboard">
            <img
              className="brand-mark"
              src="/lodex-logo.svg"
              width="32"
              height="32"
              alt=""
            />
            lodex<span className="brand-caption">Console</span>
          </Link>
          {navigation}
        </aside>
        <div className="main-shell">
          <header className="topbar">
            <div className="breadcrumbs">
              <Button
                ref={mobileMenu}
                className="mobile-menu"
                variant="ghost"
                size="icon"
                aria-label="Open navigation"
                onClick={() => setMenu(true)}
              >
                <Menu />
              </Button>
              <Monitor size={15} className="muted desktop-icon" />
              <ChevronRight size={13} className="muted desktop-icon" />
              {!target && !selectedProject && (
                <Link
                  to={
                    section === "Overview"
                      ? "/dashboard"
                      : `/${section.toLowerCase()}`
                  }
                >
                  {section}
                </Link>
              )}
              {target && state.detail && (
                <>
                  <Link
                    className="breadcrumb-project"
                    to={`/environments?project=${encodeURIComponent(state.detail.project)}`}
                  >
                    {projectLabel(state.data.projects, state.detail.project)}
                  </Link>
                </>
              )}
              {selectedProject && !target && (
                <>
                  <span className="breadcrumb-current">
                    {projectLabel(state.data.projects, selectedProject)}
                  </span>
                </>
              )}
              {target && (
                <>
                  {state.detail && <ChevronRight size={13} className="muted" />}
                  <span className="breadcrumb-current">
                    {state.detail ? taskLabel(state.detail) : "Environment"}
                  </span>
                </>
              )}
            </div>
            <div className="actions">
              <span className="sync-label muted">
                {state.observed
                  ? `Checked ${state.observed.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}`
                  : "Connecting…"}
              </span>
              <Button
                variant="ghost"
                size="sm"
                aria-label="Refresh"
                onClick={() => void state.refresh()}
              >
                <RefreshCw />
                <span className="refresh-label">Refresh</span>
              </Button>
              <select
                className="theme-select"
                aria-label="Color theme"
                value={theme}
                onChange={(event) => changeTheme(event.target.value as Theme)}
              >
                <option value="system">System</option>
                <option value="light">Light</option>
                <option value="dark">Dark</option>
              </select>
            </div>
          </header>
          <main
            ref={main}
            tabIndex={-1}
            id="main-content"
            className="page-content"
          >
            {state.error && (
              <div role="alert" className="feedback feedback-error">
                <span>{state.error}</span>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  aria-label="Dismiss error"
                  onClick={() => state.setError("")}
                >
                  <X />
                </Button>
              </div>
            )}
            {state.notice && (
              <div role="status" className="feedback feedback-success">
                <Check size={17} />
                <span>{state.notice}</span>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  aria-label="Dismiss notice"
                  onClick={() => state.setNotice("")}
                >
                  <X />
                </Button>
              </div>
            )}
            {state.busy && (
              <div role="status" className="feedback">
                <LoaderCircle size={16} className="animate-spin" />
                <span>
                  Operation in progress: {state.busy}. You can inspect recorded
                  results while it runs.
                </span>
              </div>
            )}
            <Routes>
              <Route path="/dashboard" element={<Dashboard />} />
              <Route
                path="/environments"
                element={<Environments onEdit={editProject} />}
              />
              <Route
                path="/environments/:id/:tab?"
                element={<EnvironmentDetail />}
              />
              <Route path="/projects" element={<Projects />} />
              <Route
                path="/projects/:id"
                element={
                  <Navigate
                    replace
                    to={`/environments?project=${encodeURIComponent(projectTarget || "")}`}
                  />
                }
              />
              <Route path="/secrets" element={<Secrets />} />
              <Route path="*" element={<Navigate replace to="/dashboard" />} />
            </Routes>
          </main>
        </div>
        <Dialog open={menu} onOpenChange={setMenu}>
          <DialogContent
            className="mobile-navigation"
            onCloseAutoFocus={(event) => {
              event.preventDefault();
              const anotherDialog = document.querySelector(
                '[role="dialog"][data-state="open"]',
              );
              if (
                !anotherDialog &&
                !main.current?.contains(document.activeElement)
              )
                mobileMenu.current?.focus();
            }}
          >
            <DialogHeader>
              <DialogTitle className="brand">
                <img
                  className="brand-mark"
                  src="/lodex-logo.svg"
                  width="32"
                  height="32"
                  alt=""
                />
                lodex
              </DialogTitle>
              <DialogDescription>
                Local environments for work with your coding agent.
              </DialogDescription>
            </DialogHeader>
            {navigation}
          </DialogContent>
        </Dialog>
        <ConfirmationDialog
          confirmation={deletion}
          onClose={() => setDeletion(null)}
          onDone={() => {
            if (selectedProject === deletion?.action.project)
              navigate("/dashboard");
          }}
          onCloseAutoFocus={(event) => {
            event.preventDefault();
            if (formTrigger.current?.isConnected) formTrigger.current.focus();
            else main.current?.focus();
          }}
        />
        {editingProject && (
          <ProjectNameDialog
            key={editingProject.id}
            project={editingProject}
            onClose={() => setForm(null)}
            onCloseAutoFocus={(event) => {
              event.preventDefault();
              if (formTrigger.current?.isConnected) formTrigger.current.focus();
              else main.current?.focus();
            }}
          />
        )}
        {form && form.kind !== "rename" && (
          <EnvironmentForm
            key={`${form.kind}:${form.project || ""}`}
            kind={form.kind}
            project={form.project}
            open
            onOpenChange={(open) => {
              if (!open) setForm(null);
            }}
            onCloseAutoFocus={(event) => {
              event.preventDefault();
              if (formTrigger.current?.isConnected) formTrigger.current.focus();
              else main.current?.focus();
            }}
          />
        )}
      </div>
    </ConsoleContext.Provider>
  );
}
