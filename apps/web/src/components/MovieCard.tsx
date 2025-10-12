import ReactMarkdown from "react-markdown";
import clsx from "clsx";
import { Heart, ThumbsDown, ThumbsUp } from "lucide-react";
import type { ParsedMovie } from "../utils/parseMarkdown";
import { hasAnyRating, hasValidScore } from "@/utils/checkScores";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";

type MovieCardExtras = {
  releaseYear?: number;
  providers?: string[];
  whyMarkdown?: string;
  whyText?: string;
  isWhyLoading?: boolean;
  isRatingsLoading?: boolean;
  layout?: "grid" | "wide";
};

type MovieCardInput = Partial<ParsedMovie> & MovieCardExtras & {
  title: string;
  imdbRating?: number | string | null;
  rottenTomatoesRating?: number | string | null;
  posterUrl?: string;
  backdropUrl?: string;
};

interface Props {
  movie: MovieCardInput;
  layout?: "grid" | "wide";
  feedback?: {
    value?: "love" | "like" | "dislike";
    disabled?: boolean;
    onChange: (value: "love" | "like" | "dislike") => void;
  };
  onTrailerClick?: () => void;
}

export default function MovieCard({ movie, layout = "grid", feedback, onTrailerClick }: Props) {
  const posterUrl = movie.posterUrl ?? undefined;
  const backdropUrl = movie.backdropUrl ?? undefined;
  const providers = movie.providers ?? [];
  const genres = movie.genres ?? [];
  const imdbRaw = movie.imdbRating ?? undefined;
  const rtRaw = movie.rottenTomatoesRating ?? undefined;
  const isWhyLoading = movie.isWhyLoading ?? false;
  const isRatingsLoading = movie.isRatingsLoading ?? false;
  const hasRating = !isRatingsLoading && hasAnyRating({ imdbRating: imdbRaw, rottenTomatoesRating: rtRaw });
  const whySource = movie.whyMarkdown ?? movie.whyText ?? movie.why ?? "";
  const hasWhyContent = !isWhyLoading && typeof whySource === "string" && whySource.trim().length > 0;
  const isWide = layout === "wide";

  const containerClass = clsx(
    "group relative flex h-full flex-col overflow-hidden rounded-xl border border-white/10 bg-background/95 text-white transition-all duration-200 hover:shadow-[0_8px_30px_rgba(0,0,0,0.4)] hover:scale-[1.01]",
    isWide ? "md:hover:-translate-y-0.5" : "hover:-translate-y-1",
  );

  const contentClass = clsx(
    "relative z-10 flex flex-col gap-4 p-4 md:flex-row",
    isWide && "gap-6 p-6",
  );

  const posterWrapperClass = clsx(
    "mx-auto flex w-full max-w-[11rem] flex-shrink-0 overflow-hidden rounded-lg bg-black/30 md:mx-0 md:w-44",
    isWide && "max-w-[12rem] md:w-48",
  );

  const titleClass = "text-2xl font-semibold leading-tight text-white";
  const metaClass = "text-sm text-zinc-300";
  const bulletClass = "text-zinc-500";
  const ratingContainerClass = "flex flex-wrap items-center gap-2 text-sm text-zinc-300";
  const whyHeaderClass = "text-xs font-semibold uppercase tracking-wide text-zinc-400";
  const emptyWhyClass = "text-sm italic text-zinc-400";
  const providerBadgeClass = "rounded-full bg-white/10 px-2.5 py-1 text-xs font-medium text-zinc-100 backdrop-blur";
  const feedbackValue = feedback?.value;
  const feedbackDisabled = feedback?.disabled ?? false;
  const feedbackLabelClass = "text-xs font-semibold uppercase tracking-wide text-zinc-400";

  return (
    <Card className={containerClass}>
      {backdropUrl ? (
        <div className="pointer-events-none absolute inset-0 z-0">
          {/* Backdrop image with consistent opacity across /query and /discover */}
          <div
            className="h-full w-full bg-cover bg-center blur-[1px] opacity-15 transition-opacity duration-300 group-hover:opacity-20"
            style={{ backgroundImage: `url(${backdropUrl})` }}
          />
          <div className="absolute inset-0 bg-gradient-to-b from-slate-800/80 via-black/40 to-transparent" />
        </div>
      ) : null}

      <CardContent className={contentClass}>
        <div className={posterWrapperClass}>
          {posterUrl ? (
            <img
              src={posterUrl}
              alt={movie.title}
              className="h-full w-full object-cover transition-transform duration-300 group-hover:scale-[1.01]"
              loading="lazy"
            />
          ) : (
            <div className="flex h-full w-full items-center justify-center px-3 text-center text-xs text-muted-foreground/70">
              Poster coming soon
            </div>
          )}
        </div>

        <div className="flex flex-1 flex-col gap-4 text-sm">
          <div className="space-y-2">
            <div className="flex flex-wrap items-baseline gap-3">
              <h2 className={titleClass}>{movie.title}</h2>
              {movie.releaseYear ? (
                <span className="rounded-full border border-white/20 px-3 py-0.5 text-xs text-white/70">
                  {movie.releaseYear}
                </span>
              ) : null}
            </div>

            {providers.length > 0 ? (
              <div className="flex flex-wrap gap-2">
                {providers.map((provider) => (
                  <span
                    key={provider}
                    className={providerBadgeClass}
                  >
                    {provider}
                  </span>
                ))}
              </div>
            ) : null}

            {genres.length > 0 ? (
              <div className={metaClass}>
                <span className="font-medium text-white">Genres:</span> {genres.join(", ")}
              </div>
            ) : null}

            <div className="min-h-[1.25rem]">
              {isRatingsLoading ? (
                <div className="flex items-center gap-2 animate-pulse">
                  <span className="h-3 w-16 rounded bg-muted/80" />
                  <span className="h-3 w-12 rounded bg-muted/70" />
                </div>
              ) : hasRating ? (
                <p className={ratingContainerClass}>
                  {hasValidScore(imdbRaw) ? <span>⭐ {formatRating(imdbRaw)}/10</span> : null}
                  {hasValidScore(imdbRaw) && hasValidScore(rtRaw) ? (
                    <span className={bulletClass}>•</span>
                  ) : null}
                  {hasValidScore(rtRaw) ? <span>🍅 {formatRating(rtRaw)}%</span> : null}
                </p>
              ) : (
                <span className="text-sm italic text-zinc-400">Ratings pending</span>
              )}
            </div>
          </div>

          <div className="space-y-2 text-sm text-zinc-300">
            <div className={whyHeaderClass}>Why this fits your taste</div>
            {isWhyLoading ? (
              <div className="space-y-2 animate-pulse">
                <div className="h-3 w-full rounded bg-muted/80" />
                <div className="h-3 w-5/6 rounded bg-muted/70" />
                <div className="h-3 w-4/6 rounded bg-muted/60" />
              </div>
            ) : hasWhyContent ? (
              <div className="prose prose-invert prose-sm max-w-none text-base leading-relaxed text-zinc-200">
                <ReactMarkdown>{whySource}</ReactMarkdown>
              </div>
            ) : (
              <p className={emptyWhyClass}>We're still working on a personalized reason for this pick.</p>
            )}
          </div>

          {movie.trailerKey ? (
            <div>
              <a
                href={`https://www.youtube.com/watch?v=${movie.trailerKey}`}
                target="_blank"
                rel="noopener noreferrer"
                onClick={() => onTrailerClick?.()}
                className="inline-flex items-center gap-2 text-base font-medium text-blue-300 hover:underline"
              >
                <img src="/icons/play_icon.png" alt="Play" className="h-5 w-5" />
                Watch trailer
              </a>
            </div>
          ) : null}

          {feedback ? (
            <div className="mt-4 flex flex-col gap-2">
              <span className={feedbackLabelClass}>What do you think?</span>
              <div className="flex items-center gap-2">
                <FeedbackButton
                  icon={Heart}
                  label="Love"
                  active={feedbackValue === "love"}
                  disabled={feedbackDisabled}
                  onClick={() => feedback.onChange("love")}
                  activeClass="bg-pink-500/20 text-pink-200 border-pink-400/50"
                />
                <FeedbackButton
                  icon={ThumbsUp}
                  label="Like"
                  active={feedbackValue === "like"}
                  disabled={feedbackDisabled}
                  onClick={() => feedback.onChange("like")}
                  activeClass="bg-emerald-500/15 text-emerald-200 border-emerald-400/50"
                />
                <FeedbackButton
                  icon={ThumbsDown}
                  label="Not for me"
                  active={feedbackValue === "dislike"}
                  disabled={feedbackDisabled}
                  onClick={() => feedback.onChange("dislike")}
                  activeClass="bg-amber-500/15 text-amber-200 border-amber-400/50"
                />
              </div>
            </div>
          ) : null}
        </div>
      </CardContent>
    </Card>
  );
}

