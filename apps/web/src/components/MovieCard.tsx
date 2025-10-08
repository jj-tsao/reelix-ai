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
}

export default function MovieCard({ movie, layout = "grid", feedback }: Props) {
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

  const containerClass =
    isWide
      ? "group relative flex h-full flex-col overflow-hidden border border-border/70 bg-background/95 text-foreground transition-[transform,box-shadow] duration-200 hover:-translate-y-0.5 hover:shadow-2xl"
      : "group relative flex h-full flex-col overflow-hidden border border-border/70 bg-background/95 text-foreground transition-[transform,box-shadow] duration-200 hover:-translate-y-1 hover:shadow-xl";

  const contentClass = isWide ? "relative z-10 flex flex-col gap-6 p-6 md:flex-row" : "relative z-10 flex flex-col gap-4 p-4 md:flex-row";
  const posterWrapperClass =
    isWide
      ? "mx-auto flex w-full max-w-[12rem] flex-shrink-0 overflow-hidden rounded-lg bg-muted md:mx-0 md:w-48"
      : "mx-auto flex w-full max-w-[10.5rem] flex-shrink-0 overflow-hidden rounded-lg bg-muted md:mx-0 md:w-44";
  const titleClass = isWide
    ? "text-2xl md:text-[26px] font-semibold leading-tight text-white"
    : "text-xl font-semibold leading-tight text-foreground";
  const metaClass = isWide ? "text-sm text-white/80" : "text-xs text-muted-foreground";
  const bulletClass = isWide ? "text-white/60" : "text-muted-foreground/60";
  const ratingContainerClass = isWide
    ? "flex flex-wrap items-center gap-2 text-sm text-white/85"
    : "flex flex-wrap items-center gap-2 text-sm text-muted-foreground";
  const whyHeaderClass = isWide
    ? "text-sm font-semibold uppercase tracking-wide text-white/70"
    : "text-xs font-semibold uppercase tracking-wide text-muted-foreground/80";
  const emptyWhyClass = isWide ? "text-sm italic text-white/60" : "text-xs italic text-muted-foreground/70";
  const providerBadgeClass = isWide
    ? "rounded-full bg-white/10 px-2.5 py-1 text-xs font-medium text-white/90 backdrop-blur"
    : "rounded-full bg-primary/10 px-2.5 py-1 text-xs font-medium text-primary";
  const feedbackValue = feedback?.value;
  const feedbackDisabled = feedback?.disabled ?? false;
  const feedbackLabelClass = isWide
    ? "text-xs font-semibold uppercase tracking-wide text-white/60"
    : "text-[10px] font-semibold uppercase tracking-wide text-muted-foreground/70";

  return (
    <Card className={containerClass}>
      {backdropUrl ? (
        <div
          className={
            isWide
              ? "pointer-events-none absolute inset-0 z-0 opacity-80 transition-opacity duration-300 group-hover:opacity-100"
              : "pointer-events-none absolute inset-0 z-0 opacity-60 transition-opacity duration-300 group-hover:opacity-90"
          }
        >
          <div
            className={
              isWide
                ? "h-full w-full bg-cover bg-center opacity-30 blur-[2px]"
                : "h-full w-full bg-cover bg-center opacity-40 blur-sm"
            }
            style={{ backgroundImage: `url(${backdropUrl})` }}
          />
          <div
            className={
              isWide
                ? "absolute inset-0 bg-gradient-to-b from-slate-950/95 via-slate-950/65 to-slate-900/10"
                : "absolute inset-0 bg-gradient-to-br from-background via-background/95 to-background/85"
            }
          />
          {isWide ? (
            <div className="absolute inset-0 bg-gradient-radial from-white/8 via-transparent to-transparent mix-blend-soft-light opacity-70" />
          ) : null}
          {isWide ? (
            <div className="absolute inset-0 bg-gradient-to-t from-slate-900/20 via-transparent to-transparent" />
          ) : null}
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
                <span className={isWide ? "rounded-full border border-white/20 px-3 py-0.5 text-xs text-white/70" : "rounded-full border border-border px-2 py-0.5 text-xs text-muted-foreground"}>
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
                <span className={isWide ? "font-medium text-white" : "font-semibold text-foreground/80"}>Genres:</span> {genres.join(", ")}
              </div>
            ) : null}

            <div className={isWide ? "min-h-[1.25rem]" : "min-h-[1.25rem] text-xs text-muted-foreground"}>
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
                <span className={isWide ? "text-sm italic text-white/60" : "text-xs italic text-muted-foreground/70"}>Ratings pending</span>
              )}
            </div>
          </div>

          <div className="space-y-2 text-sm text-muted-foreground">
            <div className={whyHeaderClass}>Why you might enjoy it</div>
            {isWhyLoading ? (
              <div className="space-y-2 animate-pulse">
                <div className="h-3 w-full rounded bg-muted/80" />
                <div className="h-3 w-5/6 rounded bg-muted/70" />
                <div className="h-3 w-4/6 rounded bg-muted/60" />
              </div>
            ) : hasWhyContent ? (
              isWide ? (
                <div className="text-base leading-relaxed text-white/90">
                  <ReactMarkdown>{whySource}</ReactMarkdown>
                </div>
              ) : (
                <div className="prose prose-sm prose-slate dark:prose-invert max-w-none leading-relaxed">
                  <ReactMarkdown>{whySource}</ReactMarkdown>
                </div>
              )
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
                className={isWide ? "inline-flex items-center gap-2 text-sm font-medium text-white hover:text-white/80" : "inline-flex items-center gap-2 text-sm font-medium text-primary hover:text-primary/80"}
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
                  activeClass={isWide ? "bg-pink-500/20 text-pink-200 border-pink-400/50" : "bg-pink-100 text-pink-700 border-pink-300"}
                />
                <FeedbackButton
                  icon={ThumbsUp}
                  label="Like"
                  active={feedbackValue === "like"}
                  disabled={feedbackDisabled}
                  onClick={() => feedback.onChange("like")}
                  activeClass={isWide ? "bg-emerald-500/15 text-emerald-200 border-emerald-400/50" : "bg-green-100 text-green-700 border-green-300"}
                />
                <FeedbackButton
                  icon={ThumbsDown}
                  label="Not for me"
                  active={feedbackValue === "dislike"}
                  disabled={feedbackDisabled}
                  onClick={() => feedback.onChange("dislike")}
                  activeClass={isWide ? "bg-amber-500/15 text-amber-200 border-amber-400/50" : "bg-amber-100 text-amber-800 border-amber-300"}
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
        "h-9 w-9 rounded-full border border-transparent px-0 text-muted-foreground transition-colors",
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
