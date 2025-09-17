import { useEffect, useMemo, useState } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Check, ChevronDown, ChevronUp } from "lucide-react";
import clsx from "clsx";
import { WATCH_PROVIDERS } from "../data/watch_providers";
import { getActiveSubscriptionIds, upsertUserSubscriptions, setProviderFilterMode } from "../api";

type Props = {
  onBack?: () => void;
  onShowAll?: () => void; // treat as selecting everything (no provider filtering)
  onContinue?: (providers: number[]) => void; // continue with selected providers only (ids)
  initialSelected?: number[]; // provider ids
};

type Provider = { id: number; name: string; logo_path: string };

const TOP_PROVIDERS_NAMES = [
  "Netflix",
  "Hulu",
  "Max",
  "Disney+",
  "Apple TV+",
  "Amazon Prime Video",
  "Paramount Plus",
  "Peacock Premium",
] as const;

const MORE_PROVIDERS_NAMES = [
  "Crunchyroll",
  "MGM Plus",
  "Starz",
  "AMC+",
  "BritBox",
  "Acorn TV",
  "Criterion Channel",
  "Tubi TV",
  "Pluto TV",
  "The Roku Channel",
] as const;

export default function ProvidersStep({
  onBack,
  onShowAll,
  onContinue,
  initialSelected,
}: Props) {
  const byName = useMemo(() => {
    const m = new Map<string, Provider>();
    for (const p of WATCH_PROVIDERS) {
      m.set(p.provider_name, {
        id: p.provider_id,
        name: p.provider_name,
        logo_path: p.logo_path,
      });
    }
    // Aliases
    if (m.has("Disney Plus") && !m.has("Disney+"))
      m.set("Disney+", m.get("Disney Plus")!);
    if (m.has("HBO Max") && !m.has("Max")) m.set("Max", m.get("HBO Max")!);
    return m;
  }, []);

  const topProviders: Provider[] = useMemo(
    () =>
      TOP_PROVIDERS_NAMES.map((n) => byName.get(n)).filter(
        Boolean
      ) as Provider[],
    [byName]
  );
  const moreProviders: Provider[] = useMemo(
    () =>
      MORE_PROVIDERS_NAMES.map((n) => byName.get(n)).filter(
        Boolean
      ) as Provider[],
    [byName]
  );

  const [selected, setSelected] = useState<Set<number>>(new Set(initialSelected ?? []));
  const [showMore, setShowMore] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (initialSelected && initialSelected.length > 0) {
      setSelected(new Set(initialSelected));
      return;
    }
    (async () => {
      try {
        const ids = await getActiveSubscriptionIds();
        if (ids && ids.length > 0) setSelected(new Set(ids));
      } catch (e) {
        // ignore; preselect is a nice-to-have
        console.warn("Failed to fetch existing subscriptions", e);
      }
    })();
  }, [initialSelected]);

  function toggle(id: number) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  // Auto-unfold "See more services" when any selected provider lives in the MORE list.
  useEffect(() => {
    if (showMore) return; // don't override user's manual toggle once open
    const moreIds = new Set(moreProviders.map((p) => p.id));
    for (const id of selected) {
      if (moreIds.has(id)) {
        setShowMore(true);
        break;
      }
    }
  }, [selected, moreProviders, showMore]);

  function renderGrid(list: Provider[]) {
    return (
      <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-3">
        {list.map((p) => {
          const isSelected = selected.has(p.id);
          return (
            <button
              key={p.id}
              type="button"
              onClick={() => toggle(p.id)}
              className={clsx(
                "relative group rounded-md border p-2 flex items-center justify-center text-left transition-colors",
                isSelected
                  ? "border-primary ring-1 ring-primary/30 bg-primary/5"
                  : "border-border hover:bg-accent"
              )}
              title={p.name}
              aria-pressed={isSelected}
            >
              <div className="flex flex-col items-center justify-center w-full">
                <div className="flex items-center justify-center w-full h-[96px] sm:h-[100px] md:h-[106px]">
                  <img
                    src={p.logo_path}
                    alt={p.name}
                    loading="lazy"
                    className="max-w-[75%] sm:max-w-[72%] md:max-w-[65%] lg:max-w-[60%] h-auto object-contain"
                    onError={(e) => {
                      const el = e.currentTarget as HTMLImageElement;
                      el.style.display = "none";
                      const parent = el.parentElement;
                      if (parent)
                        parent.innerHTML = `<div class="w-12 h-12 rounded bg-muted text-foreground/70 text-sm font-medium flex items-center justify-center">${p.name.charAt(0)}</div>`;
                    }}
                  />
                </div>
                <div className="mt-2 w-full text-center text-[12px] md:text-[13px] text-muted-foreground leading-tight truncate px-1">
                  {p.name}
                </div>
              </div>
              {isSelected && (
                <Check className="absolute top-2 right-2 h-4 w-4 text-primary" />
              )}
            </button>
          );
        })}
      </div>
    );
  }

  const selectedArr = Array.from(selected);

  return (
    <div className="mx-auto max-w-5xl px-4 py-8">
      <div className="mb-6">
        <h2 className="text-2xl font-semibold">
          Tell us where you usually watch
        </h2>
        <p className="text-sm text-muted-foreground">
          Pick your streaming services to prioritize recommendations available there. Or choose <strong>Show me everything</strong> if you want the full catalog.
        </p>
      </div>

      <div className="space-y-4">
        {renderGrid(topProviders)}

        <div>
          <button
            type="button"
            onClick={() => setShowMore((v) => !v)}
            className="mt-2 inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
            aria-expanded={showMore}
          >
            {showMore ? (
              <>
                <ChevronUp className="h-4 w-4" /> See fewer
              </>
            ) : (
              <>
                <ChevronDown className="h-4 w-4" /> See more services
              </>
            )}
          </button>
        </div>

  {showMore && (
    <Card>
      <CardContent className="p-3">
        {renderGrid(moreProviders)}
      </CardContent>
    </Card>
  )}
</div>

<div className="flex items-center justify-between mt-8">
  <div className="flex items-center gap-2">
    <Button variant="outline" onClick={onBack} disabled={saving} aria-disabled={saving}>
      Back
    </Button>
  </div>
  <div className="flex items-center gap-2">
    <Button
      variant="outline"
      disabled={saving}
      aria-disabled={saving}
      onClick={async () => {
        setSaving(true);
        try {
          await upsertUserSubscriptions(selectedArr);
          await setProviderFilterMode("ALL");
        } catch (e) {
          console.warn("Failed to save subscriptions/settings", e);
        } finally {
          setSaving(false);
          onShowAll?.();
        }
      }}
    >
      Show me everything
    </Button>
    <Button
      onClick={async () => {
        setSaving(true);
        try {
          await upsertUserSubscriptions(selectedArr);
          await setProviderFilterMode("SELECTED");
          onContinue?.(selectedArr);
        } catch (e) {
          console.warn("Failed to save subscriptions/settings", e);
        } finally {
          setSaving(false);
        }
      }}
      disabled={selectedArr.length === 0 || saving}
      aria-disabled={selectedArr.length === 0 || saving}
    >
      Continue
    </Button>
  </div>
</div>

    </div>
  );
}
