import type { MascotCharacter } from "@/mascot/companions";
export type { MascotCharacter };
/** "system" follows the device's prefers-color-scheme (light or dark). */
export type ThemeName = "light" | "dark" | "kolam" | "temple" | "ocean" | "night_study" | "system";

export interface Preferences {
  version: number;
  mascot: {
    character: MascotCharacter;
    name: string;
    color: string;
    outfit: string;
    accessories: string[];
    enabled: boolean;
    position: "bottom-right" | "bottom-left" | "docked";
    voice: boolean;
    chattiness: number;
  };
  mentor: {
    personality: "anna_akka" | "strict_teacher" | "funny_buddy" | "calm_guru";
    depth: "simple" | "detailed";
    reply_language: "auto" | "en" | "ta" | "tanglish";
    example_style: "cricket" | "cinema" | "farming" | "coding" | "daily_life";
  };
  appearance: {
    theme: ThemeName;
    accent: string;
    font: "mukta" | "noto" | "catamaran" | "dyslexic";
    font_scale: number;
    reduced_motion: boolean;
    sound_effects: boolean;
    study_music: boolean;
  };
  learning: {
    daily_goal_minutes: number;
    pace: "relaxed" | "steady" | "intense";
    difficulty: "auto" | "easy" | "medium" | "hard";
    reminder_times: string[];
    study_days: number[];
    dashboard_widgets: string[];
    adaptive: boolean;
    lesson_language: string;
    progress_pins: string[];
    tours_done: string[];
    /** Course page layout; older accounts may not have it yet (the page defaults to "map"). */
    course_view?: "map" | "path";
  };
  /** Workshop and Ask Aasan voice: tap-to-talk (default) or hands-free. Older accounts may not have them yet. */
  voice?: { workshop_mode?: "tap" | "handsfree"; mentor_mode?: "tap" | "handsfree"; mentor_read_aloud?: boolean; mentor_lang?: "" | "en" | "ta" };
  notifications: {
    email_study: boolean;
    email_plan: boolean;
    email_workshops?: boolean;
    kili_nudges: boolean;
    email_winback?: boolean;
    push_study?: boolean;
    push_streak?: boolean;
    push_reviews?: boolean;
    push_workshops?: boolean;
    push_teacher?: boolean;
    push_plan?: boolean;
  };
}

export type DeepPartial<T> = { [K in keyof T]?: T[K] extends object ? (T[K] extends unknown[] ? T[K] : DeepPartial<T[K]>) : T[K] };

export interface Profile {
  display_name: string;
  language: import("@/i18n/languages").UiLang;
  domain: string;
  goals: string[];
  skills: string[];
  level: "beginner" | "intermediate" | "advanced";
  onboarding_completed: boolean;
  avatar: Record<string, unknown>;
}

export interface Me {
  id: number;
  email: string;
  email_verified: boolean;
  is_staff: boolean;
  /** Admin console roles (superadmin | support | finance | content); empty for everyone else. */
  staff_roles?: string[];
  is_creator: boolean;
  /** Creator, staff, or a school owner/admin/teacher — may use the Creator Lab. */
  can_author: boolean;
  has_password: boolean;
  profile: Profile;
  preferences: Preferences;
  consent: { required: boolean; version: string; age_band: "adult" | "minor" | null; guardian?: "pending" | "given" | "objected" | null };
  /** Platform switches set by the admin (lesson podcast, explainer video, Listen); all off by default. */
  features?: Features;
}

export interface Features { podcast: boolean; explainer: boolean; listen: boolean }

export interface AuthPayload {
  access: string;
  user: Me;
}
