// src/features/onboarding/GenresStep.tsx
import { useState } from "react";
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

  // For the footer summary and validation
  const totalVibes = selectedVibes.length;
  const canContinue = selectedGenres.length > 0 && !submitting;

  function toggleGenre(genre: string) {
    const isActive = selectedGenres.includes(genre);
    const next = isActive
      ? selectedGenres.filter((g) => g !== genre)
      : [...selectedGenres, genre];

    // If removing a genre, also remove its vibes to avoid orphans
    if (isActive) {
      const genreVibes = new Set(VIBE_TAGS[genre as Genre] ?? []);
      setSelectedVibes((prev) => prev.filter((v) => !genreVibes.has(v)));
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

  return (
    <div className="mx-auto max-w-4xl px-4 py-8">
      <div className="mb-6">
        <h2 className="text-2xl font-semibold">Welcome! Let’s start with genres</h2>
        <p className="text-sm text-muted-foreground">
          Pick a few you enjoy. Vibe tags for a genre are shown when it’s selected.
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
                "transition-all",
                active ? "border-primary ring-1 ring-primary/30" : "hover:border-border"
              )}
            >
              <CardHeader className="py-3">
                <div className="flex items-center justify-between">
                  <button
                    type="button"
                    onClick={() => toggleGenre(g)}
                    className={clsx(
                      "inline-flex items-center gap-2 text-sm font-medium px-3 py-1 rounded-full border transition-colors",
                      active
                        ? "bg-primary text-primary-foreground border-primary"
                        : "bg-background border-muted-foreground/30"
                    )}
                    aria-pressed={active}
                  >
                    {active && <Check className="h-4 w-4" />}
                    {g}
                  </button>
                </div>
              </CardHeader>

              {active && (
                <CardContent className="pt-0 pb-4">
                  <div className="text-xs text-muted-foreground mb-2">
                    Optional: Pick any that sound appealing.
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {(VIBE_TAGS[g as Genre] ?? []).map((v) => {
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
                  </div>
                </CardContent>
              )}
            </Card>
          );
        })}
      </div>

      {/* Footer */}
      <div className="flex items-center justify-between mt-6">
        <div className="text-sm text-muted-foreground">
          Selected: <span className="font-medium">{selectedGenres.length}</span> genre
          {selectedGenres.length !== 1 ? "s" : ""} ·{" "}
          <span className="font-medium">{totalVibes}</span> vibe tag
          {totalVibes !== 1 ? "s" : ""}
        </div>
        <Button
          disabled={!canContinue}
          onClick={() =>
            onSubmit({ genres: selectedGenres, vibeTags: selectedVibes })
          }
        >
          {submitting ? "Saving..." : "Save & Continue"}
        </Button>
      </div>
    </div>
  );
}
