import { useMemo, useState } from "react";
import { SEED_MOVIES } from "../constants";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Heart, ThumbsUp, ThumbsDown, SkipForward } from "lucide-react";
import clsx from "clsx";

type SeedMovie = {
  title: string;
  year: number;
  poster_url: string;
  vibes: string[];
};

type Rating = "love" | "like" | "not_for_me" | "skip";

type Props = {
  genres: string[];
  onBack?: () => void;
  onFinish?: (ratings: Record<string, Rating>) => void;
};

function sampleThree<T>(arr: readonly T[]): T[] {
  if (!arr || arr.length === 0) return [];
  const copy = Array.from(arr);
  for (let i = copy.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [copy[i], copy[j]] = [copy[j], copy[i]];
  }
  return copy.slice(0, 3);
}

export default function RateSeedMoviesStep({ genres, onBack, onFinish }: Props) {
  const [ratings, setRatings] = useState<Record<string, Rating>>({});

  const picksFlat = useMemo(() => {
    const flat: { genre: string; movie: SeedMovie }[] = [];
    for (const g of genres) {
      const pool = (SEED_MOVIES as unknown as Record<string, readonly SeedMovie[]>)[g] ?? [];
      const sampled = sampleThree(pool);
      sampled.forEach((m) => flat.push({ genre: g, movie: m }));
    }
    // Shuffle across genres so cards appear in a randomized sequence
    for (let i = flat.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [flat[i], flat[j]] = [flat[j], flat[i]];
    }
    return flat;
  }, [JSON.stringify(genres)]);

  function keyFor(genre: string, m: SeedMovie) {
    return `${genre}:${m.title}:${m.year}`;
  }

  function setRating(genre: string, m: SeedMovie, r: Rating) {
    const k = keyFor(genre, m);
    setRatings((prev) => ({ ...prev, [k]: r }));
  }

  return (
    <div className="mx-auto max-w-5xl px-4 py-8">
      <div className="mb-6">
        <h2 className="text-2xl font-semibold">Rate a few picks</h2>
        <p className="text-sm text-muted-foreground">
          We selected a few titles per genre you chose. Tap Love, Like, Not for me, or Skip.
        </p>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-4">
        {picksFlat.map(({ genre, movie: m }) => {
          const k = keyFor(genre, m);
          const r = ratings[k];
          return (
            <Card key={k} className="overflow-hidden">
              <CardContent className="p-0">
                <div className="aspect-[2/3] w-full bg-muted overflow-hidden">
                  {m.poster_url && (
                    <img
                      src={m.poster_url}
                      alt={m.title}
                      className="w-full h-full object-cover"
                      loading="lazy"
                    />
                  )}
                </div>
                <div className="p-3 border-t">
                  <div className="text-sm font-medium leading-tight">{m.title}</div>
                  <div className="text-xs text-muted-foreground">{m.year}</div>
                  <div className="mt-3 grid grid-cols-4 gap-2">
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      className={clsx(
                        "justify-center",
                        r === "love" && "bg-pink-100 text-pink-700 border border-pink-300"
                      )}
                      onClick={() => setRating(genre, m, "love")}
                      aria-pressed={r === "love"}
                      title="Love"
                    >
                      <Heart className="h-4 w-4" />
                    </Button>
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      className={clsx(
                        "justify-center",
                        r === "like" && "bg-green-100 text-green-700 border border-green-300"
                      )}
                      onClick={() => setRating(genre, m, "like")}
                      aria-pressed={r === "like"}
                      title="Like"
                    >
                      <ThumbsUp className="h-4 w-4" />
                    </Button>
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      className={clsx(
                        "justify-center",
                        r === "not_for_me" && "bg-amber-100 text-amber-800 border border-amber-300"
                      )}
                      onClick={() => setRating(genre, m, "not_for_me")}
                      aria-pressed={r === "not_for_me"}
                      title="Not for me"
                    >
                      <ThumbsDown className="h-4 w-4" />
                    </Button>
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      className={clsx(
                        "justify-center",
                        r === "skip" && "bg-slate-100 text-slate-700 border border-slate-300"
                      )}
                      onClick={() => setRating(genre, m, "skip")}
                      aria-pressed={r === "skip"}
                      title="Skip"
                    >
                      <SkipForward className="h-4 w-4" />
                    </Button>
                  </div>
                </div>
              </CardContent>
            </Card>
          );
        })}
      </div>

      <div className="flex items-center justify-between mt-8">
        <Button variant="outline" onClick={onBack}>Back</Button>
        <Button onClick={() => onFinish?.(ratings)}>Continue</Button>
      </div>
    </div>
  );
}
