import { useRef, useState } from "react";
import { KeyRound, Plus, Trash2 } from "lucide-react";
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
import { Empty, Loading, PageHeading } from "@/components/shared";
import {
  ConfirmationDialog,
  type Confirmation,
} from "@/components/confirmation";

export function Secrets() {
  const { data, loading, busy, perform } = useConsole();
  const [confirmation, setConfirmation] = useState<Confirmation | null>(null);
  const [storedName, setStoredName] = useState("");
  const valueInput = useRef<HTMLInputElement>(null);
  return (
    <>
      <PageHeading title="Secrets" description="Shared across projects." />
      <section className="form-section">
        <div>
          <h2>
            <KeyRound size={18} />
            Set value
          </h2>
          <p className="muted">Saved values cannot be read back.</p>
        </div>
        <form
          className="inline-form"
          onSubmit={(e) => {
            e.preventDefault();
            const form = e.currentTarget;
            const fields = new FormData(form);
            const name = String(fields.get("name"));
            const value = String(fields.get("value"));
            form.reset();
            setStoredName("");
            void perform({ action: "secret.set", name, value }, "Save secret");
          }}
        >
          <label>
            Name
            <Input
              name="name"
              value={storedName}
              onChange={(event) => setStoredName(event.target.value)}
              required
              placeholder="app-dev-token"
              autoComplete="off"
            />
          </label>
          <label>
            Value
            <Input
              name="value"
              ref={valueInput}
              type="password"
              required
              autoComplete="new-password"
            />
          </label>
          <Button disabled={!!busy}>
            <Plus />
            Save
          </Button>
        </form>
        <p className="muted small">
          Running services keep their current values until restarted.
        </p>
        <details className="form-options">
          <summary>Storage</summary>
          <p className="muted small">
            Values are stored in the local SQLite database in plaintext, with
            private file permissions. They are never returned here.
          </p>
        </details>
      </section>
      {loading ? (
        <Loading />
      ) : !data.secrets.length ? (
        <Empty title="No secrets stored">
          Add a value above, then reference its name from project.toml.
        </Empty>
      ) : (
        <div className="data-panel">
          <Table className="secret-table">
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>Reference</TableHead>
                <TableHead>
                  <span className="sr-only">Actions</span>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.secrets.map((name) => (
                <TableRow key={name}>
                  <TableCell>
                    <strong>{name}</strong>
                  </TableCell>
                  <TableCell>
                    <code>secret:{name}</code>
                    <details className="secret-reference">
                      <summary>Usage</summary>
                      <pre>{`[secrets]\nAPI_TOKEN = ${JSON.stringify(`secret:${name}`)}`}</pre>
                      <p className="muted small">
                        Add this to <code>.lodex/project.toml</code>. API_TOKEN
                        is the variable your app receives.
                      </p>
                    </details>
                  </TableCell>
                  <TableCell className="text-right">
                    <Button
                      variant="ghost"
                      disabled={!!busy}
                      onClick={() => {
                        setStoredName(name);
                        if (valueInput.current) {
                          valueInput.current.value = "";
                          valueInput.current.focus();
                        }
                      }}
                    >
                      Replace<span className="sr-only"> {name}</span>
                    </Button>
                    <Button
                      variant="ghost"
                      className="text-destructive"
                      disabled={!!busy}
                      onClick={async () => {
                        const action = { action: "secret.remove", name };
                        const preview = await perform(
                          action,
                          "Preview secret removal",
                          true,
                        );
                        if (preview) setConfirmation({ action, preview });
                      }}
                    >
                      <Trash2 />
                      Remove<span className="sr-only"> {name}</span>
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
      <ConfirmationDialog
        confirmation={confirmation}
        onClose={() => setConfirmation(null)}
      />
    </>
  );
}
