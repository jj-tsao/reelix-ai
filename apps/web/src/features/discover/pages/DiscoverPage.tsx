import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import MovieCard from "@/components/MovieCard";
import { Button } from "@/components/ui/button";
import { useToast } from "@/components/ui/useToast";
import { useAuth } from "@/features/auth/hooks/useAuth";
import { getSessionId } from "@/utils/session";
import type { DiscoverCardData } from "../types";
import type { DiscoverStreamEvent } from "../api";
import { fetchDiscoverInitial, getAccessToken, logDiscoverFinalRecs, streamDiscoverWhy } from "../api";
import DiscoverGridSkeleton from "../components/DiscoverGridSkeleton";
import StreamStatusBar, { type StreamStatusState } from "../components/StreamStatusBar";
import { upsertUserInteraction, type RatingValue } from "@/features/taste_onboarding/api";
import { rebuildTasteProfile } from "@/api";
import { hasTasteProfile, type TasteProfileHttpError } from "@/features/taste_profile/api";

type DiscoverRating = Exclude<RatingValue, "dismiss">;

function toDiscoverCard(item: {
  id?: string;
  media_id: number | string;
  title: string;
  release_year?: number | string | null;
  poster_url?: string | null;
  backdrop_url?: string | null;
  trailer_key?: string | null;
  genres?: unknown;
  providers?: unknown;
}): DiscoverCardData {
  return {
    id: item.id,
    mediaId: normalizeMediaId(item.media_id),
    title: item.title,
    releaseYear: toOptionalNumber(item.release_year),
    posterUrl: typeof item.poster_url === "string" ? item.poster_url : undefined,
    backdropUrl: typeof item.backdrop_url === "string" ? item.backdrop_url : undefined,
    trailerKey: typeof item.trailer_key === "string" ? item.trailer_key : undefined,
    genres: toStringArray(item.genres),
    providers: toStringArray(item.providers),
    imdbRating: null,
    rottenTomatoesRating: null,
    whyMarkdown: undefined,
    whyText: undefined,
    isWhyLoading: true,
    isRatingsLoading: true,
  };
}

function normalizeMediaId(value: unknown): string {
  if (typeof value === "number" && Number.isFinite(value)) return String(value);
  if (typeof value === "string" && value.trim() !== "") {
    return value.trim();
  }
  return "";
}

function toOptionalNumber(value: unknown): number | undefined {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim() !== "") {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return undefined;
}

function toStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value
    .map((entry) => {
      if (typeof entry === "string") return entry;
      if (entry && typeof entry === "object") {
        if ("name" in entry && typeof (entry as { name: unknown }).name === "string") {
          return (entry as { name: string }).name;
        }
        if ("provider" in entry && typeof (entry as { provider: unknown }).provider === "string") {
          return (entry as { provider: string }).provider;
        }
      }
      return null;
    })
    .filter((entry): entry is string => Boolean(entry));
}

type CardMap = Record<string, DiscoverCardData>;

type PageState = "idle" | "loading" | "ready" | "error" | "unauthorized" | "missingTasteProfile";

type StreamPhase = StreamStatusState["status"];

const RATING_COUNT_KEY = "rating_count";
const PENDING_REBUILD_KEY = "pending_rebuild";
const LAST_REBUILD_KEY = "last_rebuild_at";
const MIN_RATINGS_FOR_REBUILD = 2;
const REBUILD_DELAY_MS = 10_000;
const REBUILD_COOLDOWN_MS = 2 * 60 * 1000;

function parseStoredNumber(value: string | null): number | null {
  if (typeof value !== "string") return null;
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : null;
}

function isTruthyString(value: string | null): boolean {
  return value === "true" || value === "1";
}

class DiscoverRebuildController {
  private ratingTimer: ReturnType<typeof setTimeout> | null = null;
  private cooldownTimer: ReturnType<typeof setTimeout> | null = null;
  private ratingCount = 0;
  private pendingRebuild = false;
  private lastRebuildAt: number | null = null;
  private rebuildInFlight = false;
  private hydrated = false;

