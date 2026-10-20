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
import { Plus, FolderInput } from "lucide-react";

export function EnvironmentForm({
  kind,
  project,
}: {
  kind: "project" | "create" | "attach";
  project?: string;
}) {
  const { data, busy, perform, error } = useConsole();
  const [open, setOpen] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const navigate = useNavigate();
  const title =
    kind === "project"
      ? "Register project"
      : kind === "create"
        ? "New worktree"
        : "Attach checkout";
  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setSubmitted(true);
    const fields = Object.fromEntries(
      [...new FormData(e.currentTarget)].filter(([, value]) => value !== ""),
    ) as Record<string, string>;
    const result = await perform(
      {
        action: kind === "project" ? "project.add" : `worktree.${kind}`,
        ...fields,
      },
      title,
    );
    if (result) {
      setOpen(false);
      if (kind !== "project" && typeof result.id === "string")
        navigate(`/environments/${encodeURIComponent(result.id)}/services`);
    }
  }
  return (
    <Dialog
      open={open}
      onOpenChange={(value) => {
        if (!busy) {
          setOpen(value);
          setSubmitted(false);
        }
      }}
    >
      <DialogTrigger asChild>
        <Button
          variant={kind === "attach" ? "outline" : "default"}
          disabled={!!busy || (kind !== "project" && !data.projects.length)}
        >
          {kind === "attach" ? <FolderInput /> : <Plus />}
          {title}
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>
            {kind === "project"
              ? "Register a local Git repository. Existing configuration is preserved; a missing file gets a starter configuration."
              : "Create or connect a checkout. Prepare and service startup are separate actions."}
          </DialogDescription>
        </DialogHeader>
        <form className="stack-form" onSubmit={submit}>
          {kind === "project" ? (
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
          {kind !== "create" ? (
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
                <Input name="branch" placeholder="feature/my-change" required />
              </label>
            </>
          )}
          <label>
            Configuration source{" "}
            <span className="muted font-normal">Optional</span>
            <Input name="config" placeholder="/absolute/path/to/project.toml" />
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
      </DialogContent>
    </Dialog>
  );
}
