import { supabase } from "@/lib/supabase";
import type { Json, TablesInsert, TablesUpdate } from "@/types/supabase";

// Upsert into public.user_preferences for current user.
// Requires caller to pass user_id from the current session.
export async function upsertUserPreferences(row: TablesInsert<"user_preferences"> | TablesUpdate<"user_preferences">) {
  if (!("user_id" in row) || !row.user_id) {
    throw new Error("Missing user_id when upserting preferences");
  }
  // Ensure we overwrite these arrays on every request (clear to null when omitted)
  // PostgREST upsert only updates columns present in the payload.
  // By setting defaults to null first, we guarantee previous values are cleared if not provided now.
  const payload: TablesInsert<"user_preferences"> = {
    user_id: row.user_id as string,
    genres_include: null,
    keywords_include: null,
    // Limit spread to fields valid for an insert payload to avoid `any`.
    ...(row as Partial<TablesInsert<"user_preferences">>),
  };

  const { error } = await supabase
    .from("user_preferences")
    .upsert(payload, { onConflict: "user_id" });
  if (error) throw new Error(error.message);
}

// ---------- Taste Onboarding → user_interactions ----------
export type RatingValue = "love" | "like" | "dislike" | "dismiss";

const INTERACTION_SOURCE = "taste_onboarding";

// Canonical event names match DB check constraint exactly; map only weights.
const EVENT_WEIGHT: Record<RatingValue, number> = {
  love: 2.0,
  like: 1.0,
  dislike: -1.5,
  dismiss: 0.0,
};

type UserInteractionInsert = TablesInsert<"user_interactions"> & { title: string };

async function upsertInteractionRow(row: UserInteractionInsert) {
  // Always migrate legacy rows to set the concrete source column
  const updatePayload = {
    event_type: row.event_type,
    weight: row.weight,
    context_json: row.context_json,
    occurred_at: row.occurred_at,
    source: INTERACTION_SOURCE,
    title: row.title,
  } satisfies Partial<UserInteractionInsert>;

  // 1) Update rows that already have matching source in the column
  {
    const { data, error } = await supabase
      .from("user_interactions")
      .update(updatePayload)
      .eq("user_id", row.user_id)
      .eq("media_id", row.media_id)
      .eq("media_type", row.media_type)
      .eq("source", INTERACTION_SOURCE)
      .select("interaction_id");
    if (error) throw new Error(error.message);
    if ((data?.length ?? 0) > 0) return;
  }

  // 2) Update legacy rows that stored source in context_json
  {
    const { data, error } = await supabase
      .from("user_interactions")
      .update(updatePayload)
      .eq("user_id", row.user_id)
      .eq("media_id", row.media_id)
      .eq("media_type", row.media_type)
      .eq("context_json->>source", INTERACTION_SOURCE)
      .select("interaction_id");
    if (error) throw new Error(error.message);
    if ((data?.length ?? 0) > 0) return;
  }

  // 3) Update the most recent legacy row with unknown source (if any)
  {
    const { data: legacy, error: legacyErr } = await supabase
      .from("user_interactions")
      .select("interaction_id")
      .eq("user_id", row.user_id)
      .eq("media_id", row.media_id)
      .eq("media_type", row.media_type)
      .eq("source", "unknown")
      .order("occurred_at", { ascending: false })
      .limit(1);
    if (legacyErr) throw new Error(legacyErr.message);
    if (legacy && legacy.length > 0) {
      const id = legacy[0].interaction_id as number;
      const { error: updErr } = await supabase
        .from("user_interactions")
        .update(updatePayload)
        .eq("interaction_id", id);
      if (updErr) throw new Error(updErr.message);
      return;
    }
  }

  // 4) No existing row matched: use upsert on the unique key to avoid conflicts
  const { error: upsertErr } = await supabase
    .from("user_interactions")
    .upsert(row, { onConflict: "user_id, media_id, media_type, source" });
  if (upsertErr) {
    // Fallback: if ON CONFLICT isn't supported or RLS interferes, try a targeted update
    const { error: retryUpdErr } = await supabase
      .from("user_interactions")
      .update(updatePayload)
      .eq("user_id", row.user_id)
      .eq("media_id", row.media_id)
      .eq("media_type", row.media_type)
      .eq("source", INTERACTION_SOURCE);
    if (retryUpdErr) throw new Error(upsertErr.message);
  }
}

