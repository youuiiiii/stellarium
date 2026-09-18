import { useEffect, useMemo, useState } from "react";
import { ArrowLeft, ArrowRight, Check, RefreshCw, ShieldCheck, Undo2 } from "lucide-react";
import { useNavigate } from "react-router";
import { api } from "@/lib/api";
import type {
  StellaDetectedInstallation,
  StellaMigrationManifest,
  StellaMigrationPreview,
} from "@/lib/api";
import { useToast } from "@nous-research/ui/hooks/use-toast";
import { Toast } from "@nous-research/ui/ui/components/toast";
import { Badge } from "@nous-research/ui/ui/components/badge";
import { Button } from "@nous-research/ui/ui/components/button";
import { Card, CardContent } from "@nous-research/ui/ui/components/card";
import { Checkbox } from "@nous-research/ui/ui/components/checkbox";
import { Input } from "@nous-research/ui/ui/components/input";
import { Label } from "@nous-research/ui/ui/components/label";
import { Select, SelectOption } from "@nous-research/ui/ui/components/select";
import { cn, themedBody } from "@/lib/utils";

const COMPONENTS = [
  "config",
  "soul",
  "memories",
  "skills",
  "cron",
  "sessions",
] as const;

type ComponentName = (typeof COMPONENTS)[number];
type WizardStep = "select" | "preview" | "progress" | "complete";

const COMPONENT_LABELS: Record<ComponentName, string> = {
  config: "Configuration (sanitized)",
  soul: "SOUL",
  memories: "Memories",
  skills: "Skills",
  cron: "Cron jobs",
  sessions: "Sessions",
};

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function formatBytes(value: number): string {
  if (!Number.isFinite(value) || value < 1024) return `${value || 0} B`;
  const units = ["KiB", "MiB", "GiB"];
  let size = value;
  let unit = -1;
  do {
    size /= 1024;
    unit += 1;
  } while (size >= 1024 && unit < units.length - 1);
  return `${size.toFixed(size >= 10 ? 0 : 1)} ${units[unit]}`;
}

function DetectedInstallationCard({
  item,
  selected,
  onSelect,
}: {
  item: StellaDetectedInstallation;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      className={cn(
        "w-full border p-4 text-left transition-colors",
        selected
          ? "border-accent bg-accent/10"
          : "border-border hover:border-foreground/40",
        !item.is_valid && "opacity-60",
      )}
      disabled={!item.is_valid}
      onClick={onSelect}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="font-mono text-sm break-all">{item.path}</div>
          <div className="mt-2 flex flex-wrap gap-1.5 text-xs text-muted-foreground">
            {item.version_hint && <span>{item.version_hint}</span>}
            <span>{item.skill_count} skills</span>
            <span>{item.memory_count} memories</span>
            <span>{item.cron_count} cron jobs</span>
            <span>{formatBytes(item.estimated_size_bytes)}</span>
          </div>
        </div>
        <Badge tone={item.is_valid ? "success" : "secondary"}>
          {item.is_valid ? "valid" : "not usable"}
        </Badge>
      </div>
    </button>
  );
}

function StepIndicator({ step }: { step: WizardStep }) {
  const steps: Array<{ id: WizardStep; label: string }> = [
    { id: "select", label: "Select" },
    { id: "preview", label: "Preview" },
    { id: "progress", label: "Import" },
    { id: "complete", label: "Complete" },
  ];
  const currentIndex = steps.findIndex((item) => item.id === step);
  return (
    <ol className="flex flex-wrap items-center gap-2 text-xs uppercase tracking-wider text-muted-foreground">
      {steps.map((item, index) => (
        <li key={item.id} className="flex items-center gap-2">
          <span
            className={cn(
              "flex h-6 w-6 items-center justify-center rounded-full border",
              index <= currentIndex
                ? "border-accent bg-accent text-accent-foreground"
                : "border-border",
            )}
          >
            {index < currentIndex ? <Check className="h-3.5 w-3.5" /> : index + 1}
          </span>
          <span className={index === currentIndex ? "text-foreground" : undefined}>
            {item.label}
          </span>
          {index < steps.length - 1 && <span aria-hidden>·</span>}
        </li>
      ))}
    </ol>
  );
}

