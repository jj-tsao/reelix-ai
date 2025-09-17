export const ALL_GENRES = [
  "Action",
  "Adventure",
  "Comedy",
  "Crime",
  "Drama",
  "Fantasy",
  "Horror",
  "Romance",
  "Science Fiction",
  "Thriller",
] as const;

export type Genre = (typeof ALL_GENRES)[number];

export const VIBE_TAGS: Record<Genre, string[]> = {
  Action: ["Fast-paced", "High-stakes", "Action-packed", "Espionage"],
  Adventure: ["Epic scale", "Whimsical", "Visually-stunning", "Grand journey"],
  Comedy: ["Quirky", "Satirical", "Feel-good", "Light-hearted"],
  Crime: ["Gritty", "Plot-twisty", "Slow-burn", "Neo-Noir"],
  Drama: ["Character-driven", "Emotional", "Social commentary", "Historical"],
  Fantasy: ["Dreamlike", "Magical", "Mythic", "High fantasy"],
  Horror: ["Supernatural", "Slasher", "Body horror", "Twisted"],
  Romance: ["Heartwarming", "Romantic comedy", "Tragic love", "Bittersweet"],
  "Science Fiction": [
    "Mind-bending",
    "Dystopian",
    "Thought-provoking",
    "Cyberpunk",
  ],
  Thriller: ["Psychological", "Suspenseful", "Intense", "Dark"],
};