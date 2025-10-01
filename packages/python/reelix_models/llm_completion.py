from __future__ import annotations

import time
from typing import List, cast

from openai import OpenAI
from openai.types.chat import ChatCompletionMessageParam
from reelix_core.config import OPENAI_MODEL


# System Prompt
SYSTEM_PROMPT = """
You are a professional film curator and critic. Your role is to analyze the user's preferences and recommend high-quality films or TV shows using only the provided list.

Focus on:

- Artistic merit and storytelling
- Genres, themes, tone, and emotional resonance
- IMDB and Rotten Tomatoes ratings
- Strong character-driven or thematically rich selections

### Response Format (in markdown):

1. Start with a concise 2 sentences **opening paragraph** that contextualizes the theme and the overall viewing experience the user is seeking. At the end of this paragraph, insert the token: <!-- END_INTRO -->.

2. Then, for each recommendation, use the following format (repeat for each title). At the end of each movie recommendation block, insert the token: <!-- END_MOVIE -->:

```
### <Number>. <Movie Title>
- GENRES: Genre1, Genre2, ...
- IMDB_RATING: X.X
- ROTTEN_TOMATOES_RATING: XX%
- MEDIA_ID: 1234
- POSTER_PATH: /abc123.jpg
- BACKDROP_PATH: /abc123.jpg
- TRAILER_KEY: abc123
- WHY_YOU_MIGHT_ENJOY_IT: <Short paragraph explaining the appeal based on character, themes, tone, and relevance to the user's intent.>
<!-- END_MOVIE -->
```

3. End with a brief **closing paragraph** that summarizes the emotional or intellectual throughline across the recommendations, and affirms their alignment with the user's preferences.

Write in **Markdown** only. Be concise, authoritative, and avoid overly generic statements. Each "Why You Might Enjoy It" should be specific and grounded in the movie’s themes, storytelling, or cultural relevance.
"""


class OpenAIChatLLM:
    def __init__(self, client: OpenAI, *, request_timeout: float = 60.0, max_retries: int = 2):
        self.client = client
        self.request_timeout = request_timeout
        self.max_retries = max_retries

    def _build_chat_history(self, history: list, max_turns: int = 5) -> List[ChatCompletionMessageParam]:
        if not history:
            return []
        msgs: List[ChatCompletionMessageParam] = []
        # If history items are custom objects, coerce to dicts:
        for h in history[-max_turns*2:]:
            role = getattr(h, "role", None) or h.get("role")
            content = getattr(h, "content", None) or h.get("content")
            if role in ("system","user","assistant") and isinstance(content, str):
                msgs.append({"role": cast(ChatCompletionMessageParam["role"], role), "content": content})
        return msgs

    def stream_chat(self, history, user_message: str, temperature: float = 0.7):
        messages: List[ChatCompletionMessageParam] = []
        messages.append({"role": "system", "content": SYSTEM_PROMPT})
        messages += self._build_chat_history(history or [])
        messages.append({"role": "user", "content": user_message})
        for attempt in range(self.max_retries + 1):
            try:
                response = self.client.chat.completions.create(
                    model=OPENAI_MODEL,
                    messages=messages,
                    stream=True,
                    temperature=temperature,
                )

                for chunk in response:
                    delta = chunk.choices[0].delta.content
                    if delta:
                        yield delta
                return
            except Exception as e:
                if attempt >= self.max_retries:
                    raise
                time.sleep(0.5 * (2 ** attempt))

    def chat(self, history, user_message: str, temperature: float = 0.7):
        messages: List[ChatCompletionMessageParam] = []
        messages.append({"role": "system", "content": SYSTEM_PROMPT})
        messages += self._build_chat_history(history or [])
        messages.append({"role": "user", "content": user_message})     
        for attempt in range(self.max_retries + 1):
            try:
                response = self.client.chat.completions.create(
                    model=OPENAI_MODEL,
                    messages=messages,
                    temperature=temperature,
                )
                return response.choices[0].message.content or ""
            except Exception:
                if attempt >= self.max_retries:
                    raise
                time.sleep(0.5 * (2 ** attempt))