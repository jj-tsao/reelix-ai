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

export const SEED_MOVIES = {
  Action: [
    {
      title: "Mad Max: Fury Road",
      year: 2015,
      vibes: ["Fast-paced", "Action-packed", "High-stakes"],
      poster_url:
        "https://image.tmdb.org/t/p/w500/hA2ple9q4qnwxp3hKVNhroipsir.jpg",
      media_id: 76341,
    },
    {
      title: "John Wick",
      year: 2014,
      vibes: ["Fast-paced", "Action-packed"],
      poster_url:
        "https://image.tmdb.org/t/p/w500/fZPSd91yGE9fCcCe6OoQr6E3Bev.jpg",
      media_id: 245891,
    },
    {
      title: "Mission: Impossible - Fallout",
      year: 2018,
      vibes: ["Espionage", "High-stakes", "Fast-paced"],
      poster_url:
        "https://image.tmdb.org/t/p/w500/AkJQpZp9WoNdj7pLYSj1L0RcMMN.jpg",
      media_id: 353081,
    },
    {
      title: "Skyfall",
      year: 2012,
      vibes: ["Espionage", "High-stakes"],
      poster_url:
        "https://image.tmdb.org/t/p/w500/d0IVecFQvsGdSbnMAHqiYsNYaJT.jpg",
      media_id: 37724,
    },
    {
      title: "Crouching Tiger, Hidden Dragon",
      year: 2000,
      vibes: ["Epic scale", "Martial arts"],
      poster_url:
        "https://image.tmdb.org/t/p/w500/iNDVBFNz4XyYzM9Lwip6atSTFqf.jpg",
      media_id: 146,
    },
    {
      title: "Die Hard",
      year: 1988,
      vibes: ["High-stakes", "Action-packed"],
      poster_url:
        "https://image.tmdb.org/t/p/w500/aJCpHDC6RoGz7d1Fzayl019xnxX.jpg",
      media_id: 562,
    },
    {
      title: "Gladiator",
      year: 2000,
      vibes: ["Epic scale", "Grand journey"],
      poster_url:
        "https://image.tmdb.org/t/p/w500/ty8TGRuvJLPUmAR1H1nRIsgwvim.jpg",
      media_id: 98,
    },
    {
      title: "The Bourne Ultimatum",
      year: 2007,
      vibes: ["Espionage", "Fast-paced"],
      poster_url:
        "https://image.tmdb.org/t/p/w500/15rMz5MRXFp7CP4VxhjYw4y0FUn.jpg",
      media_id: 2503,
    },
    {
      title: "Edge of Tomorrow",
      year: 2014,
      vibes: ["Fast-paced", "Action-packed"],
      poster_url:
        "https://image.tmdb.org/t/p/w500/nBM9MMa2WCwvMG4IJ3eiGUdbPe6.jpg",
      media_id: 137113,
    },
    {
      title: "The Dark Knight",
      year: 2008,
      vibes: ["High-stakes", "Action-packed"],
      poster_url:
        "https://image.tmdb.org/t/p/w500/qJ2tW6WMUDux911r6m7haRef0WH.jpg",
      media_id: 155,
    },
  ],
  Adventure: [
    {
      title: "Raiders of the Lost Ark",
      year: 1981,
      vibes: ["Epic scale", "Grand journey"],
      poster_url:
        "https://image.tmdb.org/t/p/w500/ceG9VzoRAVGwivFU403Wc3AHRys.jpg",
      media_id: 85,
    },
    {
      title: "The Lord of the Rings: The Fellowship of the Ring",
      year: 2001,
      vibes: ["Epic scale", "Grand journey", "Visually-stunning"],
      poster_url:
        "https://image.tmdb.org/t/p/w500/6oom5QYQ2yQTMJIbnvbkBL9cHo6.jpg",
      media_id: 120,
    },
    {
      title: "Spirited Away",
      year: 2001,
      vibes: ["Whimsical", "Visually-stunning"],
      poster_url:
        "https://image.tmdb.org/t/p/w500/39wmItIWsg5sZMyRUHLkWBcuVCM.jpg",
      media_id: 129,
    },
    {
      title: "Life of Pi",
      year: 2012,
      vibes: ["Visually-stunning", "Grand journey"],
      poster_url:
        "https://image.tmdb.org/t/p/w500/iLgRu4hhSr6V1uManX6ukDriiSc.jpg",
      media_id: 87827,
    },
    {
      title: "Up",
      year: 2009,
      vibes: ["Whimsical", "Grand journey"],
      poster_url:
        "https://image.tmdb.org/t/p/w500/mFvoEwSfLqbcWwFsDjQebn9bzFe.jpg",
      media_id: 14160,
    },
    {
      title: "Everything Everywhere All at Once",
      year: 2022,
      vibes: ["Adventure epic", "Quirky"],
      poster_url:
        "https://image.tmdb.org/t/p/w500/u68AjlvlutfEIcpmbYpKcdi09ut.jpg",
      media_id: 545611,
    },
    {
      title: "Avengers: Endgame",
      year: 2019,
      vibes: ["Epic scale", "Visually-stunning"],
      poster_url:
        "https://image.tmdb.org/t/p/w500/ulzhLuWrPK07P1YkdWQLZnQh1JL.jpg",
      media_id: 299534,
    },
    {
      title: "The Revenant",
      year: 2015,
      vibes: ["Grand journey", "Epic scale"],
      poster_url:
        "https://image.tmdb.org/t/p/w500/ji3ecJphATlVgWNY0B0RVXZizdf.jpg",
      media_id: 281957,
    },
    {
      title: "The Secret Life of Walter Mitty",
      year: 2013,
      vibes: ["Whimsical", "Grand journey"],
      poster_url:
        "https://image.tmdb.org/t/p/w500/tY6ypjKOOtujhxiSwTmvA4OZ5IE.jpg",
      media_id: 116745,
    },
    {
      title: "Moana",
      year: 2016,
      vibes: ["Grand journey", "Visually-stunning"],
      poster_url:
        "https://image.tmdb.org/t/p/w500/9tzN8sPbyod2dsa0lwuvrwBDWra.jpg",
      media_id: 277834,
    },
  ],
  Comedy: [
    {
      title: "The Grand Budapest Hotel",
      year: 2014,
      vibes: ["Quirky", "Melancholy"],
      poster_url:
        "https://image.tmdb.org/t/p/w500/eWdyYQreja6JGCzqHWXpWHDrrPo.jpg",
      media_id: 120467,
    },
    {
      title: "Green Book",
      year: 2018,
      vibes: ["Feel-good", "Period drama"],
      poster_url:
        "https://image.tmdb.org/t/p/w500/7BsvSuDQuoqhWmU2fL7W2GOcZHU.jpg",
      media_id: 490132,
    },
    {
      title: "Monty Python and the Holy Grail",
      year: 1975,
      vibes: ["Quirky", "Satirical"],
      poster_url:
        "https://image.tmdb.org/t/p/w500/hWx1ANiWEWWyzKPN0us35HCGnhQ.jpg",
      media_id: 762,
    },
    {
      title: "Superbad",
      year: 2007,
      vibes: ["Light-hearted", "Feel-good"],
      poster_url:
        "https://image.tmdb.org/t/p/w500/ek8e8txUyUwd2BNqj6lFEerJfbq.jpg",
      media_id: 8363,
    },
    {
      title: "Bridesmaids",
      year: 2011,
      vibes: ["Feel-good", "Light-hearted"],
      poster_url:
        "https://image.tmdb.org/t/p/w500/gJtA7hYsBMQ7EM3sPBMUdBfU7a0.jpg",
      media_id: 55721,
    },
    {
      title: "Jojo Rabbit",
      year: 2019,
      vibes: ["Satirical", "Quirky"],
      poster_url:
        "https://image.tmdb.org/t/p/w500/1mqL7VG4Ix8wmxwypmCA1HTHBky.jpg",
      media_id: 515001,
    },
    {
      title: "Anchorman: The Legend of Ron Burgundy",
      year: 2004,
      vibes: ["Light-hearted"],
      poster_url:
        "https://image.tmdb.org/t/p/w500/mhZIcRePT7U8viFQVjt1ZjYIsR4.jpg",
      media_id: 8699,
    },
    {
      title: "Hot Fuzz",
      year: 2007,
      vibes: ["Quirky", "Satirical"],
      poster_url:
        "https://image.tmdb.org/t/p/w500/zPib4ukTSdXvHP9pxGkFCe34f3y.jpg",
      media_id: 4638,
    },
    {
      title: "Paddington 2",
      year: 2017,
      vibes: ["Feel-good", "Light-hearted"],
      poster_url:
        "https://image.tmdb.org/t/p/w500/1OJ9vkD5xPt3skC6KguyXAgagRZ.jpg",
      media_id: 346648,
    },
    {
      title: "Groundhog Day",
      year: 1993,
      vibes: ["Feel-good", "Light-hearted"],
      poster_url:
        "https://image.tmdb.org/t/p/w500/gCgt1WARPZaXnq523ySQEUKinCs.jpg",
      media_id: 137,
    },
  ],
  Crime: [
    {
      title: "Heat",
      year: 1995,
      vibes: ["Gritty"],
      poster_url:
        "https://image.tmdb.org/t/p/w500/umSVjVdbVwtx5ryCA2QXL44Durm.jpg",
      media_id: 949,
    },
    {
      title: "Se7en",
      year: 1995,
      vibes: ["Neo-Noir", "Plot-twisty"],
      poster_url:
        "https://image.tmdb.org/t/p/w500/191nKfP0ehp3uIvWqgPbFmI4lv9.jpg",
      media_id: 807,
    },
    {
      title: "The Departed",
      year: 2006,
      vibes: ["Plot-twisty"],
      poster_url:
        "https://image.tmdb.org/t/p/w500/nT97ifVT2J1yMQmeq20Qblg61T.jpg",
      media_id: 1422,
    },
    {
      title: "Chinatown",
      year: 1974,
      vibes: ["Slow-burn", "Neo-Noir"],
      poster_url:
        "https://image.tmdb.org/t/p/w500/kZRSP3FmOcq0xnBulqpUQngJUXY.jpg",
      media_id: 829,
    },
    {
      title: "City of God",
      year: 2002,
      vibes: ["Gritty"],
      poster_url:
        "https://image.tmdb.org/t/p/w500/k7eYdWvhYQyRQoU2TB2A2Xu2TfD.jpg",
      media_id: 598,
    },
    {
      title: "Memories of Murder",
      year: 2003,
      vibes: ["Slow-burn", "Gritty"],
      poster_url:
        "https://image.tmdb.org/t/p/w500/jcgUjx1QcupGzjntTVlnQ15lHqy.jpg",
      media_id: 11423,
    },
    {
      title: "Oldboy",
      year: 2003,
      vibes: ["Neo-Noir", "Plot-twisty"],
      poster_url:
        "https://image.tmdb.org/t/p/w500/pWDtjs568ZfOTMbURQBYuT4Qxka.jpg",
      media_id: 670,
    },
    {
      title: "The Gentlemen",
      year: 2020,
      vibes: ["Fast-paced", "Dark comedy"],
      poster_url:
        "https://image.tmdb.org/t/p/w500/jtrhTYB7xSrJxR1vusu99nvnZ1g.jpg",
      media_id: 522627,
    },
    {
      title: "The Godfather",
      year: 1972,
      vibes: ["Slow-burn"],
      poster_url:
        "https://image.tmdb.org/t/p/w500/3bhkrj58Vtu7enYsRolD1fZdja1.jpg",
      media_id: 238,
    },
    {
      title: "Prisoners",
      year: 2013,
      vibes: ["Gritty", "Plot-twisty"],
      poster_url:
        "https://image.tmdb.org/t/p/w500/jsS3a3ep2KyBVmmiwaz3LvK49b1.jpg",
      media_id: 146233,
    },
    {
      title: "Pulp Fiction",
      year: 1994,
      vibes: ["Satirical", "Non-linear narrative"],
      poster_url:
        "https://image.tmdb.org/t/p/w500/vQWk5YBFWF4bZaofAbv0tShwBvQ.jpg",
      media_id: 680,
    },
  ],
  Drama: [
    {
      title: "Moonlight",
      year: 2016,
      vibes: ["Character-driven", "Emotional"],
      poster_url:
        "https://image.tmdb.org/t/p/w500/rcICfiL9fvwRjoWHxW8QeroLYrJ.jpg",
      media_id: 376867,
    },
    {
      title: "Parasite",
      year: 2019,
      vibes: ["Social commentary", "Character-driven"],
      poster_url:
        "https://image.tmdb.org/t/p/w500/7IiTTgloJzvGI1TAYymCfbfl3vT.jpg",
      media_id: 496243,
    },
    {
      title: "There Will Be Blood",
      year: 2007,
      vibes: ["Character-driven", "Historical"],
      poster_url:
        "https://image.tmdb.org/t/p/w500/fa0RDkAlCec0STeMNAhPaF89q6U.jpg",
      media_id: 7345,
    },
    {
      title: "12 Years a Slave",
      year: 2013,
      vibes: ["Historical", "Emotional"],
      poster_url:
        "https://image.tmdb.org/t/p/w500/xdANQijuNrJaw1HA61rDccME4Tm.jpg",
      media_id: 76203,
    },
    {
      title: "Manchester by the Sea",
      year: 2016,
      vibes: ["Emotional", "Character-driven"],
      poster_url:
        "https://image.tmdb.org/t/p/w500/o9VXYOuaJxCEKOxbA86xqtwmqYn.jpg",
      media_id: 334541,
    },
    {
      title: "Nomadland",
      year: 2021,
      vibes: ["Social commentary", "Emotional"],
      poster_url:
        "https://image.tmdb.org/t/p/w500/8Vc5EOUEIF1EUXuX9eLFf7BvN3P.jpg",
      media_id: 581734,
    },
    {
      title: "The Social Network",
      year: 2010,
      vibes: ["Social commentary"],
      poster_url:
        "https://image.tmdb.org/t/p/w500/n0ybibhJtQ5icDqTp8eRytcIHJx.jpg",
      media_id: 37799,
    },
    {
      title: "Ford v Ferrari",
      year: 2019,
      vibes: ["Docudrama", "Period drama"],
      poster_url:
        "https://image.tmdb.org/t/p/w500/dR1Ju50iudrOh3YgfwkAU1g2HZe.jpg",
      media_id: 359724,
    },
    {
      title: "The King's Speech",
      year: 2010,
      vibes: ["Historical", "Emotional"],
      poster_url:
        "https://image.tmdb.org/t/p/w500/pVNKXVQFukBaCz6ML7GH3kiPlQP.jpg",
      media_id: 45269,
    },
    {
      title: "Whiplash",
      year: 2014,
      vibes: ["Character-driven", "Emotional"],
      poster_url:
        "https://image.tmdb.org/t/p/w500/7fn624j5lj3xTme2SgiLCeuedmO.jpg",
      media_id: 244786,
    },
  ],
  Fantasy: [
    {
      title: "Pan's Labyrinth",
      year: 2006,
      vibes: ["Dreamlike", "Mythic", "Magical"],
      poster_url:
        "https://image.tmdb.org/t/p/w500/s8C4whhKtDaJvMDcyiMvx3BIF5F.jpg",
      media_id: 1417,
    },
    {
      title: "The Lord of the Rings: The Two Towers",
      year: 2002,
      vibes: ["High fantasy", "Mythic"],
      poster_url:
        "https://image.tmdb.org/t/p/w500/5VTN0pR8gcqV3EPUHHfMGnJYN9L.jpg",
      media_id: 121,
    },
    {
      title: "KPop Demon Hunters",
      year: 2025,
      vibes: ["Supernatural", "Musical"],
      poster_url:
        "https://image.tmdb.org/t/p/w500/22AouvwlhlXbe3nrFcjzL24bvWH.jpg",
      media_id: 803796,
    },
    {
      title: "Harry Potter and the Prisoner of Azkaban",
      year: 2004,
      vibes: ["Magical"],
      poster_url:
        "https://image.tmdb.org/t/p/w500/aWxwnYoe8p2d2fcxOqtvAtJ72Rw.jpg",
      media_id: 673,
    },
    {
      title: "Howl's Moving Castle",
      year: 2004,
      vibes: ["Dreamlike", "Magical"],
      poster_url:
        "https://image.tmdb.org/t/p/w500/TkTPELv4kC3u1lkloush8skOjE.jpg",
      media_id: 4935,
    },
    {
      title: "The Shape of Water",
      year: 2017,
      vibes: ["Dreamlike", "Magical"],
      poster_url:
        "https://image.tmdb.org/t/p/w500/9zfwPffUXpBrEP26yp0q1ckXDcj.jpg",
      media_id: 399055,
    },
    {
      title: "Stardust",
      year: 2007,
      vibes: ["Magical", "High fantasy"],
      poster_url:
        "https://image.tmdb.org/t/p/w500/7zbFmxy3DqKYL2M8Hop6uylp2Uy.jpg",
      media_id: 2270,
    },
    {
      title: "The Curious Case of Benjamin Button",
      year: 2008,
      vibes: ["Whimsical", "Melancholy"],
      poster_url:
        "https://image.tmdb.org/t/p/w500/26wEWZYt6yJkwRVkjcbwJEFh9IS.jpg",
      media_id: 4922,
    },
    {
      title: "Big Fish",
      year: 2003,
      vibes: ["Dreamlike", "Magical"],
      poster_url:
        "https://image.tmdb.org/t/p/w500/tjK063yCgaBAluVU72rZ6PKPH2l.jpg",
      media_id: 587,
    },
    {
      title: "Legend",
      year: 1985,
      vibes: ["High fantasy", "Mythic"],
      poster_url:
        "https://image.tmdb.org/t/p/w500/6n3PQSYpZRK5YPk2w8JEwED7AZk.jpg",
      media_id: 11976,
    },
  ],
  Horror: [
    {
      title: "The Exorcist",
      year: 1973,
      vibes: ["Supernatural"],
      poster_url:
        "https://image.tmdb.org/t/p/w500/5x0CeVHJI8tcDx8tUUwYHQSNILq.jpg",
      media_id: 9552,
    },
    {
      title: "The Thing",
      year: 1982,
      vibes: ["Body horror"],
      poster_url:
        "https://image.tmdb.org/t/p/w500/tzGY49kseSE9QAKk47uuDGwnSCu.jpg",
      media_id: 1091,
    },
    {
      title: "Halloween",
      year: 1978,
      vibes: ["Slasher"],
      poster_url:
        "https://image.tmdb.org/t/p/w500/wijlZ3HaYMvlDTPqJoTCWKFkCPU.jpg",
      media_id: 948,
    },
    {
      title: "Hereditary",
      year: 2018,
      vibes: ["Supernatural", "Twisted"],
      poster_url:
        "https://image.tmdb.org/t/p/w500/4GFPuL14eXi66V96xBWY73Y9PfR.jpg",
      media_id: 493922,
    },
    {
      title: "Get Out",
      year: 2017,
      vibes: ["Twisted"],
      poster_url:
        "https://image.tmdb.org/t/p/w500/tFXcEccSQMf3lfhfXKSU9iRBpa3.jpg",
      media_id: 419430,
    },
    {
      title: "A Nightmare on Elm Street",
      year: 1984,
      vibes: ["Supernatural", "Slasher"],
      poster_url:
        "https://image.tmdb.org/t/p/w500/wGTpGGRMZmyFCcrY2YoxVTIBlli.jpg",
      media_id: 377,
    },
    {
      title: "The Babadook",
      year: 2014,
      vibes: ["Supernatural"],
      poster_url:
        "https://image.tmdb.org/t/p/w500/qt3fqapeo94TfvMyld8P7gkpXLz.jpg",
      media_id: 242224,
    },
    {
      title: "It Follows",
      year: 2015,
      vibes: ["Supernatural"],
      poster_url:
        "https://image.tmdb.org/t/p/w500/iwnQ1JH1wdWrGYkgWySptJ5284A.jpg",
      media_id: 270303,
    },
    {
      title: "Audition",
      year: 2000,
      vibes: ["Twisted", "Body horror"],
      poster_url:
        "https://image.tmdb.org/t/p/w500/zwGaUMm0wAqi0wkO7LJDlwoA5LP.jpg",
      media_id: 11075,
    },
    {
      title: "The Texas Chain Saw Massacre",
      year: 1974,
      vibes: ["Slasher", "Body horror"],
      poster_url:
        "https://image.tmdb.org/t/p/w500/mpgkRPH1GNkMCgdPk2OMyHzAks7.jpg",
      media_id: 30497,
    },
  ],
  Romance: [
    {
      title: "When Harry Met Sally...",
      year: 1989,
      vibes: ["Romantic comedy"],
      poster_url:
        "https://image.tmdb.org/t/p/w500/rFOiFUhTMtDetqCGClC9PIgnC1P.jpg",
      media_id: 639,
    },
    {
      title: "Pride & Prejudice",
      year: 2005,
      vibes: ["Heartwarming", "Period drama"],
      poster_url:
        "https://image.tmdb.org/t/p/w500/jnsoq5q98DQaE8yw6WZH0F9dW5G.jpg",
      media_id: 4348,
    },
    {
      title: "The Big Sick",
      year: 2017,
      vibes: ["Romantic comedy", "Heartwarming"],
      poster_url:
        "https://image.tmdb.org/t/p/w500/9fJTT8pBxxQsFILJHTtHhdYFr77.jpg",
      media_id: 416477,
    },
    {
      title: "Before Sunrise",
      year: 1995,
      vibes: ["Bittersweet"],
      poster_url:
        "https://image.tmdb.org/t/p/w500/kf1Jb1c2JAOqjuzA3H4oDM263uB.jpg",
      media_id: 76,
    },
    {
      title: "Call Me by Your Name",
      year: 2017,
      vibes: ["Bittersweet"],
      poster_url:
        "https://image.tmdb.org/t/p/w500/gXiE0WveDnT0n5J4sW9TMxXF4oT.jpg",
      media_id: 398818,
    },
    {
      title: "Eternal Sunshine of the Spotless Mind",
      year: 2004,
      vibes: ["Bittersweet"],
      poster_url:
        "https://image.tmdb.org/t/p/w500/5MwkWH9tYHv3mV9OdYTMR5qreIz.jpg",
      media_id: 38,
    },
    {
      title: "Titanic",
      year: 1997,
      vibes: ["Tragic love"],
      poster_url:
        "https://image.tmdb.org/t/p/w500/9xjZS2rlVxm8SFx8kPC3aIGCOYQ.jpg",
      media_id: 597,
    },
    {
      title: "La La Land",
      year: 2016,
      vibes: ["Bittersweet", "Visually-stunning"],
      poster_url:
        "https://image.tmdb.org/t/p/w500/uDO8zWDhfWwoFdKS4fzkUJt0Rf0.jpg",
      media_id: 313369,
    },
    {
      title: "The Notebook",
      year: 2004,
      vibes: ["Tragic love", "Heartwarming"],
      poster_url:
        "https://image.tmdb.org/t/p/w500/rNzQyW4f8B8cQeg7Dgj3n6eT5k9.jpg",
      media_id: 11036,
    },
    {
      title: "Midnight in Paris",
      year: 2011,
      vibes: ["Nostalgic", "Metaphorical", "Romantic comedy"],
      poster_url:
        "https://image.tmdb.org/t/p/w500/4wBG5kbfagTQclETblPRRGihk0I.jpg",
      media_id: 59436,
    },
    {
      title: "Notting Hill",
      year: 1999,
      vibes: ["Romantic comedy", "Heartwarming"],
      poster_url:
        "https://image.tmdb.org/t/p/w500/hHRIf2XHeQMbyRb3HUx19SF5Ujw.jpg",
      media_id: 509,
    },
  ],
  "Science Fiction": [
    {
      title: "Inception",
      year: 2010,
      vibes: ["Mind-bending", "Cerebral", "Psychological"],
      poster_url:
        "https://image.tmdb.org/t/p/w500/ljsZTbVsrQSqZgWeep2B1QiDKuh.jpg",
      media_id: 27205,
    },
    {
      title: "The Matrix",
      year: 1999,
      vibes: ["Cyberpunk", "Mind-bending"],
      poster_url:
        "https://image.tmdb.org/t/p/w500/p96dm7sCMn4VYAStA6siNz30G1r.jpg",
      media_id: 603,
    },
    {
      title: "Blade Runner 2049",
      year: 2017,
      vibes: ["Cyberpunk", "Thought-provoking", "Dystopian"],
      poster_url:
        "https://image.tmdb.org/t/p/w500/gajva2L0rPYkEWjzgFlBXCAVBE5.jpg",
      media_id: 335984,
    },
    {
      title: "Arrival",
      year: 2016,
      vibes: ["Thought-provoking"],
      poster_url:
        "https://image.tmdb.org/t/p/w500/x2FJsf1ElAgr63Y3PNPtJrcmpoe.jpg",
      media_id: 329865,
    },
    {
      title: "Ex Machina",
      year: 2015,
      vibes: ["Thought-provoking"],
      poster_url:
        "https://image.tmdb.org/t/p/w500/dmJW8IAKHKxFNiUnoDR7JfsK7Rp.jpg",
      media_id: 264660,
    },
    {
      title: "Children of Men",
      year: 2006,
      vibes: ["Dystopian", "Thought-provoking"],
      poster_url:
        "https://image.tmdb.org/t/p/w500/8Xgvmx7WWc7Z9Ws9RAYk7uya2kh.jpg",
      media_id: 9693,
    },
    {
      title: "Annihilation",
      year: 2018,
      vibes: ["Mind-bending", "Thought-provoking"],
      poster_url:
        "https://image.tmdb.org/t/p/w500/4YRplSk6BhH6PRuE9gfyw9byUJ6.jpg",
      media_id: 300668,
    },
    {
      title: "Gattaca",
      year: 1997,
      vibes: ["Dystopian", "Thought-provoking"],
      poster_url:
        "https://image.tmdb.org/t/p/w500/eSKr5Fl1MEC7zpAXaLWBWSBjgJq.jpg",
      media_id: 782,
    },
    {
      title: "Snowpiercer",
      year: 2013,
      vibes: ["Dystopian"],
      poster_url:
        "https://image.tmdb.org/t/p/w500/nzccOvhrLGI0nvAknCEAk8bchD9.jpg",
      media_id: 110415,
    },
    {
      title: "Ghost in the Shell",
      year: 1995,
      vibes: ["Cyberpunk", "Thought-provoking"],
      poster_url:
        "https://image.tmdb.org/t/p/w500/9gC88zYUBARRSThcG93MvW14sqx.jpg",
      media_id: 9323,
    },
  ],
  Thriller: [
    {
      title: "The Silence of the Lambs",
      year: 1991,
      vibes: ["Psychological", "Dark"],
      poster_url:
        "https://image.tmdb.org/t/p/w500/uS9m8OBk1A8eM9I042bx8XXpqAq.jpg",
      media_id: 274,
    },
    {
      title: "Shutter Island",
      year: 2010,
      vibes: ["Psychological", "Suspenseful"],
      poster_url:
        "https://image.tmdb.org/t/p/w500/nrmXQ0zcZUL8jFLrakWc90IR8z9.jpg",
      media_id: 11324,
    },
    {
      title: "Gone Girl",
      year: 2014,
      vibes: ["Psychological", "Suspenseful"],
      poster_url:
        "https://image.tmdb.org/t/p/w500/ts996lKsxvjkO2yiYG0ht4qAicO.jpg",
      media_id: 210577,
    },
    {
      title: "No Country for Old Men",
      year: 2007,
      vibes: ["Intense", "Dark"],
      poster_url:
        "https://image.tmdb.org/t/p/w500/6d5XOczc226jECq0LIX0siKtgHR.jpg",
      media_id: 6977,
    },
    {
      title: "Nightcrawler",
      year: 2014,
      vibes: ["Dark", "Psychological"],
      poster_url:
        "https://image.tmdb.org/t/p/w500/j9HrX8f7GbZQm1BrBiR40uFQZSb.jpg",
      media_id: 242582,
    },
    {
      title: "Donnie Darko",
      year: 2001,
      vibes: ["Mystery", "Psychological Thriller"],
      poster_url:
        "https://image.tmdb.org/t/p/w500/fhQoQfejY1hUcwyuLgpBrYs6uFt.jpg",
      media_id: 141,
    },
    {
      title: "Sicario",
      year: 2015,
      vibes: ["Intense", "Suspenseful"],
      poster_url:
        "https://image.tmdb.org/t/p/w500/lz8vNyXeidqqOdJW9ZjnDAMb5Vr.jpg",
      media_id: 273481,
    },
    {
      title: "The Prestige",
      year: 2006,
      vibes: ["Psychological", "Dark"],
      poster_url:
        "https://image.tmdb.org/t/p/w500/2ZOzyhoW08neG27DVySMCcq2emd.jpg",
      media_id: 1124,
    },
    {
      title: "Buried",
      year: 2010,
      vibes: ["Intense", "Suspenseful"],
      poster_url:
        "https://image.tmdb.org/t/p/w500/splPNB0vAoNlb8l5WYxz2E3FK2G.jpg",
      media_id: 26388,
    },
    {
      title: "The Girl with the Dragon Tattoo",
      year: 2011,
      vibes: ["Suspenseful", "Dark"],
      poster_url:
        "https://image.tmdb.org/t/p/w500/8bokS83zGdhaXgN9tjidUKmAftW.jpg",
      media_id: 65754,
    },
  ],
} as const;
