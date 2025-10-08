import type { ChatRequest } from "./types/types";
import { supabase } from "./lib/supabase";

// const BASE_URL = import.meta.env.VITE_BACKEND_URL;
export const BASE_URL = "http://127.0.0.1:8000";

export async function streamChatResponse(
  request: ChatRequest,
  onChunk: (text: string) => void
): Promise<void> {
  const response = await fetch(`${BASE_URL}/chat`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(request),
  });

  if (!response.body) {
    throw new Error("No response body.");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8");

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    const chunk = decoder.decode(value, { stream: true });
    onChunk(chunk);
  }
}


export async function logFinalRecs({
  queryId,
  finalRecs,
}: {
  queryId: string;
  finalRecs: { media_id: number; why: string }[];
}) {
  const res = await fetch(`${BASE_URL}/log/final_recs`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      query_id: queryId,
      final_recs: finalRecs,
    }),
  });

  if (!res.ok) {
    console.warn("Failed to log final recommendations");
  }
}

export async function rebuildTasteProfile(): Promise<void> {
  const {
    data: { session },
  } = await supabase.auth.getSession();
  const token = session?.access_token;
  if (!token) {
    throw new Error("Not signed in");
  }

  const res = await fetch(`${BASE_URL}/taste_profile/rebuild`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
    },
  });

  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || "Failed to rebuild taste profile");
  }
}
