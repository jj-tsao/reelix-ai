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
  Action: ["Fast-Paced", "High-Stakes", "Action-Packed", "Espionage"],
  Adventure: ["Epic Scale", "Whimsical", "Visually-Stunning", "Grand Journey"],
  Comedy: ["Quirky", "Satirical", "Feel-Good", "Light-Hearted"],
  Crime: ["Gritty", "Plot-Twisty", "Slow-burn", "Neo-Noir"],
  Drama: ["Character-Driven", "Emotional", "Social Commentary", "Coming-of-Age"],
  Fantasy: ["Dreamlike", "Magical", "Mythic", "High Fantasy"],
  Horror: ["Supernatural", "Slasher", "Body Horror", "Twisted"],
  Romance: ["Heartwarming", "Romantic Comedy", "Tragic Love", "Bittersweet"],
  "Science Fiction": [
    "Mind-Bending",
    "Dystopian",
    "Thought-Provoking",
    "Cyberpunk",
  ],
  Thriller: ["Psychological", "Suspenseful", "Intense", "Dark"],
};