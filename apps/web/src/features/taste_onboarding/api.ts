import { supabase } from "@/lib/supabase";
import type { TablesInsert, TablesUpdate } from "@/types/supabase";

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
