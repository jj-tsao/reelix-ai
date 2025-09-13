import { useState } from "react";
import GenresStep from "../components/GenresStep";
import RateSeedMoviesStep from "../components/RateSeedMoviesStep";
import { useAuth } from "@/features/auth/hooks/useAuth";
import { upsertUserPreferences } from "../api";
import { useToast } from "@/components/ui/useToast";

export default function TasteOnboardingPage() {
  const { user, loading } = useAuth();
  const { toast } = useToast();
  const [submitting, setSubmitting] = useState(false);
  const [step, setStep] = useState<"genres" | "rate">("genres");
  const [selectedGenres, setSelectedGenres] = useState<string[]>([]);
  const [selectedVibes, setSelectedVibes] = useState<string[]>([]);

  async function handleGenresSubmit({
    genres,
    vibeTags,
  }: {
    genres: string[];
    vibeTags: string[];
  }) {
    if (!user) {
      toast({
        title: "Sign In",
        description: "Please sign in to build your taste profile.",
      });
      return;
    }
    try {
      setSubmitting(true);
      await upsertUserPreferences({
        user_id: user.id,
        genres_include: genres,
        keywords_include: vibeTags,
      });
      toast({
        title: "Saved",
        description:
          "Preferences updated. Next, we’ll ask you to rate a few titles.",
      });
      setSelectedGenres(genres);
      setSelectedVibes(vibeTags);
      setStep("rate");
    } catch (e: any) {
      toast({
        title: "Failed to save",
        description: e?.message ?? "Something went wrong",
      });
    } finally {
      setSubmitting(false);
    }
  }

  if (loading) return null;

  if (step === "genres") {
    return (
      <GenresStep
        onSubmit={handleGenresSubmit}
        submitting={submitting}
        initialGenres={selectedGenres}
        initialVibes={selectedVibes}
      />
    );
  }

  return (
    <RateSeedMoviesStep
      genres={selectedGenres}
      onBack={() => setStep("genres")}
      onFinish={(ratings) => {
        // TODO: submit ratings to backend in Screen 2 implementation step 2
        console.log("Collected ratings:", ratings);
      }}
    />
  );
}