export function canonicalizeTag(s: string): string {
  return s
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .replace(/_{2,}/g, "_");
}

// (Removed bulk insert helper used by the old Continue button)

// Upsert a single interaction on each rating click.
// Note: For true idempotence, ensure a unique constraint exists on (user_id, media_id, media_type) or a matching materialized column for the context-based source.
export async function upsertUserInteraction(item: {
  media_id: number | string
  title: string
  vibes?: string[]
  rating: RatingValue
}) {
  const { data: auth } = await supabase.auth.getUser();
  const user = auth?.user;
  if (!user) throw new Error("Not signed in");

  const mediaId = Number(item.media_id);
  if (!Number.isFinite(mediaId)) throw new Error("Invalid media_id");

  const weight = EVENT_WEIGHT[item.rating];
  const context: Json = {
    tags: (item.vibes ?? []).map(canonicalizeTag),
  };
  const row: UserInteractionInsert = {
    user_id: user.id,
    media_id: mediaId,
    media_type: "movie",
    event_type: item.rating,
    weight,
    context_json: context,
    occurred_at: new Date().toISOString(),
    source: INTERACTION_SOURCE,
    title: item.title,
  };

  await upsertInteractionRow(row);
}

// ---------- Streaming providers (user_subscriptions) ----------

export async function getActiveSubscriptionIds(): Promise<number[]> {
  const { data: auth } = await supabase.auth.getUser();
  const user = auth?.user;
  if (!user) throw new Error("Not signed in");

  const { data, error } = await supabase
    .from("user_subscriptions")
    .select("provider_id, active")
    .eq("user_id", user.id);
  if (error) throw new Error(error.message);

  return (data ?? [])
    .filter((r) => r.active === true)
    .map((r) => Number(r.provider_id))
    .filter((n) => Number.isFinite(n));
}

export async function upsertUserSubscriptions(providerIds: number[]): Promise<void> {
  const { data: auth } = await supabase.auth.getUser();
  const user = auth?.user;
  if (!user) throw new Error("Not signed in");

  const { data: existing, error: existingErr } = await supabase
    .from("user_subscriptions")
    .select("provider_id, active")
    .eq("user_id", user.id);
  if (existingErr) throw new Error(existingErr.message);

  const now = new Date().toISOString();
  const selected = new Set<number>(providerIds.map((n) => Number(n)));

  // Split into two operations to keep types precise and avoid `any` casts.
  const toActivate: TablesInsert<"user_subscriptions">[] = Array.from(selected).map((pid) => ({
    user_id: user.id,
    provider_id: pid,
    active: true,
    updated_at: now,
  }));

  const toDeactivate: number[] = (existing ?? [])
    .filter((r) => r.active === true && !selected.has(Number(r.provider_id)))
    .map((r) => Number(r.provider_id));

  if (toActivate.length > 0) {
    const { error } = await supabase
      .from("user_subscriptions")
      .upsert(toActivate, { onConflict: "user_id, provider_id" });
    if (error) throw new Error(error.message);
  }

  if (toDeactivate.length > 0) {
    const { error } = await supabase
      .from("user_subscriptions")
      .update({ active: false, updated_at: now })
      .eq("user_id", user.id)
      .in("provider_id", toDeactivate);
    if (error) throw new Error(error.message);
  }
}

// ---------- User settings: provider filter mode ----------
export type ProviderFilterMode = "ALL" | "SELECTED";

export async function setProviderFilterMode(mode: ProviderFilterMode): Promise<void> {
  const { data: auth } = await supabase.auth.getUser();
  const user = auth?.user;
  if (!user) throw new Error("Not signed in");

  const payload: TablesInsert<"user_settings"> = {
    user_id: user.id,
    provider_filter_mode: mode,
  };

  const { error } = await supabase
    .from("user_settings")
    .upsert(payload, { onConflict: "user_id" });
  if (error) throw new Error(error.message);
}
