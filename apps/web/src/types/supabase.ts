export type Json =
  | string
  | number
  | boolean
  | null
  | { [key: string]: Json | undefined }
  | Json[]

export type Database = {
  // Allows to automatically instantiate createClient with right options
  // instead of createClient<Database, { PostgrestVersion: 'XX' }>(URL, KEY)
  __InternalSupabase: {
    PostgrestVersion: "12.2.3 (519615d)"
  }
  public: {
    Tables: {
      app_user: {
        Row: {
          created_at: string | null
          display_name: string | null
          email: string
          locale: string | null
          tz: string | null
          updated_at: string | null
          user_id: string
        }
        Insert: {
          created_at?: string | null
          display_name?: string | null
          email: string
          locale?: string | null
          tz?: string | null
          updated_at?: string | null
          user_id: string
        }
        Update: {
          created_at?: string | null
          display_name?: string | null
          email?: string
          locale?: string | null
          tz?: string | null
          updated_at?: string | null
          user_id?: string
        }
        Relationships: []
      }
      query_logs: {
        Row: {
          created_at: string
          device_type: string | null
          genres: string[] | null
          intent: string | null
          media_type: string | null
          platform: string | null
          providers: string[] | null
          query_id: string
          question: string | null
          session_id: string | null
          user_agent: string | null
          year_end: number | null
          year_start: number | null
        }
        Insert: {
          created_at?: string
          device_type?: string | null
          genres?: string[] | null
          intent?: string | null
          media_type?: string | null
          platform?: string | null
          providers?: string[] | null
          query_id: string
          question?: string | null
          session_id?: string | null
          user_agent?: string | null
          year_end?: number | null
          year_start?: number | null
        }
        Update: {
          created_at?: string
          device_type?: string | null
          genres?: string[] | null
          intent?: string | null
          media_type?: string | null
          platform?: string | null
          providers?: string[] | null
          query_id?: string
          question?: string | null
          session_id?: string | null
          user_agent?: string | null
          year_end?: number | null
          year_start?: number | null
        }
        Relationships: []
      }
      result_logs: {
        Row: {
          created_at: string
          dense_score: number | null
          is_final_rec: boolean | null
          media_id: number
          media_type: string | null
          query_id: string
          rank: number | null
          reranked_score: number | null
          sparse_score: number | null
          title: string | null
          why_summary: string | null
        }
        Insert: {
          created_at?: string
          dense_score?: number | null
          is_final_rec?: boolean | null
          media_id: number
          media_type?: string | null
          query_id: string
          rank?: number | null
          reranked_score?: number | null
          sparse_score?: number | null
          title?: string | null
          why_summary?: string | null
        }
        Update: {
          created_at?: string
          dense_score?: number | null
          is_final_rec?: boolean | null
          media_id?: number
          media_type?: string | null
          query_id?: string
          rank?: number | null
          reranked_score?: number | null
          sparse_score?: number | null
          title?: string | null
          why_summary?: string | null
        }
        Relationships: []
      }
      user_agent_state: {
        Row: {
          backlog_json: Json | null
          last_alert_scan: string | null
          last_profile_build: string | null
          notes: string | null
          updated_at: string | null
          user_id: string
        }
        Insert: {
          backlog_json?: Json | null
          last_alert_scan?: string | null
          last_profile_build?: string | null
          notes?: string | null
          updated_at?: string | null
          user_id: string
        }
        Update: {
          backlog_json?: Json | null
          last_alert_scan?: string | null
          last_profile_build?: string | null
          notes?: string | null
          updated_at?: string | null
          user_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "user_agent_state_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: true
            referencedRelation: "app_user"
            referencedColumns: ["user_id"]
          },
        ]
      }
      user_alert_rules: {
        Row: {
          created_at: string | null
          is_active: boolean | null
          lead_days: number | null
          providers_filter: string[] | null
          rule_id: number
          target_ref: string | null
          target_type: string
          trigger_type: string
          user_id: string
        }
        Insert: {
          created_at?: string | null
          is_active?: boolean | null
          lead_days?: number | null
          providers_filter?: string[] | null
          rule_id?: number
          target_ref?: string | null
          target_type: string
          trigger_type: string
          user_id: string
        }
        Update: {
          created_at?: string | null
          is_active?: boolean | null
          lead_days?: number | null
          providers_filter?: string[] | null
          rule_id?: number
          target_ref?: string | null
          target_type?: string
          trigger_type?: string
          user_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "user_alert_rules_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "app_user"
            referencedColumns: ["user_id"]
          },
        ]
      }
      user_follows: {
        Row: {
          created_at: string | null
          follow_id: number
          is_deleted: boolean | null
          target_ref: string
          target_type: string
          user_id: string
        }
        Insert: {
          created_at?: string | null
          follow_id?: number
          is_deleted?: boolean | null
          target_ref: string
          target_type: string
          user_id: string
        }
        Update: {
          created_at?: string | null
          follow_id?: number
          is_deleted?: boolean | null
          target_ref?: string
          target_type?: string
          user_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "user_follows_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "app_user"
            referencedColumns: ["user_id"]
          },
        ]
      }
      user_interactions: {
        Row: {
          context_json: Json | null
          event_type: string
          interaction_id: number
          media_id: number
          media_type: string
          occurred_at: string | null
          source: string
          user_id: string
          weight: number | null
        }
        Insert: {
          context_json?: Json | null
          event_type: string
          interaction_id?: number
          media_id: number
          media_type: string
          occurred_at?: string | null
          source?: string
          user_id: string
          weight?: number | null
        }
        Update: {
          context_json?: Json | null
          event_type?: string
          interaction_id?: number
          media_id?: number
          media_type?: string
          occurred_at?: string | null
          source?: string
          user_id?: string
          weight?: number | null
        }
        Relationships: [
          {
            foreignKeyName: "user_interactions_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "app_user"
            referencedColumns: ["user_id"]
          },
        ]
      }
      user_notifications: {
        Row: {
          digest_frequency: string
          email_enabled: boolean | null
          push_enabled: boolean | null
          quiet_hours: unknown | null
          updated_at: string | null
          user_id: string
        }
        Insert: {
          digest_frequency?: string
          email_enabled?: boolean | null
          push_enabled?: boolean | null
          quiet_hours?: unknown | null
          updated_at?: string | null
          user_id: string
        }
        Update: {
          digest_frequency?: string
          email_enabled?: boolean | null
          push_enabled?: boolean | null
          quiet_hours?: unknown | null
          updated_at?: string | null
          user_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "user_notifications_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: true
            referencedRelation: "app_user"
            referencedColumns: ["user_id"]
          },
        ]
      }
      user_preferences: {
        Row: {
          diversity_level: number | null
          genres_exclude: string[] | null
          genres_include: string[] | null
          include_movies: boolean | null
          include_tv: boolean | null
          keywords_exclude: string[] | null
          keywords_include: string[] | null
          languages: string[] | null
          maturity_ratings: string[] | null
          prefer_recency: boolean | null
          runtime_max: number | null
          runtime_min: number | null
          updated_at: string | null
          user_id: string
          year_max: number | null
          year_min: number | null
        }
        Insert: {
          diversity_level?: number | null
          genres_exclude?: string[] | null
          genres_include?: string[] | null
          include_movies?: boolean | null
          include_tv?: boolean | null
          keywords_exclude?: string[] | null
          keywords_include?: string[] | null
          languages?: string[] | null
          maturity_ratings?: string[] | null
          prefer_recency?: boolean | null
          runtime_max?: number | null
          runtime_min?: number | null
          updated_at?: string | null
          user_id: string
          year_max?: number | null
          year_min?: number | null
        }
        Update: {
          diversity_level?: number | null
          genres_exclude?: string[] | null
          genres_include?: string[] | null
          include_movies?: boolean | null
          include_tv?: boolean | null
          keywords_exclude?: string[] | null
          keywords_include?: string[] | null
          languages?: string[] | null
          maturity_ratings?: string[] | null
          prefer_recency?: boolean | null
          runtime_max?: number | null
          runtime_min?: number | null
          updated_at?: string | null
          user_id?: string
          year_max?: number | null
          year_min?: number | null
        }
        Relationships: [
          {
            foreignKeyName: "user_preferences_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: true
            referencedRelation: "app_user"
            referencedColumns: ["user_id"]
          },
        ]
      }
      user_settings: {
        Row: {
          autoplay_trailers: boolean | null
          default_sort_order: string | null
          language_ui: string | null
          onboarding_completed: boolean | null
          provider_filter_mode: string
          updated_at: string | null
          user_id: string
        }
        Insert: {
          autoplay_trailers?: boolean | null
          default_sort_order?: string | null
          language_ui?: string | null
          onboarding_completed?: boolean | null
          provider_filter_mode?: string
          updated_at?: string | null
          user_id: string
        }
        Update: {
          autoplay_trailers?: boolean | null
          default_sort_order?: string | null
          language_ui?: string | null
          onboarding_completed?: boolean | null
          provider_filter_mode?: string
          updated_at?: string | null
          user_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "user_settings_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: true
            referencedRelation: "app_user"
            referencedColumns: ["user_id"]
          },
        ]
      }
      user_subscriptions: {
        Row: {
          active: boolean | null
          provider_id: number
          updated_at: string | null
          user_id: string
        }
        Insert: {
          active?: boolean | null
          provider_id: number
          updated_at?: string | null
          user_id: string
        }
        Update: {
          active?: boolean | null
          provider_id?: number
          updated_at?: string | null
          user_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "user_subscriptions_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "app_user"
            referencedColumns: ["user_id"]
          },
        ]
      }
    }
    Views: {
      user_follows_active: {
        Row: {
          created_at: string | null
          follow_id: number | null
          is_deleted: boolean | null
          target_ref: string | null
          target_type: string | null
          user_id: string | null
        }
        Insert: {
          created_at?: string | null
          follow_id?: number | null
          is_deleted?: boolean | null
          target_ref?: string | null
          target_type?: string | null
          user_id?: string | null
        }
        Update: {
          created_at?: string | null
          follow_id?: number | null
          is_deleted?: boolean | null
          target_ref?: string | null
          target_type?: string | null
          user_id?: string | null
        }
        Relationships: [
          {
            foreignKeyName: "user_follows_user_id_fkey"
            columns: ["user_id"]
            isOneToOne: false
            referencedRelation: "app_user"
            referencedColumns: ["user_id"]
          },
        ]
      }
    }
    Functions: {
      citext: {
        Args: { "": boolean } | { "": string } | { "": unknown }
        Returns: string
      }
      citext_hash: {
        Args: { "": string }
        Returns: number
      }
      citextin: {
        Args: { "": unknown }
        Returns: string
      }
      citextout: {
        Args: { "": string }
        Returns: unknown
      }
      citextrecv: {
        Args: { "": unknown }
        Returns: string
      }
      citextsend: {
        Args: { "": string }
        Returns: string
      }
      is_me: {
        Args: { uid: string }
        Returns: boolean
      }
    }
    Enums: {
      [_ in never]: never
    }
    CompositeTypes: {
      [_ in never]: never
    }
  }
}

