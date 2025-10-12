import { type FormEvent, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "@/features/auth/hooks/useAuth";

const ALL_CHIPS = [
  "Psychological thrillers with a satirical tone",
  "Playful rom-coms with quirky characters",
  "Gritty neo-noirs with stylish actions",
  "Heartwarming coming-of-age drama",
  "Mind-bending time-travel sci-fi",
  "High-stakes espionage adventures",
];

const LAST_PROMPT_KEY = "reelix_last_prompt";

export default function LandingPage() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [vibe, setVibe] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [showAllChips, setShowAllChips] = useState(false);

  // Restore last prompt
  useEffect(() => {
    const prev = sessionStorage.getItem(LAST_PROMPT_KEY);
    if (prev) setVibe(prev);
  }, []);

  // Persist while typing
  useEffect(() => {
    if (vibe) sessionStorage.setItem(LAST_PROMPT_KEY, vibe);
  }, [vibe]);

  const handleBuildTaste = () => {
    const target = user ? "/taste" : "/taste?first_run=1";
    navigate(target);
  };

  function submitQuery(text?: string) {
    const q = (text ?? vibe).trim() || "Hard-boiled investigative crime drama";
    setSubmitting(true);
    sessionStorage.setItem(LAST_PROMPT_KEY, q);
    // your query page expects ?q=
    navigate(`/query?q=${encodeURIComponent(q)}`);
  }

  const handleExploreSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    submitQuery();
  };

  const helperId = "vibe-helper";
  const visibleChips = useMemo(
    () => (showAllChips ? ALL_CHIPS : ALL_CHIPS.slice(0, 3)),
    [showAllChips]
  );

  return (
    <main className="mx-auto flex min-h-[70vh] w-full max-w-5xl flex-col items-center justify-center gap-8 px-6 text-center">
      {/* HERO */}
      <section className="flex max-w-3xl flex-col items-center gap-6">
        <div className="space-y-4">
          <h1 className="text-4xl font-semibold tracking-tight text-foreground sm:text-4xl">
            Find your next watch. Personalized to your taste.
          </h1>
          <p className="text-base text-muted-foreground sm:text-lg">
            Reelix is your personal AI curator. It learns your taste and brings
            you films and shows you’ll love.
          </p>
        </div>

        {/* Primary CTA */}
        <div className="flex w-full flex-col items-center gap-3">
          <button
            type="button"
            onClick={handleBuildTaste}
            className="inline-flex items-center justify-center rounded-full bg-primary px-6 py-3 text-sm font-medium text-primary-foreground shadow-sm transition hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
          >
            Personalize my feed
          </button>
          <span className="text-xs text-muted-foreground">
            Takes under a minute. No sign-up needed.
          </span>
        </div>
      </section>

      {/* SECONDARY CTA: input + icon + example chips */}
      <section className="mt-6 flex w-full max-w-xl flex-col items-center gap-3">
        <p className="text-xs text-muted-foreground">or explore by vibe</p>

        <form
          onSubmit={handleExploreSubmit}
          role="search"
          aria-label="Explore by vibe"
          className="w-full"
          aria-describedby={helperId}
        >
          <label className="sr-only" htmlFor="landing-vibe-input">
            Explore by vibe
          </label>
          <div className="flex w-full items-center gap-2 rounded-full border border-border/60 bg-background px-4 py-2 transition focus-within:border-primary">
            <input
              id="landing-vibe-input"
              type="text"
              value={vibe}
              onChange={(e) => setVibe(e.target.value)}
              placeholder="Describe a vibe… e.g., Hard-boiled crime drama"
              className="w-full bg-transparent text-sm text-foreground placeholder:text-muted-foreground focus:outline-none"
              aria-label="Vibe prompt"
              autoComplete="off"
              disabled={submitting}
            />
            <button
              type="submit"
              disabled={submitting}
              className="inline-flex h-9 w-9 items-center justify-center rounded-full hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary disabled:opacity-60"
              aria-label="Submit vibe"
              title="Explore by vibe"
            >
              {/* search icon */}
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                <path
                  d="M21 21l-4.3-4.3M10.5 18a7.5 7.5 0 1 1 0-15 7.5 7.5 0 0 1 0 15Z"
                  stroke="currentColor"
                  strokeWidth="1.6"
                  strokeLinecap="round"
                />
              </svg>
            </button>
          </div>
        </form>

        {/* Example chips (3 + 'More…' expander) */}
        <div className="flex w-full flex-wrap items-center justify-center gap-2">
          {visibleChips.map((text) => (
            <button
              key={text}
              type="button"
              onClick={() => submitQuery(text)}
              disabled={submitting}
              className="inline-flex max-w-full items-center rounded-full border border-border bg-background px-3 py-1.5 text-xs text-foreground transition-transform duration-150 hover:-translate-y-0.5 hover:border-primary/70 hover:bg-background/70 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary disabled:opacity-60"
              aria-label={`Try: ${text}`}
              title={text}
            >
              <span className="truncate">{text}</span>
            </button>
          ))}

          <button
            type="button"
            onClick={() => setShowAllChips((s) => !s)}
            className="inline-flex items-center rounded-full border border-border bg-background px-3 py-1.5 text-xs text-muted-foreground hover:border-primary/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
            aria-expanded={showAllChips}
            aria-controls="chip-list"
          >
            {showAllChips ? "Show less" : "More…"}
          </button>
        </div>

        <span id={helperId} className="text-xs text-muted-foreground">
          Type a mood or tap an example to see smart picks.
        </span>
      </section>
    </main>
  );
}
