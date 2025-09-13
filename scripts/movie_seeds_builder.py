from reelix_core.config import (
    QDRANT_API_KEY,
    QDRANT_ENDPOINT,
    QDRANT_MOVIE_COLLECTION_NAME,
)
from reelix_retrieval.filter_builder import build_qfilter
from reelix_retrieval.vectorstore import connect_qdrant

SEED_MOVIES = {
  "Action": [
    { "title": "Mad Max: Fury Road", "year": 2015, "vibes": ["Fast-paced", "Action-packed", "High-stakes"] },
    { "title": "John Wick", "year": 2014, "vibes": ["Fast-paced", "Action-packed"] },
    { "title": "Mission: Impossible - Fallout", "year": 2018, "vibes": ["Espionage", "High-stakes", "Fast-paced"] },
    { "title": "Skyfall", "year": 2012, "vibes": ["Espionage", "High-stakes"] },
    { "title": "The Raid: Redemption", "year": 2011, "vibes": ["Fast-paced", "Action-packed"] },
    { "title": "Die Hard", "year": 1988, "vibes": ["High-stakes", "Action-packed"] },
    { "title": "Hard Boiled", "year": 1992, "vibes": ["Action-packed", "Fast-paced"] },
    { "title": "The Bourne Ultimatum", "year": 2007, "vibes": ["Espionage", "Fast-paced"] },
    { "title": "Edge of Tomorrow", "year": 2014, "vibes": ["Fast-paced", "Action-packed"] },
    { "title": "The Dark Knight", "year": 2008, "vibes": ["High-stakes", "Action-packed"] }
  ],
  "Adventure": [
    { "title": "Raiders of the Lost Ark", "year": 1981, "vibes": ["Epic scale", "Grand journey"] },
    { "title": "The Lord of the Rings: The Fellowship of the Ring", "year": 2001, "vibes": ["Epic scale", "Grand journey", "Visually-stunning"] },
    { "title": "Spirited Away", "year": 2001, "vibes": ["Whimsical", "Visually-stunning"] },
    { "title": "Life of Pi", "year": 2012, "vibes": ["Visually-stunning", "Grand journey"] },
    { "title": "Up", "year": 2009, "vibes": ["Whimsical", "Grand journey"] },
    { "title": "The Princess Bride", "year": 1987, "vibes": ["Whimsical"] },
    { "title": "The Adventures of Tintin", "year": 2011, "vibes": ["Grand journey", "Visually-stunning"] },
    { "title": "The Revenant", "year": 2015, "vibes": ["Grand journey", "Epic scale"] },
    { "title": "The Secret Life of Walter Mitty", "year": 2013, "vibes": ["Whimsical", "Grand journey"] },
    { "title": "Moana", "year": 2016, "vibes": ["Grand journey", "Visually-stunning"] }
  ],
  "Comedy": [
    { "title": "The Grand Budapest Hotel", "year": 2014, "vibes": ["Quirky"] },
    { "title": "Dr. Strangelove", "year": 1964, "vibes": ["Satirical"] },
    { "title": "Monty Python and the Holy Grail", "year": 1975, "vibes": ["Quirky", "Satirical"] },
    { "title": "Superbad", "year": 2007, "vibes": ["Light-hearted", "Feel-good"] },
    { "title": "Bridesmaids", "year": 2011, "vibes": ["Feel-good", "Light-hearted"] },
    { "title": "Jojo Rabbit", "year": 2019, "vibes": ["Satirical", "Quirky"] },
    { "title": "Anchorman: The Legend of Ron Burgundy", "year": 2004, "vibes": ["Light-hearted"] },
    { "title": "Hot Fuzz", "year": 2007, "vibes": ["Quirky", "Satirical"] },
    { "title": "Paddington 2", "year": 2017, "vibes": ["Feel-good", "Light-hearted"] },
    { "title": "Groundhog Day", "year": 1993, "vibes": ["Feel-good", "Light-hearted"] }
  ],
  "Crime": [
    { "title": "Heat", "year": 1995, "vibes": ["Gritty"] },
    { "title": "Se7en", "year": 1995, "vibes": ["Neo-Noir", "Plot-twisty"] },
    { "title": "The Departed", "year": 2006, "vibes": ["Plot-twisty"] },
    { "title": "Chinatown", "year": 1974, "vibes": ["Slow-burn", "Neo-Noir"] },
    { "title": "City of God", "year": 2002, "vibes": ["Gritty"] },
    { "title": "Memories of Murder", "year": 2003, "vibes": ["Slow-burn", "Gritty"] },
    { "title": "Oldboy", "year": 2003, "vibes": ["Neo-Noir", "Plot-twisty"] },
    { "title": "The Godfather", "year": 1972, "vibes": ["Slow-burn"] },
    { "title": "Prisoners", "year": 2013, "vibes": ["Gritty", "Plot-twisty"] },
    { "title": "The French Connection", "year": 1971, "vibes": ["Gritty"] }
  ],
  "Drama": [
    { "title": "Moonlight", "year": 2016, "vibes": ["Character-driven", "Emotional"] },
    { "title": "Parasite", "year": 2019, "vibes": ["Social commentary", "Character-driven"] },
    { "title": "There Will Be Blood", "year": 2007, "vibes": ["Character-driven", "Historical"] },
    { "title": "12 Years a Slave", "year": 2013, "vibes": ["Historical", "Emotional"] },
    { "title": "Manchester by the Sea", "year": 2016, "vibes": ["Emotional", "Character-driven"] },
    { "title": "Nomadland", "year": 2021, "vibes": ["Social commentary", "Emotional"] },
    { "title": "The Social Network", "year": 2010, "vibes": ["Social commentary"] },
    { "title": "A Separation", "year": 2011, "vibes": ["Emotional", "Character-driven"] },
    { "title": "The King's Speech", "year": 2010, "vibes": ["Historical", "Emotional"] },
    { "title": "Whiplash", "year": 2014, "vibes": ["Character-driven", "Emotional"] }
  ],
  "Fantasy": [
    { "title": "Pan's Labyrinth", "year": 2006, "vibes": ["Dreamlike", "Mythic", "Magical"] },
    { "title": "The Lord of the Rings: The Two Towers", "year": 2002, "vibes": ["High fantasy", "Mythic"] },
    { "title": "The Green Knight", "year": 2021, "vibes": ["Mythic", "Dreamlike"] },
    { "title": "Harry Potter and the Prisoner of Azkaban", "year": 2004, "vibes": ["Magical"] },
    { "title": "Howl's Moving Castle", "year": 2004, "vibes": ["Dreamlike", "Magical"] },
    { "title": "The Shape of Water", "year": 2017, "vibes": ["Dreamlike", "Magical"] },
    { "title": "Stardust", "year": 2007, "vibes": ["Magical", "High fantasy"] },
    { "title": "Willow", "year": 1988, "vibes": ["High fantasy"] },
    { "title": "Big Fish", "year": 2003, "vibes": ["Dreamlike", "Magical"] },
    { "title": "Legend", "year": 1985, "vibes": ["High fantasy", "Mythic"] }
  ],
  "Horror": [
    { "title": "The Exorcist", "year": 1973, "vibes": ["Supernatural"] },
    { "title": "The Thing", "year": 1982, "vibes": ["Body horror"] },
    { "title": "Halloween", "year": 1978, "vibes": ["Slasher"] },
    { "title": "Hereditary", "year": 2018, "vibes": ["Supernatural", "Twisted"] },
    { "title": "Get Out", "year": 2017, "vibes": ["Twisted"] },
    { "title": "A Nightmare on Elm Street", "year": 1984, "vibes": ["Supernatural", "Slasher"] },
    { "title": "The Babadook", "year": 2014, "vibes": ["Supernatural"] },
    { "title": "It Follows", "year": 2015, "vibes": ["Supernatural"] },
    { "title": "Audition", "year": 2000, "vibes": ["Twisted", "Body horror"] },
    { "title": "The Texas Chain Saw Massacre", "year": 1974, "vibes": ["Slasher", "Body horror"] }
  ],
  "Romance": [
    { "title": "When Harry Met Sally...", "year": 1989, "vibes": ["Romantic comedy"] },
    { "title": "Pride & Prejudice", "year": 2005, "vibes": ["Heartwarming"] },
    { "title": "The Big Sick", "year": 2017, "vibes": ["Romantic comedy", "Heartwarming"] },
    { "title": "Before Sunrise", "year": 1995, "vibes": ["Bittersweet"] },
    { "title": "Call Me by Your Name", "year": 2017, "vibes": ["Bittersweet"] },
    { "title": "Eternal Sunshine of the Spotless Mind", "year": 2004, "vibes": ["Bittersweet"] },
    { "title": "Titanic", "year": 1997, "vibes": ["Tragic love"] },
    { "title": "La La Land", "year": 2016, "vibes": ["Bittersweet"] },
    { "title": "The Notebook", "year": 2004, "vibes": ["Tragic love", "Heartwarming"] },
    { "title": "Notting Hill", "year": 1999, "vibes": ["Romantic comedy", "Heartwarming"] }
  ],
  "Science Fiction": [
    { "title": "Inception", "year": 2010, "vibes": ["Mind-bending"] },
    { "title": "The Matrix", "year": 1999, "vibes": ["Cyberpunk", "Mind-bending"] },
    { "title": "Blade Runner 2049", "year": 2017, "vibes": ["Cyberpunk", "Thought-provoking"] },
    { "title": "Arrival", "year": 2016, "vibes": ["Thought-provoking"] },
    { "title": "Ex Machina", "year": 2015, "vibes": ["Thought-provoking"] },
    { "title": "Children of Men", "year": 2006, "vibes": ["Dystopian", "Thought-provoking"] },
    { "title": "Annihilation", "year": 2018, "vibes": ["Mind-bending", "Thought-provoking"] },
    { "title": "Gattaca", "year": 1997, "vibes": ["Dystopian", "Thought-provoking"] },
    { "title": "Snowpiercer", "year": 2013, "vibes": ["Dystopian"] },
    { "title": "Ghost in the Shell", "year": 1995, "vibes": ["Cyberpunk", "Thought-provoking"] }
  ],
  "Thriller": [
    { "title": "The Silence of the Lambs", "year": 1991, "vibes": ["Psychological", "Dark"] },
    { "title": "Shutter Island", "year": 2010, "vibes": ["Psychological", "Suspenseful"] },
    { "title": "Gone Girl", "year": 2014, "vibes": ["Psychological", "Suspenseful"] },
    { "title": "No Country for Old Men", "year": 2007, "vibes": ["Intense", "Dark"] },
    { "title": "Nightcrawler", "year": 2014, "vibes": ["Dark", "Psychological"] },
    { "title": "The Wages of Fear", "year": 1953, "vibes": ["Suspenseful", "Intense"] },
    { "title": "Sicario", "year": 2015, "vibes": ["Intense", "Suspenseful"] },
    { "title": "The Prestige", "year": 2006, "vibes": ["Psychological", "Dark"] },
    { "title": "Buried", "year": 2010, "vibes": ["Intense", "Suspenseful"] },
    { "title": "The Girl with the Dragon Tattoo", "year": 2011, "vibes": ["Suspenseful", "Dark"] }
  ]
}

qdrant_client = connect_qdrant(QDRANT_API_KEY, QDRANT_ENDPOINT)


def query_qdrant (filter):
    point, _ = qdrant_client.scroll(
        collection_name=QDRANT_MOVIE_COLLECTION_NAME,
        scroll_filter=filter,
        limit=1,
        with_payload=True,
        with_vectors=False,
    )
    return point


for genre, medias in SEED_MOVIES.items():
    for m in medias:
        filter = build_qfilter(titles=[m['title']], release_year=m['year'])
        print (m['title'])
        point = query_qdrant(filter)
        if point:
            m['poster_url']

SEED_MOVIES['Action']
filter = build_qfilter(titles=["A Separation"])

point, _ = qdrant_client.scroll(
    collection_name=QDRANT_MOVIE_COLLECTION_NAME,
    scroll_filter=filter,
    limit=1,
    with_payload=True,
    with_vectors=False,
)
point