type FeedbackIcon = typeof Heart;

function FeedbackButton({
  icon: Icon,
  label,
  active,
  disabled,
  onClick,
  activeClass,
}: {
  icon: FeedbackIcon;
  label: string;
  active: boolean;
  disabled: boolean;
  onClick: () => void;
  activeClass: string;
}) {
  return (
    <Button
      type="button"
      variant="ghost"
      size="sm"
      disabled={disabled}
      aria-disabled={disabled}
      aria-pressed={active}
      onClick={onClick}
      className={clsx(
        "h-9 w-9 rounded-full border border-white/20 bg-black/40 px-0 text-zinc-200 transition-colors hover:bg-white/10",
        active && activeClass,
        disabled && "opacity-60",
      )}
      title={label}
    >
      <Icon className="h-4 w-4" aria-hidden="true" />
      <span className="sr-only">{label}</span>
    </Button>
  );
}

function formatRating(value: unknown): string {
  if (typeof value === "number" && Number.isFinite(value)) {
    return Number.isInteger(value) ? value.toString() : value.toFixed(1);
  }
  if (typeof value === "string") {
    const trimmed = value.trim();
    if (!trimmed) return "";
    const numeric = Number(trimmed);
    if (!Number.isNaN(numeric)) {
      return Number.isInteger(numeric) ? numeric.toString() : numeric.toFixed(1);
    }
    return trimmed;
  }
  return "";
}
