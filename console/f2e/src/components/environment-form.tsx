import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { useConsole } from "@/lib/console";
import { Plus, FolderInput, GitBranchPlus, ArrowLeft } from "lucide-react";

export function EnvironmentForm({
  kind,
  project,
  open: controlledOpen,
  onOpenChange,
  onCloseAutoFocus,
}: {
  kind: "project" | "create" | "attach" | "add";
  project?: string;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  onCloseAutoFocus?: (event: Event) => void;
}) {
  const { data, busy, perform, error } = useConsole();
  const [localOpen, setLocalOpen] = useState(false);
  const [choice, setChoice] = useState<"create" | "attach" | null>(null);
  const [submitted, setSubmitted] = useState(false);
  const navigate = useNavigate();
  const open = controlledOpen ?? localOpen;
  const formKind = kind === "add" ? choice : kind;
  function setOpen(value: boolean) {
    if (busy) return;
    setLocalOpen(value);
    onOpenChange?.(value);
    setSubmitted(false);
    if (!value) setChoice(null);
  }
  const title =
    formKind === "project"
      ? "Register project"
      : formKind === "create"
        ? "New worktree"
        : formKind === "attach"
          ? "Connect existing checkout"
          : "Add checkout";
  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setSubmitted(true);
    const fields = Object.fromEntries(
      [...new FormData(e.currentTarget)].filter(([, value]) => value !== ""),
    ) as Record<string, string>;
    const result = await perform(
      {
        action: formKind === "project" ? "project.add" : `worktree.${formKind}`,
        ...fields,
      },
      title,
    );
    if (result) {
      setOpen(false);
      if (formKind !== "project" && typeof result.id === "string")
        navigate(`/environments/${encodeURIComponent(result.id)}/services`);
    }
  }
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      {controlledOpen === undefined && (
        <DialogTrigger asChild>
          <Button
            variant={kind === "attach" ? "outline" : "default"}
            disabled={!!busy || (kind !== "project" && !data.projects.length)}
          >
            {kind === "attach" ? <FolderInput /> : <Plus />}
            {kind === "add" ? "Add checkout" : title}
          </Button>
        </DialogTrigger>
      )}
      <DialogContent onCloseAutoFocus={onCloseAutoFocus}>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>
            {formKind === "project"
              ? "Register a local Git repository. Existing configuration is preserved; a missing file gets a starter configuration."
              : formKind === "attach"
                ? "Register an existing main checkout or worktree from the same local repository. No code is copied. Prepare and service startup are separate actions."
                : "Create a new worktree or connect an existing checkout. Prepare and service startup are separate actions."}
          </DialogDescription>
        </DialogHeader>
        {kind === "add" && !choice ? (
          <div className="checkout-choices">
            <Button variant="outline" onClick={() => setChoice("create")}>
              <GitBranchPlus />
              <span>
                <strong>Create a new worktree</strong>
                <small>
                  Create a branch and a separate checkout for this project.
                </small>
              </span>
            </Button>
            <Button variant="outline" onClick={() => setChoice("attach")}>
              <FolderInput />
              <span>
                <strong>Connect existing checkout</strong>
                <small>
                  Register an existing main checkout or worktree in place.
                </small>
              </span>
            </Button>
          </div>
        ) : (
          <form className="stack-form" onSubmit={submit}>
            {kind === "add" && (
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={() => {
                  setChoice(null);
                  setSubmitted(false);
                }}
              >
                <ArrowLeft />
                Choose a different way
              </Button>
            )}
            {formKind === "project" ? (
              <label>
                Project name
                <Input name="name" required />
              </label>
            ) : (
              <label>
                Project
                <select name="project" defaultValue={project}>
                  {data.projects.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.id}
                    </option>
                  ))}
                </select>
              </label>
            )}
            {formKind !== "create" ? (
              <label>
                Absolute checkout path
                <Input
                  name="path"
                  required
                  placeholder="/Users/you/projects/repository"
                />
              </label>
            ) : (
              <>
                <label>
                  Starting Git ref
                  <Input name="ref" defaultValue="HEAD" required />
                </label>
                <label>
                  New branch
                  <Input
                    name="branch"
                    placeholder="feature/my-change"
                    required
                  />
                </label>
              </>
            )}
            <label>
              Configuration source{" "}
              <span className="muted font-normal">Optional</span>
              <Input
                name="config"
                placeholder="/absolute/path/to/project.toml"
              />
            </label>
            {submitted && error && (
              <p className="feedback feedback-error" role="alert">
                {error}
              </p>
            )}
            <div className="actions justify-end">
              <Button
                type="button"
                variant="outline"
                disabled={!!busy}
                onClick={() => setOpen(false)}
              >
                Cancel
              </Button>
              <Button disabled={!!busy}>{busy || title}</Button>
            </div>
          </form>
        )}
      </DialogContent>
    </Dialog>
  );
}
