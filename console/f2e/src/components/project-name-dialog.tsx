import { useState } from "react";
import type { Project } from "@/api";
import { useConsole } from "@/lib/console";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

export function ProjectNameDialog({
  project,
  onClose,
  onCloseAutoFocus,
}: {
  project: Project;
  onClose: () => void;
  onCloseAutoFocus: (event: Event) => void;
}) {
  const { busy, error, perform } = useConsole();
  const [submitted, setSubmitted] = useState(false);
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open && !busy) onClose();
      }}
    >
      <DialogContent onCloseAutoFocus={onCloseAutoFocus}>
        <DialogHeader>
          <DialogTitle>Edit name</DialogTitle>
          <DialogDescription>
            Changes the display name. The project ID and worktrees stay the
            same.
          </DialogDescription>
        </DialogHeader>
        <form
          className="stack-form"
          onSubmit={async (event) => {
            event.preventDefault();
            setSubmitted(true);
            const fields = new FormData(event.currentTarget);
            if (
              await perform(
                {
                  action: "project.rename",
                  project: project.id,
                  display_name: String(fields.get("display_name")),
                },
                "Rename project",
              )
            )
              onClose();
          }}
        >
          <label>
            Name
            <Input
              name="display_name"
              defaultValue={project.display_name || project.id}
              required
              maxLength={120}
            />
          </label>
          <p className="muted small">
            Project ID <code>{project.id}</code>
          </p>
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
              onClick={onClose}
            >
              Cancel
            </Button>
            <Button disabled={!!busy}>{busy || "Save"}</Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
