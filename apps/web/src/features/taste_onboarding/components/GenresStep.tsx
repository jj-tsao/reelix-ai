// src/features/onboarding/GenresStep.tsx
import { useMemo, useState } from "react";
import { ALL_GENRES, VIBE_TAGS, type Genre } from "../constants";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Check } from "lucide-react";
import clsx from "clsx";

type Props = {
  initialGenres?: string[];
  initialVibes?: string[];
  onSubmit: (data: { genres: string[]; vibeTags: string[] }) => void;
  submitting?: boolean;
};

const MIN_GENRES_REQUIRED = 3;
const MAX_VISIBLE_VIBES = 4;

export default function GenresStep({
  initialGenres,
  initialVibes,
  onSubmit,
  submitting,
}: Props) {
  const [selectedGenres, setSelectedGenres] = useState<string[]>(
    initialGenres ?? []
  );
  const [selectedVibes, setSelectedVibes] = useState<string[]>(
    initialVibes ?? []
  );
  const [expandedGenres, setExpandedGenres] = useState<Record<string, boolean>>(
    {}
  );

  // For the footer summary and validation
  const totalVibes = selectedVibes.length;
  const needsMoreGenres = selectedGenres.length < MIN_GENRES_REQUIRED;
  const helperMessage = useMemo(
    () =>
      needsMoreGenres
        ? "Pick 3+ to personalize better."
        : "Looks good. Keep picking or continue.",
    [needsMoreGenres]
  );
  function toggleGenre(genre: string) {
    const isActive = selectedGenres.includes(genre);
    const next = isActive
      ? selectedGenres.filter((g) => g !== genre)
      : [...selectedGenres, genre];

    // If removing a genre, also remove its vibes to avoid orphans
    if (isActive) {
      const genreVibes = new Set(VIBE_TAGS[genre as Genre] ?? []);
      setSelectedVibes((prev) => prev.filter((v) => !genreVibes.has(v)));
      setExpandedGenres((prev) => {
        if (!(genre in prev)) return prev;
        const nextExpanded = { ...prev };
        delete nextExpanded[genre];
        return nextExpanded;
      });
    }
    setSelectedGenres(next);
  }

  function toggleVibe(genre: string, tag: string) {
    // Ensure the parent genre is selected (if user taps a vibe first)
    if (!selectedGenres.includes(genre)) {
      setSelectedGenres((prev) => [...prev, genre]);
    }
    setSelectedVibes((prev) =>
      prev.includes(tag) ? prev.filter((t) => t !== tag) : [...prev, tag]
    );
  }

  function handleSubmit() {
    if (submitting) return;
    if (needsMoreGenres) return;

    onSubmit({ genres: selectedGenres, vibeTags: selectedVibes });
  }

  function handleClearSelections() {
    setSelectedGenres([]);
    setSelectedVibes([]);
    setExpandedGenres({});
  }

  return (
    <div className="mx-auto max-w-4xl px-4 pb-8 pt-4 sm:pt-4">
      <h2 className="mb-1 text-2xl font-semibold text-foreground">
        Pick a few genres you enjoy
      </h2>
      <div className="sticky top-[3.5rem] z-20 mb-6 border-b border-border/60 bg-background/95 py-3 shadow-sm backdrop-blur sm:top-[4.25rem]">
        <p className="text-sm text-muted-foreground">
          Choose at least 3 to get started. We’ll suggest a few titles to rate
          next.
        </p>
      </div>

      {/* Responsive grid of cards; tags are shown only when genre is selected */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        {ALL_GENRES.map((g) => {
          const active = selectedGenres.includes(g);

          return (
            <Card
              key={g}
              className={clsx(
                "transition-all cursor-pointer focus:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2",
                active
                  ? "border-border ring-2 ring-inset ring-primary/50"
                  : "hover:border-border"
              )}
              onClick={() => toggleGenre(g)}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  toggleGenre(g);
                }
              }}
              role="button"
              tabIndex={0}
              aria-pressed={active}
            >
              <CardHeader className="py-3">
                <div className="flex items-center justify-between">
                  <div
                    className={clsx(
                      "inline-flex items-center gap-2 text-sm font-medium px-3 py-1 rounded-full border transition-colors",
                      active
                        ? "bg-primary text-primary-foreground border-primary"
                        : "bg-background border-muted-foreground/30"
                    )}
                  >
                    {active && <Check className="h-4 w-4" />}
                    {g}
                  </div>
                </div>
              </CardHeader>

              {active && (
                <CardContent className="pt-0 pb-4">
                  <div className="text-xs text-muted-foreground mb-2">
                    Optional: Pick any that sound appealing.
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {(() => {
                      const allVibes = VIBE_TAGS[g as Genre] ?? [];
                      const expanded = expandedGenres[g] ?? false;
                      const visibleVibes = expanded
                        ? allVibes
                        : allVibes.slice(0, MAX_VISIBLE_VIBES);

                      return (
                        <>
                          {visibleVibes.map((v) => {
                            const picked = selectedVibes.includes(v);
                            return (
                              <button
                                key={g + v}
                                type="button"
                                onClick={(e) => {
                                  e.stopPropagation();
                                  toggleVibe(g, v);
                                }}
                                className={clsx(
                                  "px-2.5 py-1 rounded-full text-xs border transition",
                                  picked
                                    ? "bg-secondary text-secondary-foreground border-secondary"
                                    : "bg-background border-muted-foreground/30 hover:bg-muted"
                                )}
                                aria-pressed={picked}
                              >
                                <span className="inline-flex items-center gap-1">
                                  {picked && <Check className="h-3.5 w-3.5" />}
                                  {v}
                                </span>
                              </button>
                            );
                          })}
                          {allVibes.length > MAX_VISIBLE_VIBES && (
                            <button
                              type="button"
                              onClick={(e) => {
                                e.stopPropagation();
                                setExpandedGenres((prev) => ({
                                  ...prev,
                                  [g]: !(prev[g] ?? false),
                                }));
                              }}
                              className="px-2.5 py-1 rounded-full text-xs border border-muted-foreground/30 text-muted-foreground transition hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
                              aria-expanded={expanded}
                              aria-label={`${
                                expanded ? "Show fewer" : "Show more"
                              } vibe tags for ${g}`}
                            >
                              {expanded ? "Show less" : "More..."}
                            </button>
                          )}
                        </>
                      );
                    })()}
                  </div>
                </CardContent>
              )}
            </Card>
          );
        })}
      </div>

      {/* Footer */}
      <div className="sticky bottom-0 z-20 mt-6 border-t border-border/60 bg-background/95 py-4 shadow-md backdrop-blur">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-3 text-sm text-muted-foreground">
            <span>
              Selected:{" "}
              <span className="font-medium">{selectedGenres.length}</span> genre
              {selectedGenres.length > 1 ? "s" : ""} ·{" "}
              <span className="font-medium">{totalVibes}</span> vibe tag
              {totalVibes > 1 ? "s" : ""}
            </span>
            <Button
              type="button"
              size="sm"
              variant="secondary"
              className="px-2 text-xs"
              onClick={handleClearSelections}
              disabled={selectedGenres.length === 0 && totalVibes === 0}
            >
              Clear all
            </Button>
          </div>
          <Button
            disabled={submitting || needsMoreGenres}
            onClick={handleSubmit}
            className={clsx(
              "transition-opacity",
              needsMoreGenres && !submitting ? "opacity-60" : "opacity-100"
            )}
          >
            {submitting ? "Saving..." : "Continue to Rating"}
          </Button>
        </div>
        <div className="mt-1 w-full text-right text-sm text-muted-foreground">
          {helperMessage}
        </div>
      </div>
    </div>
  );
}
