import { supabase } from "@/lib/supabase";
import type { Json, TablesInsert } from "@/types/supabase";

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

async function upsertInteractionRow(row: TablesInsert<"user_interactions">) {
  // Always migrate legacy rows to set the concrete source column
  const updatePayload = {
    event_type: row.event_type,
    weight: row.weight,
    context_json: row.context_json,
    occurred_at: row.occurred_at,
    source: INTERACTION_SOURCE,
  } satisfies Partial<TablesInsert<"user_interactions">>;

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

export async function insertTasteOnboardingInteractions(
  items: { media_id?: number | string; vibes?: string[]; rating: RatingValue }[]
) {
  const { data: auth } = await supabase.auth.getUser();
  const user = auth?.user;
  if (!user) throw new Error("Not signed in");

  // Build rows using new `media_id` column (formerly `tmdb_id`).
  // Cast to any for forward-compatibility while generated types catch up.
  const rows = items
    .map((it) => {
      const mediaId = Number(it.media_id);
      if (!Number.isFinite(mediaId)) return null;
      const weight = EVENT_WEIGHT[it.rating];
      const context: Json = {
        tags: (it.vibes ?? []).map(canonicalizeTag),
      };
      const row: TablesInsert<"user_interactions"> = {
        user_id: user.id,
        media_id: mediaId,
        media_type: "movie",
        event_type: it.rating,
        weight,
        context_json: context,
        occurred_at: new Date().toISOString(),
        source: INTERACTION_SOURCE,
      };
      return row;
    })
    .filter((row): row is TablesInsert<"user_interactions"> => Boolean(row));

  if (rows.length === 0) return;

  for (const row of rows) {
    await upsertInteractionRow(row);
  }
}

// Upsert a single interaction on each rating click.
// Note: For true idempotence, ensure a unique constraint exists on (user_id, media_id, media_type) or a matching materialized column for the context-based source.
export async function upsertUserInteraction(item: {
  media_id: number | string
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
  const row: TablesInsert<"user_interactions"> = {
    user_id: user.id,
    media_id: mediaId,
    media_type: "movie",
    event_type: item.rating,
    weight,
    context_json: context,
    occurred_at: new Date().toISOString(),
    source: INTERACTION_SOURCE,
  };

  await upsertInteractionRow(row);
}
