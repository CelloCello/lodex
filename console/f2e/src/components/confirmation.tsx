import { useRef, useState } from "react";
import type { Action, Resource, Service } from "@/api";
import { useConsole } from "@/lib/console";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { RawData, State } from "@/components/shared";

export type Confirmation = { action: Action; preview: Record<string, unknown> };
export function ConfirmationDialog({
  confirmation,
  onClose,
  onDone,
  onCloseAutoFocus,
}: {
  confirmation: Confirmation | null;
  onClose: () => void;
  onDone?: () => void;
  onCloseAutoFocus?: (event: Event) => void;
}) {
  const { perform, busy, error } = useConsole();
  const [force, setForce] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const returnFocus = useRef<HTMLElement | null>(null);
  const action = confirmation?.action;
  const preview = confirmation?.preview || {};
  const services = (preview.services || []) as Service[];
  const resources = (preview.known_resources || []) as Resource[];
  const removing = action?.action === "worktree.remove";
  const title =
    action?.action === "cleanup"
      ? "Run cleanup"
      : action?.action === "secret.remove"
        ? "Remove secret"
        : action?.action === "project.delete"
          ? "Delete project"
          : removing
            ? "Remove worktree"
            : "Unregister environment";
  return (
    <Dialog
      open={!!confirmation}
      onOpenChange={(open) => {
        if (!open && !busy) {
          onClose();
          setForce(false);
          setSubmitted(false);
        }
      }}
    >
      <DialogContent
        onOpenAutoFocus={() => {
          returnFocus.current = document.activeElement as HTMLElement;
        }}
        onCloseAutoFocus={(event) => {
          onCloseAutoFocus?.(event);
          if (event.defaultPrevented) return;
          if (returnFocus.current?.isConnected) {
            event.preventDefault();
            returnFocus.current.focus();
          }
        }}
      >
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>
            Review the scope before continuing.
          </DialogDescription>
        </DialogHeader>
        <div className="confirmation-scope">
          {action?.action === "project.delete" && (
            <div>
              <strong>{String(preview.display_name)}</strong>
              <p className="muted small">
                Project ID <code>{String(preview.project)}</code>
              </p>
              <code className="break-value">
                {String(preview.source_checkout)}
              </code>
            </div>
          )}
          {preview.path != null && (
            <div>
              <span className="field-title">Worktree path</span>
              <code className="break-value">{String(preview.path)}</code>
            </div>
          )}
          {preview.name != null && (
            <div>
              <span className="field-title">Stored name</span>
              <code>{String(preview.name)}</code>
            </div>
          )}
          {preview.warning != null && (
            <p className="feedback feedback-warning">
              {String(preview.warning)}
            </p>
          )}
          {removing && (
            <div>
              <span className="field-title">Git changes</span>
              {preview.git_status ? (
                <pre>{String(preview.git_status)}</pre>
              ) : (
                <p className="muted">
                  No tracked or untracked changes reported. Ignored files are
                  still deleted with the directory.
                </p>
              )}
            </div>
          )}
          {(removing ||
            action?.action === "worktree.forget" ||
            action?.action === "cleanup") && (
            <>
              <div>
                <span className="field-title">
                  Recorded services · {services.length}
                </span>
                {services.length ? (
                  services.map((s) => (
                    <div className="scope-row" key={s.name}>
                      {s.name}
                      <State value={s.state} />
                    </div>
                  ))
                ) : (
                  <p className="muted">No services recorded.</p>
                )}
              </div>
              <div>
                <span className="field-title">
                  Known resources · {resources.length}
                </span>
                {resources.length ? (
                  resources.map((r, i) => (
                    <div className="scope-row" key={i}>
                      <span>
                        {r.name} <code>{r.id}</code>
                      </span>
                      <State value={r.state} />
                    </div>
                  ))
                ) : (
                  <p className="muted">
                    No resources reported. This is not a complete inventory of
                    external resources.
                  </p>
                )}
              </div>
            </>
          )}
          {removing && (
            <label className="checkbox">
              <input
                type="checkbox"
                checked={force}
                onChange={(e) => setForce(e.target.checked)}
              />
              Force Git removal, including uncommitted or untracked changes
            </label>
          )}
          <RawData value={preview} />
          {submitted && error && (
            <p role="alert" className="feedback feedback-error">
              {error}
            </p>
          )}
        </div>
        <div className="actions justify-end">
          <Button
            variant="outline"
            disabled={!!busy}
            onClick={() => {
              onClose();
              setForce(false);
              setSubmitted(false);
            }}
          >
            Cancel
          </Button>
          <Button
            variant="destructive"
            disabled={!!busy}
            onClick={async () => {
              if (!action) return;
              setSubmitted(true);
              const result = await perform(
                { ...action, yes: true, force },
                title,
              );
              if (result) {
                onClose();
                setForce(false);
                setSubmitted(false);
                onDone?.();
              }
            }}
          >
            {busy ||
              (action?.action === "worktree.forget" ? "Unregister" : title)}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
