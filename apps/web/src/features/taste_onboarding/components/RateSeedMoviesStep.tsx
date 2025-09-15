import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { PropsWithChildren } from "react";
import { SEED_MOVIES } from "../constants";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Heart, ThumbsUp, ThumbsDown, Shuffle } from "lucide-react";
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

function shuffleInPlace<T>(arr: T[]): T[] {
  for (let i = arr.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [arr[i], arr[j]] = [arr[j], arr[i]];
  }
  return arr;
}

export default function RateSeedMoviesStep({ genres, onBack, onFinish }: Props) {
  const [ratings, setRatings] = useState<Record<string, Rating>>({});

  // Cards displayed and remaining pools per genre to support "skip" swaps
  const [cards, setCards] = useState<{ genre: string; movie: SeedMovie }[]>([]);
  const [, setRemainingByGenre] = useState<Record<string, SeedMovie[]>>({});
  const [animatingIndex, setAnimatingIndex] = useState<number | null>(null);
  const animTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Initialize cards when genres change
  useEffect(() => {
    const nextCards: { genre: string; movie: SeedMovie }[] = [];
    const nextRemaining: Record<string, SeedMovie[]> = {};
    for (const g of genres) {
      const all = [
        ...(((SEED_MOVIES as unknown as Record<string, readonly SeedMovie[]>)[g] ?? []) as readonly SeedMovie[]),
      ];
      const pool = shuffleInPlace(all.slice());
      const sampled = pool.slice(0, 3);
      const remaining = pool.slice(3);
      sampled.forEach((m) => nextCards.push({ genre: g, movie: m }));
      nextRemaining[g] = remaining;
    }
    shuffleInPlace(nextCards);
    setCards(nextCards);
    setRemainingByGenre(nextRemaining);
    setRatings({});
  }, [genres]);

  function keyFor(genre: string, m: SeedMovie) {
    return `${genre}:${m.title}:${m.year}`;
  }

  function setRating(genre: string, m: SeedMovie, r: Rating) {
    const k = keyFor(genre, m);
    setRatings((prev) => ({ ...prev, [k]: r }));
  }

  function handleSkip(index: number, genre: string, m: SeedMovie) {
    // Record the skip rating for the current movie
    setRating(genre, m, "skip");
    setAnimatingIndex(index);
    // Build exclusion set of keys currently displayed (excluding the card being replaced)
    const excludeKeys = new Set(
      cards.filter((_, i) => i !== index).map(({ genre: g, movie }) => keyFor(g, movie))
    );

    // Choose a replacement from the same genre if possible,
    // otherwise randomly from any genre that still has remaining movies, avoiding duplicates.
    setRemainingByGenre((old) => {
      const mutable: Record<string, SeedMovie[]> = Object.fromEntries(
        Object.entries(old).map(([g, list]) => [g, list.slice()])
      );

      const candidateGenres = (() => {
        const others = Object.keys(mutable).filter((g) => g !== genre && (mutable[g]?.length ?? 0) > 0);
        shuffleInPlace(others);
        return [genre, ...others];
      })();

      let chosenGenre: string | null = null;
      let replacement: SeedMovie | null = null;

      for (const g of candidateGenres) {
        const pool = mutable[g] ?? [];
        const filtered = pool.filter((mv) => !excludeKeys.has(keyFor(g, mv)));
        if (filtered.length === 0) continue;
        const pick = filtered[Math.floor(Math.random() * filtered.length)];
        // Remove from the actual pool
        const idx = pool.findIndex((mv) => mv.title === pick.title && mv.year === pick.year);
        if (idx >= 0) pool.splice(idx, 1);
        chosenGenre = g;
        replacement = pick;
        break;
      }

      if (!replacement || !chosenGenre) {
        // Nothing left anywhere to swap in; leave the card as-is.
        return old;
      }

      setCards((prev) => {
        const next = prev.slice();
        next[index] = { genre: chosenGenre!, movie: replacement! };
        return next;
      });

      // Reset the animating index after the animation window
      if (animTimer.current) clearTimeout(animTimer.current);
      animTimer.current = setTimeout(() => setAnimatingIndex(null), 200);

      return { ...mutable };
    });
  }

  // Fade-in on swap for the specific active card only
  function AnimatedSwap({ token, active, children }: PropsWithChildren<{ token: string; active: boolean }>) {
    const [visible, setVisible] = useState(true);
    // Ensure we start at opacity 0 for the new token before paint, then fade in
    useLayoutEffect(() => {
      if (!active) return;
      setVisible(false);
      const t = requestAnimationFrame(() => setVisible(true));
      return () => cancelAnimationFrame(t);
    }, [token, active]);

    return (
      <div
        style={{
          transition: "opacity 180ms ease, transform 180ms ease",
          opacity: active ? (visible ? 1 : 0) : 1,
          transform: active ? (visible ? "none" : "scale(0.98)") : "none",
        }}
      >
        {children}
      </div>
    );
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
        {cards.map(({ genre, movie: m }, i) => {
          const k = keyFor(genre, m);
          const r = ratings[k];
          return (
            <Card key={i} className="overflow-hidden">
              <CardContent className="p-0">
                <AnimatedSwap token={k} active={i === animatingIndex}>
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
                  {m.vibes && m.vibes.length > 0 && (
                    <div className="mt-1 text-[11px] text-muted-foreground/80 leading-snug">
                      {m.vibes.join(" • ")}
                    </div>
                  )}
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
                      onClick={() => handleSkip(i, genre, m)}
                      aria-pressed={r === "skip"}
                      title="Skip and show another"
                    >
                      <Shuffle className="h-4 w-4" />
                    </Button>
                  </div>
                </div>
                </AnimatedSwap>
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
