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
      <PageHeading
        title="Secrets"
        description="Shared values, available to every project by name."
      />
      <section className="form-section">
        <div>
          <h2>
            <KeyRound size={18} />
            Add or update a secret
          </h2>
          <p className="muted">
            Stored values cannot be read back. Enter a new value to replace an
            existing name for all references.
          </p>
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
            Stored name
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
            Save secret
          </Button>
        </form>
        <p className="muted small">
          Values are stored in plaintext in the local SQLite database under
          private file permissions and are never returned here. Running services
          keep their current values until restarted.
        </p>
      </section>
      {loading ? (
        <Loading />
      ) : !data.secrets.length ? (
        <Empty title="No secrets stored">
          Add a value above, then reference its name from project.toml.
        </Empty>
      ) : (
        <div className="data-panel">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Stored name</TableHead>
                <TableHead>How to reference</TableHead>
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
                    <div className="cell-secondary">
                      Stored · value is not returned
                    </div>
                  </TableCell>
                  <TableCell>
                    <code>secret:{name}</code>
                    <details className="secret-reference">
                      <summary>Use in project.toml</summary>
                      <pre>{`[secrets]\nAPI_TOKEN = ${JSON.stringify(`secret:${name}`)}`}</pre>
                      <p className="muted small">
                        API_TOKEN is the environment variable your application
                        receives. {name} is the stored name. This example is not
                        a list of projects using the secret.
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
                      Replace value<span className="sr-only"> for {name}</span>
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
