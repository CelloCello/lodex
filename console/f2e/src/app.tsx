import { useEffect, useRef, useState } from "react";
import {
  Link,
  NavLink,
  Navigate,
  Route,
  Routes,
  matchPath,
  useLocation,
} from "react-router-dom";
import {
  Boxes,
  Check,
  ChevronRight,
  FolderGit2,
  KeyRound,
  LoaderCircle,
  Menu,
  Monitor,
  RefreshCw,
  Terminal,
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
import { taskLabel } from "@/components/shared";
import { useTheme, type Theme } from "@/lib/theme";

export function App() {
  const { theme, changeTheme } = useTheme();
  const location = useLocation();
  const target = matchPath("/environments/:id/*", location.pathname)?.params.id;
  const state = useConsoleState(target);
  const [menu, setMenu] = useState(false);
  const main = useRef<HTMLElement>(null);
  const section = location.pathname.startsWith("/projects")
    ? "Projects"
    : location.pathname.startsWith("/secrets")
      ? "Secrets"
      : "Environments";
  useEffect(() => {
    setMenu(false);
  }, [location.pathname]);
  useEffect(() => {
    main.current?.focus({ preventScroll: true });
  }, [section, target]);
  useEffect(() => {
    document.title = `${target && state.detail?.id === target ? taskLabel(state.detail) : section} · Lodex`;
  }, [section, target, state.detail?.branch, state.detail?.id]);
  const navigation = (
    <nav aria-label="Main navigation">
      <NavLink to="/environments">
        <Boxes />
        Environments<span>{state.data.taskenvs.length}</span>
      </NavLink>
      <NavLink to="/projects">
        <FolderGit2 />
        Projects<span>{state.data.projects.length}</span>
      </NavLink>
      <NavLink to="/secrets">
        <KeyRound />
        Secrets<span>{state.data.secrets.length}</span>
      </NavLink>
    </nav>
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
          <Link className="brand" to="/environments">
            <span className="brand-mark">
              <Terminal size={20} />
            </span>
            lodex<span className="brand-caption">Console</span>
          </Link>
          {navigation}
          <div className="sidebar-footer">
            <div>
              <Monitor size={15} />
              <span>Local workspace</span>
            </div>
            <p>
              Shared with your CLI.
              <br />
              Services stay running when you leave.
            </p>
          </div>
        </aside>
        <div className="main-shell">
          <header className="topbar">
            <div className="breadcrumbs">
              <Button
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
              <Link to={`/${section.toLowerCase()}`}>{section}</Link>
              {target && (
                <>
                  <ChevronRight size={13} className="muted" />
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
              <Route path="/environments" element={<Environments />} />
              <Route
                path="/environments/:id/:tab?"
                element={<EnvironmentDetail />}
              />
              <Route path="/projects" element={<Projects />} />
              <Route path="/secrets" element={<Secrets />} />
              <Route
                path="*"
                element={<Navigate replace to="/environments" />}
              />
            </Routes>
          </main>
        </div>
        <Dialog open={menu} onOpenChange={setMenu}>
          <DialogContent className="mobile-navigation">
            <DialogHeader>
              <DialogTitle>lodex</DialogTitle>
              <DialogDescription>Local workspace console</DialogDescription>
            </DialogHeader>
            {navigation}
          </DialogContent>
        </Dialog>
      </div>
    </ConsoleContext.Provider>
  );
}