export default function StellaMigrationPage() {
  const navigate = useNavigate();
  const { toast, showToast } = useToast();
  const [detected, setDetected] = useState<StellaDetectedInstallation[]>([]);
  const [sourcePath, setSourcePath] = useState("");
  const [targetProfileId, setTargetProfileId] = useState("stella");
  const [selectedComponents, setSelectedComponents] = useState<ComponentName[]>([
    ...COMPONENTS,
  ]);
  const [preview, setPreview] = useState<StellaMigrationPreview | null>(null);
  const [manifest, setManifest] = useState<StellaMigrationManifest | null>(null);
  const [overwrite, setOverwrite] = useState(false);
  const [importNamedProfiles, setImportNamedProfiles] = useState(false);
  const [step, setStep] = useState<WizardStep>("select");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);

  const validDetections = useMemo(
    () => detected.filter((item) => item.is_valid),
    [detected],
  );

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    api
      .detectStellaMigrations()
      .then((result) => {
        if (cancelled) return;
        setDetected(result.detected ?? []);
        const first = (result.detected ?? []).find((item) => item.is_valid);
        if (first) setSourcePath(first.path);
      })
      .catch((error) => {
        if (!cancelled) showToast(`Could not detect Hermes installations: ${errorText(error)}`, "error");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [showToast]);

  const toggleComponent = (component: ComponentName) => {
    setSelectedComponents((current) =>
      current.includes(component)
        ? current.filter((item) => item !== component)
        : [...current, component],
    );
  };

  const handlePreview = async () => {
    if (!sourcePath.trim()) {
      showToast("Choose or enter a Hermes source path first.", "error");
      return;
    }
    if (!targetProfileId.trim()) {
      showToast("Target profile ID is required.", "error");
      return;
    }
    if (selectedComponents.length === 0) {
      showToast("Select at least one component to preview.", "error");
      return;
    }
    setBusy(true);
    try {
      const result = await api.previewStellaMigration({
        source_path: sourcePath,
        target_profile_id: targetProfileId,
        components: selectedComponents,
      });
      setPreview(result.preview);
      setOverwrite(false);
      setStep("preview");
    } catch (error) {
      showToast(`Preview failed: ${errorText(error)}`, "error");
    } finally {
      setBusy(false);
    }
  };

  const handleExecute = async () => {
    if (!preview || !preview.can_proceed) return;
    if (preview.conflicts.length > 0 && !overwrite) {
      showToast("Review the conflicts and enable overwrite, or go back and change the selection.", "error");
      return;
    }
    setBusy(true);
    setStep("progress");
    try {
      const result = await api.executeStellaMigration({
        source_path: sourcePath,
        target_profile_id: targetProfileId,
        components: selectedComponents,
        overwrite,
        import_named_profiles: importNamedProfiles,
      });
      setManifest(result.manifest);
      setStep("complete");
      showToast("Hermes data imported into the Stella profile.", "success");
    } catch (error) {
      setStep("preview");
      showToast(`Import failed: ${errorText(error)}`, "error");
    } finally {
      setBusy(false);
    }
  };

  const handleRollback = async () => {
    if (!manifest) return;
    setBusy(true);
    try {
      await api.rollbackStellaMigration(manifest.target_profile_id);
      setManifest((current) => (current ? { ...current, status: "rolled_back" } : current));
      showToast("The migration was rolled back.", "success");
    } catch (error) {
      showToast(`Rollback refused: ${errorText(error)}`, "error");
    } finally {
      setBusy(false);
    }
  };

  const resetToSelection = () => {
    setPreview(null);
    setManifest(null);
    setOverwrite(false);
    setImportNamedProfiles(false);
    setStep("select");
  };

  return (
    <div className="flex flex-col gap-6">
      <Toast toast={toast} />
      <div className="flex items-center justify-between gap-4">
        <Button ghost size="sm" className="gap-2" onClick={() => navigate("/profiles")}>
          <ArrowLeft className="h-4 w-4" />
          Profiles
        </Button>
        <StepIndicator step={step} />
      </div>

      <Card className={cn(themedBody, "border-border")}>
        <CardContent className="grid gap-6 p-6">
          <header className="grid gap-2">
            <div className="flex items-center gap-2">
              <ShieldCheck className="h-5 w-5 text-success" />
              <h1 className="font-mondwest text-display text-lg tracking-wider">
                Import Hermes into Stella
              </h1>
            </div>
            <p className="max-w-3xl text-sm text-muted-foreground">
              Selective, opt-in migration. The Hermes source is read-only; credentials,
              tokens, and raw environment files are excluded or redacted by the server.
            </p>
          </header>

          {step === "select" && (
            <div className="grid gap-6">
              <section className="grid gap-3">
                <div className="flex items-center justify-between gap-3">
                  <Label>Detected Hermes installations</Label>
                  <Button
                    ghost
                    size="sm"
                    className="gap-2"
                    disabled={loading || busy}
                    onClick={() => window.location.reload()}
                  >
                    <RefreshCw className="h-3.5 w-3.5" />
                    Rescan
                  </Button>
                </div>
                {loading ? (
                  <p className="text-sm text-muted-foreground" aria-live="polite">
                    Scanning known Hermes locations…
                  </p>
                ) : validDetections.length > 0 ? (
                  <div className="grid gap-2">
                    {detected.map((item) => (
                      <DetectedInstallationCard
                        key={item.path}
                        item={item}
                        selected={sourcePath === item.path}
                        onSelect={() => setSourcePath(item.path)}
                      />
                    ))}
                  </div>
                ) : (
                  <p className="border border-dashed border-border p-4 text-sm text-muted-foreground">
                    No valid installation was detected. Enter a source path manually below.
                  </p>
                )}
              </section>

              <section className="grid gap-2">
                <Label htmlFor="stella-source-path">Hermes source path</Label>
                <Input
                  id="stella-source-path"
                  value={sourcePath}
                  onChange={(event) => setSourcePath(event.target.value)}
                  placeholder="C:\\Users\\…\\.hermes"
                  spellCheck={false}
                />
                <p className="text-xs text-muted-foreground">
                  This path is only read during preview/import. Stella will reject overlap with its own home.
                </p>
              </section>

              <div className="grid gap-4 md:grid-cols-2">
                <section className="grid gap-2">
                  <Label htmlFor="stella-target-profile">Target Stella profile ID</Label>
                  <Input
                    id="stella-target-profile"
                    value={targetProfileId}
                    onChange={(event) => setTargetProfileId(event.target.value)}
                    placeholder="stella"
                    spellCheck={false}
                  />
                </section>
                <section className="grid gap-2">
                  <Label htmlFor="stella-component-source">Component selection</Label>
                  <Select
                    id="stella-component-source"
                    value={selectedComponents.length === COMPONENTS.length ? "all" : "custom"}
                    onValueChange={(value) => {
                      setSelectedComponents(value === "all" ? [...COMPONENTS] : []);
                    }}
                  >
                    <SelectOption value="all">All supported components</SelectOption>
                    <SelectOption value="custom">Custom selection below</SelectOption>
                  </Select>
                </section>
              </div>

              <fieldset className="grid gap-3 border-t border-border pt-4">
                <legend className="font-mondwest text-display text-xs tracking-wider text-muted-foreground">
                  Components to preview and import
                </legend>
                <div className="grid gap-3 sm:grid-cols-2">
                  {COMPONENTS.map((component) => (
                    <div key={component} className="flex items-center gap-2.5">
                      <Checkbox
                        id={`stella-component-${component}`}
                        checked={selectedComponents.includes(component)}
                        onCheckedChange={() => toggleComponent(component)}
                      />
                      <Label htmlFor={`stella-component-${component}`}>
                        {COMPONENT_LABELS[component]}
                      </Label>
                    </div>
                  ))}
                </div>
              </fieldset>

              <div className="flex justify-end">
                <Button className="gap-2 uppercase" disabled={busy || loading} onClick={handlePreview}>
                  Preview migration
                  <ArrowRight className="h-4 w-4" />
                </Button>
              </div>
            </div>
          )}

          {step === "preview" && preview && (
            <div className="grid gap-6">
              <section className="grid gap-2">
                <Label>Read-only source</Label>
                <div className="border border-border bg-muted/20 p-3 font-mono text-xs break-all">
                  {preview.source_path}
                </div>
                <p className="text-xs text-muted-foreground">
                  Target: <span className="font-mono">{preview.target_profile_id}</span> · Selected: {preview.selected_components.join(", ")}
                </p>
              </section>

              <section className="grid gap-3">
                <Label>Preview by component</Label>
                <div className="grid gap-2 md:grid-cols-2">
                  {Object.entries(preview.components).map(([name, component]) => (
                    <div key={name} className="border border-border p-4">
                      <div className="flex items-center justify-between gap-2">
                        <span className="font-mondwest text-display text-sm tracking-wider">
                          {COMPONENT_LABELS[name as ComponentName] ?? name}
                        </span>
                        <Badge tone={component.available ? "success" : "secondary"}>
                          {component.available ? "available" : "not found"}
                        </Badge>
                      </div>
                      <div className="mt-2 text-xs text-muted-foreground">
                        {component.file_count} files · {formatBytes(component.total_bytes)}
                      </div>
                      {component.sample_files.length > 0 && (
                        <ul className="mt-2 space-y-1 text-xs text-muted-foreground">
                          {component.sample_files.slice(0, 5).map((file) => (
                            <li key={file} className="truncate font-mono">{file}</li>
                          ))}
                        </ul>
                      )}
                    </div>
                  ))}
                </div>
              </section>

              {(preview.conflicts.length > 0 || preview.warnings.length > 0 || preview.excluded_files.length > 0) && (
                <section className="grid gap-3 border-t border-border pt-4">
                  {preview.conflicts.length > 0 && (
                    <div className="grid gap-2">
                      <Label>Conflicts requiring a decision</Label>
                      <ul className="max-h-36 overflow-y-auto border border-warning/50 p-3 text-xs">
                        {preview.conflicts.map((conflict) => (
                          <li key={conflict} className="font-mono">{conflict}</li>
                        ))}
                      </ul>
                      <div className="flex items-center gap-2.5">
                        <Checkbox
                          id="stella-overwrite"
                          checked={overwrite}
                          onCheckedChange={(checked) => setOverwrite(checked === true)}
                        />
                        <Label htmlFor="stella-overwrite">
                          Overwrite conflicting destination files (a rollback backup will be kept)
                        </Label>
                      </div>
                    </div>
                  )}
                  {preview.warnings.length > 0 && (
                    <div>
                      <Label>Warnings</Label>
                      <ul className="mt-2 space-y-1 text-xs text-warning">
                        {preview.warnings.map((warning) => <li key={warning}>{warning}</li>)}
                      </ul>
                    </div>
                  )}
                  {preview.excluded_files.length > 0 && (
                    <div>
                      <Label>Excluded by safety policy</Label>
                      <ul className="mt-2 max-h-32 overflow-y-auto space-y-1 text-xs text-muted-foreground">
                        {preview.excluded_files.slice(0, 20).map((file) => <li key={file} className="font-mono">{file}</li>)}
                      </ul>
                    </div>
                  )}
                </section>
              )}

              <div className="flex items-center gap-2.5 border-t border-border pt-4">
                <Checkbox
                  id="stella-import-named"
                  checked={importNamedProfiles}
                  onCheckedChange={(checked) => setImportNamedProfiles(checked === true)}
                />
                <Label htmlFor="stella-import-named">
                  Import named Hermes profiles into isolated Stella profiles
                </Label>
              </div>

              <div className="flex flex-wrap justify-between gap-2">
                <Button ghost disabled={busy} onClick={resetToSelection}>
                  <ArrowLeft className="mr-2 h-4 w-4" />
                  Change selection
                </Button>
                <Button
                  className="gap-2 uppercase"
                  disabled={busy || !preview.can_proceed || (preview.conflicts.length > 0 && !overwrite)}
                  onClick={handleExecute}
                >
                  Import selected data
                  <ArrowRight className="h-4 w-4" />
                </Button>
              </div>
            </div>
          )}

          {step === "progress" && (
            <div className="grid gap-3 py-12 text-center" aria-live="polite" aria-busy="true">
              <div className="font-mondwest text-display text-lg tracking-wider">Importing safely…</div>
              <p className="text-sm text-muted-foreground">
                Staging, sanitizing, and writing the selected components. The source remains untouched.
              </p>
            </div>
          )}

          {step === "complete" && manifest && (
            <div className="grid gap-6">
              <div className="flex items-start gap-3 border border-success/50 bg-success/5 p-4">
                <Check className="mt-0.5 h-5 w-5 shrink-0 text-success" />
                <div className="grid gap-1">
                  <div className="font-mondwest text-display text-sm tracking-wider">
                    {manifest.status === "rolled_back" ? "Migration rolled back" : "Migration complete"}
                  </div>
                  <p className="text-sm text-muted-foreground">
                    Migration <span className="font-mono">{manifest.migration_id}</span> · {manifest.copied_files.length} files recorded.
                  </p>
                </div>
              </div>
              {manifest.warnings.length > 0 && (
                <ul className="space-y-1 text-xs text-warning">
                  {manifest.warnings.map((warning) => <li key={warning}>{warning}</li>)}
                </ul>
              )}
              <div className="flex flex-wrap justify-between gap-2">
                <Button ghost onClick={() => navigate("/profiles")}>Back to profiles</Button>
                <div className="flex flex-wrap gap-2">
                  {manifest.status !== "rolled_back" && (
                    <Button
                      outlined
                      className="gap-2"
                      disabled={busy}
                      onClick={handleRollback}
                    >
                      <Undo2 className="h-4 w-4" />
                      Roll back migration
                    </Button>
                  )}
                  <Button className="uppercase" disabled={busy} onClick={resetToSelection}>
                    Import another source
                  </Button>
                </div>
              </div>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
