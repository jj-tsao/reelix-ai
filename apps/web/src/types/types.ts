export type DeviceInfo = {
  device_type: string;
  platform: string;
  user_agent: string;
};

export type ChatHistoryMessage = {
  role: "user" | "assistant" | "system";
  content: string;
};

export type InteractiveRequestPayload = {
  query_text: string;
  media_type: "movie" | "tv";
  history: ChatHistoryMessage[];
  query_filters: {
    genres: string[];
    providers: number[];
    year_range: [number, number];
  };
  session_id: string;
  query_id: string;
  device_info?: DeviceInfo;
};

export type FilterSettings = {
  media_type: "movie" | "tv";
  genres: string[];
  providers: string[];
  year_range: [number, number];
};