type DatabaseWithoutInternals = Omit<Database, "__InternalSupabase">

type DefaultSchema = DatabaseWithoutInternals[Extract<keyof Database, "public">]

export type Tables<
  DefaultSchemaTableNameOrOptions extends
    | keyof (DefaultSchema["Tables"] & DefaultSchema["Views"])
    | { schema: keyof DatabaseWithoutInternals },
  TableName extends DefaultSchemaTableNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof (DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"] &
        DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Views"])
    : never = never,
> = DefaultSchemaTableNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? (DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"] &
      DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Views"])[TableName] extends {
      Row: infer R
    }
    ? R
    : never
  : DefaultSchemaTableNameOrOptions extends keyof (DefaultSchema["Tables"] &
        DefaultSchema["Views"])
    ? (DefaultSchema["Tables"] &
        DefaultSchema["Views"])[DefaultSchemaTableNameOrOptions] extends {
        Row: infer R
      }
      ? R
      : never
    : never

export type TablesInsert<
  DefaultSchemaTableNameOrOptions extends
    | keyof DefaultSchema["Tables"]
    | { schema: keyof DatabaseWithoutInternals },
  TableName extends DefaultSchemaTableNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"]
    : never = never,
> = DefaultSchemaTableNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"][TableName] extends {
      Insert: infer I
    }
    ? I
    : never
  : DefaultSchemaTableNameOrOptions extends keyof DefaultSchema["Tables"]
    ? DefaultSchema["Tables"][DefaultSchemaTableNameOrOptions] extends {
        Insert: infer I
      }
      ? I
      : never
    : never