  hydrate() {
    if (typeof window === "undefined" || this.hydrated) return;

    const storedCount = parseStoredNumber(window.localStorage.getItem(RATING_COUNT_KEY));
    this.ratingCount = storedCount && storedCount > 0 ? Math.floor(storedCount) : 0;
    window.localStorage.setItem(RATING_COUNT_KEY, String(this.ratingCount));

    this.pendingRebuild = isTruthyString(window.localStorage.getItem(PENDING_REBUILD_KEY));

    const storedLast = parseStoredNumber(window.localStorage.getItem(LAST_REBUILD_KEY));
    this.lastRebuildAt = storedLast && storedLast > 0 ? storedLast : null;

    this.hydrated = true;
    this.resumeCooldown();
  }

  registerRating() {
    if (typeof window === "undefined") return;
    this.ratingCount += 1;
    window.localStorage.setItem(RATING_COUNT_KEY, String(this.ratingCount));
    this.startRatingTimer();
  }

  dispose() {
    if (this.ratingTimer) {
      clearTimeout(this.ratingTimer);
      this.ratingTimer = null;
    }
    if (this.cooldownTimer) {
      clearTimeout(this.cooldownTimer);
      this.cooldownTimer = null;
    }
  }

  private startRatingTimer() {
    if (typeof window === "undefined") return;
    if (this.ratingTimer) {
      clearTimeout(this.ratingTimer);
    }
    this.ratingTimer = setTimeout(() => {
      this.ratingTimer = null;
      if (this.ratingCount >= MIN_RATINGS_FOR_REBUILD) {
        void this.tryRebuild();
      }
    }, REBUILD_DELAY_MS);
  }

  private clearRatingTimer() {
    if (this.ratingTimer) {
      clearTimeout(this.ratingTimer);
      this.ratingTimer = null;
    }
  }

  private resumeCooldown() {
    if (typeof window === "undefined") return;
    if (this.cooldownTimer) {
      clearTimeout(this.cooldownTimer);
      this.cooldownTimer = null;
    }
    if (this.lastRebuildAt === null) {
      if (this.pendingRebuild && this.ratingCount >= MIN_RATINGS_FOR_REBUILD && !this.rebuildInFlight) {
        void this.tryRebuild();
      }
      return;
    }
    const remaining = REBUILD_COOLDOWN_MS - (Date.now() - this.lastRebuildAt);
    if (remaining <= 0) {
      if (this.pendingRebuild && !this.rebuildInFlight) {
        void this.tryRebuild();
      }
      return;
    }
    this.cooldownTimer = setTimeout(() => {
      this.cooldownTimer = null;
      if (this.pendingRebuild && !this.rebuildInFlight) {
        void this.tryRebuild();
      }
    }, remaining);
  }

  private async tryRebuild() {
    if (this.rebuildInFlight) return;
    if (typeof window === "undefined") return;
    if (this.ratingCount < MIN_RATINGS_FOR_REBUILD && !this.pendingRebuild) return;

    const now = Date.now();
    if (this.lastRebuildAt !== null && now - this.lastRebuildAt < REBUILD_COOLDOWN_MS) {
      if (!this.pendingRebuild) {
        this.pendingRebuild = true;
        window.localStorage.setItem(PENDING_REBUILD_KEY, "true");
      }
      this.resumeCooldown();
      return;
    }

    this.rebuildInFlight = true;

    try {
      await rebuildTasteProfile();
      this.ratingCount = 0;
      window.localStorage.setItem(RATING_COUNT_KEY, "0");
      this.pendingRebuild = false;
      window.localStorage.removeItem(PENDING_REBUILD_KEY);
      this.clearRatingTimer();
    } catch (error) {
      console.warn("Failed to rebuild taste profile from discover feed", error);
      this.pendingRebuild = true;
      window.localStorage.setItem(PENDING_REBUILD_KEY, "true");
    } finally {
      this.lastRebuildAt = now;
      window.localStorage.setItem(LAST_REBUILD_KEY, String(now));
      this.rebuildInFlight = false;
      this.resumeCooldown();
    }
  }
}

