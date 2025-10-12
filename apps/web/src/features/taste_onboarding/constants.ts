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
  Action: ["Fast Paced", "High Stakes", "Espionage", "Revenge", "Heist", "Superhero", "One-Man Army", "Martial Arts"],
  Adventure: ["Epic Scale", "Grand Journey", "Exploration", "Visually Stunning", "Whimsical", "Swashbuckling", "Survival", "Treasure Hunt"],
  Comedy: ["Feel-Good", "Quirky", "Satirical", "Rom-Com", "Dark Comedy", "Mockumentary", "Raunchy", "Absurd"],
  Crime: ["Gritty", "Detective", "Neo-Noir", "Plot-Twisty", "Slow Burn", "Heist/Caper","Procedural",  "Mob/Mafia"],
  Drama: ["Character-Driven", "Coming-of-Age", "Nonlinear", "Period Piece", "Social Issue","True Story", "Family Saga", "Indie Drama"],
  Fantasy: ["High Fantasy", "Urban Fantasy", "Dark Fantasy", "Sword & Sorcery", "Magical Realism", "Mythic", "Dreamlike", "Fairy Tale"],
  Horror: ["Supernatural", "Slasher", "Body Horror", "Monster Horror", "Gore", "Psychological", "Folk Horror", "Cosmic Horror"],
  Romance: ["Heartwarming", "Rom-Com", "Tragic Love", "Bittersweet", "Enemies to Lovers", "Steamy", "Period Romance", "Slow Burn"],
  "Science Fiction": [
    "Mind-Bending",
    "Dystopian",
    "Time Travel",
    "Cyberpunk",
    "Space Opera",
    "Post-Apocalyptic",
    "AI / Robotics",
    "Hard Sci-Fi",
  ],
  Thriller: ["Psychological", "Suspenseful", "Twist Ending", "Mystery", "Neo-Noir", "Conspiracy", "Cat-and-Mouse", "Nonlinear"],
};