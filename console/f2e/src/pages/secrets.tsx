import { useState } from "react";
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
            Saving an existing name replaces its value for all references.
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
            void perform({ action: "secret.set", name, value }, "Save secret");
          }}
        >
          <label>
            Stored name
            <Input
              name="name"
              required
              placeholder="app-dev-token"
              autoComplete="off"
            />
          </label>
          <label>
            Value
            <Input
              name="value"
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
                <TableHead>Configuration reference</TableHead>
                <TableHead>
                  <span className="sr-only">Actions</span>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.secrets.map((name) => (
                <TableRow key={name}>
                  <TableCell className="font-medium">{name}</TableCell>
                  <TableCell>
                    <code>secret:{name}</code>
                  </TableCell>
                  <TableCell className="text-right">
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