export default function DiscoverPage() {
  const [pageState, setPageState] = useState<PageState>("idle");
  const [cards, setCards] = useState<CardMap>({});
  const [order, setOrder] = useState<string[]>([]);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [streamState, setStreamState] = useState<StreamStatusState>({ status: "idle" });
  const [refreshIndex, setRefreshIndex] = useState(0);
  const [feedbackById, setFeedbackById] = useState<Partial<Record<string, DiscoverRating>>>({});
  const [pendingFeedback, setPendingFeedback] = useState<Partial<Record<string, boolean>>>({});
  const queryIdRef = useRef<string | null>(null);
  const loggedQueryIdRef = useRef<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const { toast } = useToast();
  const { user } = useAuth();
  const navigate = useNavigate();
  const rebuildControllerRef = useRef<DiscoverRebuildController | null>(null);

  if (!rebuildControllerRef.current) {
    rebuildControllerRef.current = new DiscoverRebuildController();
  }

  const rebuildController = rebuildControllerRef.current;

  useEffect(() => {
    rebuildController.hydrate();
    return () => {
      rebuildController.dispose();
    };
  }, [rebuildController]);

  const orderedCards = useMemo(
    () => order.map((id) => cards[id]).filter((card): card is DiscoverCardData => Boolean(card)),
    [order, cards],
  );

  const handleStreamEvent = useCallback((event: DiscoverStreamEvent) => {
    if (event.type === "started") {
      setStreamState({ status: "streaming", message: "Streaming reasons…" });
      return;
    }
    if (event.type === "progress") {
      const message = typeof event.data?.message === "string" ? event.data.message : "Still thinking…";
      setStreamState((prev) => ({
        status: prev.status === "idle" ? "streaming" : prev.status,
        message,
      }));
      return;
    }
    if (event.type === "why_delta") {
      const mediaId = normalizeMediaId(event.data.media_id);
      if (!mediaId) return;
      setCards((prev) => {
        const next = { ...prev };
        const existing = next[mediaId];
        if (!existing) return prev;
        next[mediaId] = {
          ...existing,
          imdbRating:
            event.data.imdb_rating !== undefined ? event.data.imdb_rating ?? null : existing.imdbRating,
          rottenTomatoesRating:
            event.data.rotten_tomatoes_rating !== undefined
              ? event.data.rotten_tomatoes_rating ?? null
              : existing.rottenTomatoesRating,
          whyMarkdown: event.data.why_you_might_enjoy_it ?? existing.whyMarkdown,
          whyText: event.data.why_you_might_enjoy_it ? undefined : existing.whyText,
          isWhyLoading: event.data.why_you_might_enjoy_it ? false : existing.isWhyLoading,
          isRatingsLoading:
            event.data.imdb_rating !== undefined || event.data.rotten_tomatoes_rating !== undefined
              ? false
              : existing.isRatingsLoading,
        };
        return next;
      });
      return;
    }
    if (event.type === "done") {
      setStreamState({ status: "done", message: "Finished streaming" });
      setCards((prev) => finalizePending(prev));
      return;
    }
    if (event.type === "error") {
      const message = typeof event.data?.message === "string" ? event.data.message : "Stream error";
      setStreamState({ status: "error", message });
      setCards((prev) => finalizePending(prev));
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      setPageState("loading");
      setErrorMessage(null);
      setStreamState({ status: "idle" });
      abortRef.current?.abort();
      const sessionId = getSessionId();
      const queryId = `${sessionId}_${Date.now()}`;
      queryIdRef.current = queryId;
      loggedQueryIdRef.current = null;

      try {
        const token = await getAccessToken();
        if (!token) {
          if (!cancelled) {
            setPageState("unauthorized");
            setErrorMessage("Sign in to view your discovery feed.");
            setCards({});
            setOrder([]);
          }
          return;
        }

        let profileExists = false;
        try {
          profileExists = await hasTasteProfile(token);
        } catch (profileError) {
          if (cancelled) return;
          const status = (profileError as TasteProfileHttpError | undefined)?.status;
          if (status === 401 || status === 403) {
            setPageState("unauthorized");
            setErrorMessage("Sign in to view your discovery feed.");
            setCards({});
            setOrder([]);
            return;
          }
          throw profileError;
        }

        if (!profileExists) {
          if (!cancelled) {
            setCards({});
            setOrder([]);
            abortRef.current = null;
            setStreamState({ status: "idle" });
            setPageState("missingTasteProfile");
          }
          return;
        }

        const response = await fetchDiscoverInitial(token, {
          sessionId,
          queryId,
          mediaType: "movie",
          page: 1,
          pageSize: 12,
          includeWhy: false,
        });
        if (cancelled) return;

        const mapped: CardMap = {};
        response.items.forEach((item) => {
          const card = toDiscoverCard(item);
          if (!card.mediaId) return;
          mapped[card.mediaId] = card;
        });
        setCards(mapped);
        setOrder(
          response.items
            .map((item) => normalizeMediaId(item.media_id))
            .filter((id): id is string => Boolean(id)),
        );
        setPageState("ready");

        if (response.stream_url) {
          const controller = new AbortController();
          abortRef.current = controller;
          setStreamState({ status: "connecting", message: "Waiting for live insights…" });
          try {
            await streamDiscoverWhy({
              token,
              streamUrl: response.stream_url,
              signal: controller.signal,
              onEvent: handleStreamEvent,
            });
            if (!controller.signal.aborted) {
              setStreamState((prev) => (prev.status === "done" ? prev : { status: "done", message: "Stream complete" }));
              setCards((prev) => finalizePending(prev));
            }
          } catch (error) {
            if (controller.signal.aborted) {
              setStreamState({ status: "cancelled", message: "Stream cancelled" });
            } else {
              const message = error instanceof Error ? error.message : "Failed to stream insights";
              setStreamState({ status: "error", message });
            }
            setCards((prev) => finalizePending(prev));
          } finally {
            abortRef.current = null;
          }
        }
      } catch (error) {
        if (cancelled) return;
        const message = error instanceof Error ? error.message : "Failed to load discovery feed";
        setErrorMessage(message);
        setPageState("error");
      }
    };

    void load();

    return () => {
      cancelled = true;
      abortRef.current?.abort();
    };
  }, [refreshIndex, handleStreamEvent]);

  const streamPhase: StreamPhase = streamState.status;
  const canCancel = streamPhase === "connecting" || streamPhase === "streaming";

  const handleCancel = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  const handleRetry = useCallback(() => {
    setRefreshIndex((idx) => idx + 1);
  }, []);

  useEffect(() => {
    if (streamState.status !== "done") return;
    const queryId = queryIdRef.current;
    if (!queryId) return;
    if (loggedQueryIdRef.current === queryId) return;

    const finalRecs = orderedCards
      .map((card) => {
        const mediaId = Number(card.mediaId);
        if (!Number.isFinite(mediaId)) {
          return null;
        }
        const why = card.whyMarkdown ?? card.whyText;
        if (typeof why !== "string" || !why.trim()) {
          return null;
        }
        return { media_id: mediaId, why };
      })
      .filter((entry): entry is { media_id: number; why: string } => entry !== null);

    if (finalRecs.length === 0) return;

    loggedQueryIdRef.current = queryId;
    void logDiscoverFinalRecs({ queryId, finalRecs }).catch((error) => {
      console.warn("Failed to log discovery final recommendations", error);
    });
  }, [orderedCards, streamState.status]);

  const handleFeedback = useCallback(
    async (card: DiscoverCardData, rating: DiscoverRating) => {
      if (!card.mediaId) return;
      const id = card.mediaId;
      const previous = feedbackById[id];
      if (previous === rating) return;

      setFeedbackById((prev) => ({ ...prev, [id]: rating }));
      setPendingFeedback((prev) => ({ ...prev, [id]: true }));

      try {
        await upsertUserInteraction(
          {
            media_id: card.mediaId,
            title: card.title,
            vibes: card.genres,
            rating,
          },
          { source: "for_you_feed" },
        );
        rebuildController?.registerRating();
      } catch (error) {
        setFeedbackById((prev) => {
          const next = { ...prev };
          if (previous) {
            next[id] = previous;
          } else {
            delete next[id];
          }
          return next;
        });
        const message = error instanceof Error ? error.message : "Could not save feedback";
        toast({ title: "Feedback not saved", description: message, variant: "destructive" });
      } finally {
        setPendingFeedback((prev) => {
          const next = { ...prev };
          delete next[id];
          return next;
        });
      }
    },
    [feedbackById, toast, rebuildController],
  );

  const handleTrailerClick = useCallback(
    (card: DiscoverCardData) => {
      if (!card.mediaId) return;
      void upsertUserInteraction(
        {
          media_id: card.mediaId,
          title: card.title,
          vibes: card.genres,
          eventType: "trailer_view",
          weightOverride: 0.35,
        },
        { source: "for_you_feed" },
      ).catch((error) => {
        const message = error instanceof Error ? error.message : "Could not log trailer view";
        toast({ title: "Logging failed", description: message, variant: "destructive" });
      });
    },
    [toast],
  );

  const handleStartTasteOnboarding = useCallback(() => {
    const target = user ? "/taste" : "/taste?first_run=1";
    navigate(target);
  }, [navigate, user]);

  return (
    <section className="mx-auto flex w-full max-w-7xl flex-col gap-6 px-4 pb-24 pt-8">
      <header className="flex flex-col gap-2">
        <h1 className="text-3xl font-semibold tracking-tight text-foreground">For You</h1>
        <p className="text-sm text-muted-foreground">
          Fresh picks tailored to your taste. Updated live as our agent reasons in real time.
        </p>
      </header>

      {pageState === "loading" && <DiscoverGridSkeleton count={12} />}

      {pageState === "unauthorized" && (
        <div className="rounded-xl border border-dashed border-border bg-background/60 p-8 text-center">
          <p className="mb-4 text-sm text-muted-foreground">{errorMessage ?? "Sign in to continue."}</p>
          <Button onClick={handleRetry} variant="outline">
            Retry
          </Button>
        </div>
      )}

      {pageState === "error" && (
        <div className="rounded-xl border border-destructive/30 bg-destructive/10 p-6 text-sm text-destructive">
          {errorMessage}
          <div className="mt-4">
            <Button onClick={handleRetry} variant="ghost">
              Try again
            </Button>
          </div>
        </div>
      )}

      {pageState === "ready" && orderedCards.length === 0 && (
        <div className="rounded-xl border border-border bg-background/60 p-8 text-center text-sm text-muted-foreground">
          No recommendations available right now. Try refreshing in a moment.
        </div>
      )}

      {pageState === "missingTasteProfile" && (
        <div className="flex flex-col items-center gap-4 rounded-xl border border-border bg-background/60 px-8 py-12 text-center">
          <h2 className="text-xl font-semibold text-foreground">Build your taste profile</h2>
          <p className="max-w-md text-sm text-muted-foreground">
            Take a minute to share what you enjoy watching so we can personalize your discovery feed.
          </p>
          <div className="flex flex-col items-center gap-2">
            <Button className="rounded-full px-6" size="lg" onClick={handleStartTasteOnboarding}>
              Personalize my feed
            </Button>
            <span className="text-xs text-muted-foreground">Takes under a minute. No sign-up needed.</span>
          </div>
        </div>
      )}

      {orderedCards.length > 0 && (
        <div className="flex flex-col gap-4">
          {orderedCards.map(({ mediaId, ...card }) => (
            <MovieCard
              key={mediaId}
              movie={{
                ...card,
                imdbRating: card.imdbRating ?? undefined,
                rottenTomatoesRating: card.rottenTomatoesRating ?? undefined,
              }}
              feedback={{
                value: feedbackById[mediaId],
                disabled: pendingFeedback[mediaId] ?? false,
                onChange: (value) => handleFeedback({ mediaId, ...card }, value),
              }}
              onTrailerClick={() => handleTrailerClick({ mediaId, ...card })}
              layout="wide"
            />
          ))}
        </div>
      )}

      {pageState !== "missingTasteProfile" && (
        <StreamStatusBar state={streamState} onCancel={canCancel ? handleCancel : undefined} />
      )}
    </section>
  );
}

function finalizePending(map: CardMap): CardMap {
  const next: CardMap = {};
  for (const [key, value] of Object.entries(map)) {
    next[key] = {
      ...value,
      isWhyLoading: false,
      isRatingsLoading: false,
    };
  }
  return next;
}