export type TablesUpdate<
  DefaultSchemaTableNameOrOptions extends
    | keyof DefaultSchema["Tables"]
    | { schema: keyof DatabaseWithoutInternals },
  TableName extends DefaultSchemaTableNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"]
    : never = never,
> = DefaultSchemaTableNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"][TableName] extends {
      Update: infer U
    }
    ? U
    : never
  : DefaultSchemaTableNameOrOptions extends keyof DefaultSchema["Tables"]
    ? DefaultSchema["Tables"][DefaultSchemaTableNameOrOptions] extends {
        Update: infer U
      }
      ? U
      : never
    : never

export type Enums<
  DefaultSchemaEnumNameOrOptions extends
    | keyof DefaultSchema["Enums"]
    | { schema: keyof DatabaseWithoutInternals },
  EnumName extends DefaultSchemaEnumNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[DefaultSchemaEnumNameOrOptions["schema"]]["Enums"]
    : never = never,
> = DefaultSchemaEnumNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? DatabaseWithoutInternals[DefaultSchemaEnumNameOrOptions["schema"]]["Enums"][EnumName]
  : DefaultSchemaEnumNameOrOptions extends keyof DefaultSchema["Enums"]
    ? DefaultSchema["Enums"][DefaultSchemaEnumNameOrOptions]
    : never

export type CompositeTypes<
  PublicCompositeTypeNameOrOptions extends
    | keyof DefaultSchema["CompositeTypes"]
    | { schema: keyof DatabaseWithoutInternals },
  CompositeTypeName extends PublicCompositeTypeNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[PublicCompositeTypeNameOrOptions["schema"]]["CompositeTypes"]
    : never = never,
> = PublicCompositeTypeNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? DatabaseWithoutInternals[PublicCompositeTypeNameOrOptions["schema"]]["CompositeTypes"][CompositeTypeName]
  : PublicCompositeTypeNameOrOptions extends keyof DefaultSchema["CompositeTypes"]
    ? DefaultSchema["CompositeTypes"][PublicCompositeTypeNameOrOptions]
    : never

export const Constants = {
  public: {
    Enums: {},
  },
} as const
