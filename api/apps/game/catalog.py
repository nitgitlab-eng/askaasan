"""Rewards, badges and wardrobe items. All art is original (drawn in Kili.tsx)."""

XP = {
    "activity_correct": 10,
    "activity_partial": 4,
    "lesson_complete": 50,
    "lesson_perfect_bonus": 25,
    "review_card": 5,
    "boss_win": 120,
    "daily_goal": 30,
}
COINS = {
    "lesson_complete": 10,
    "lesson_perfect_bonus": 10,
    "boss_win": 60,
    "daily_goal": 20,
    "badge": 25,
    "referral": 100,
}

STREAK_FREEZE_PRICE = 150
MAX_FREEZES = 2

# Streak repair: a broken streak (2+ days) can be restored for coins, or for free by finishing STREAK_REVIVE_GOAL
# lessons / Today circuits within STREAK_REVIVE_HOURS of coming back. The offer lasts STREAK_REPAIR_DAYS from the day
# the break was noticed.
STREAK_REPAIR_PRICE = 300
STREAK_REPAIR_DAYS = 7
STREAK_REVIVE_GOAL = 3
STREAK_REVIVE_HOURS = 72
STREAK_REVIVE_KINDS = ("lesson_complete", "today_complete")


def level_for(xp: int) -> int:
    """Gentle curve: level n needs 50·(n-1)² XP (L2=50, L3=200, L5=800, L10=4050)."""
    n = 1
    while 50 * n * n <= xp:
        n += 1
    return n


def xp_for_level(level: int) -> int:
    return 50 * (level - 1) ** 2


BADGES = {
    "first_lesson": {
        "icon": "🌱",
        "en": "First step",
        "ta": "முதல் அடி",
        "desc_en": "Finish your first lesson",
        "desc_ta": "முதல் பாடத்தை முடியுங்கள்",
    },
    "perfect_lesson": {
        "icon": "💯",
        "en": "Perfectionist",
        "ta": "முழுமை",
        "desc_en": "Score 100% on a lesson",
        "desc_ta": "ஒரு பாடத்தில் 100% பெறுங்கள்",
    },
    "streak_3": {
        "icon": "🔥",
        "en": "On fire",
        "ta": "தீப்பொறி",
        "desc_en": "3-day streak",
        "desc_ta": "3 நாள் தொடர்",
    },
    "streak_7": {
        "icon": "🏏",
        "en": "Full innings",
        "ta": "முழு இன்னிங்ஸ்",
        "desc_en": "7-day streak",
        "desc_ta": "7 நாள் தொடர்",
    },
    "streak_30": {
        "icon": "🏆",
        "en": "Champion",
        "ta": "சாம்பியன்",
        "desc_en": "30-day streak",
        "desc_ta": "30 நாள் தொடர்",
    },
    "reviewer": {
        "icon": "🧠",
        "en": "Memory master",
        "ta": "நினைவு மன்னன்",
        "desc_en": "Review 25 cards",
        "desc_ta": "25 அட்டைகளை மீள்பார்வை",
    },
    "boss_slayer": {
        "icon": "⚔️",
        "en": "Boss slayer",
        "ta": "வீரன்",
        "desc_en": "Win a section boss battle",
        "desc_ta": "ஒரு பிரிவுப் போரில் வெல்லுங்கள்",
    },
    "level_5": {
        "icon": "⭐",
        "en": "Rising star",
        "ta": "வளரும் நட்சத்திரம்",
        "desc_en": "Reach level 5",
        "desc_ta": "நிலை 5 அடையுங்கள்",
    },
    "course_complete": {
        "icon": "🎓",
        "en": "Graduate",
        "ta": "பட்டதாரி",
        "desc_en": "Finish every lesson in a course",
        "desc_ta": "ஒரு பாடநெறியை முழுமையாக முடியுங்கள்",
    },
    "roleplay_star": {
        "icon": "🎭",
        "en": "Natural talker",
        "ta": "இயல்பான பேச்சாளர்",
        "desc_en": "Score 80+ in a role-play",
        "desc_ta": "ஒரு ரோல்-ப்ளேயில் 80+ பெறுங்கள்",
    },
    "friend": {
        "icon": "🤝",
        "en": "Good friend",
        "ta": "நல்ல நண்பன்",
        "desc_en": "Invite a friend who joins",
        "desc_ta": "நண்பரை அழைத்துச் சேருங்கள்",
    },
}

# slot: outfit | accessory. Free items are owned by everyone.
ITEMS = {
    "uniform": {"slot": "outfit", "price": 0, "level": 1, "en": "School uniform", "ta": "பள்ளி சீருடை"},
    "veshti": {"slot": "outfit", "price": 120, "level": 1, "en": "Veshti", "ta": "வேஷ்டி"},
    "kurta": {"slot": "outfit", "price": 150, "level": 2, "en": "Festive kurta", "ta": "பண்டிகை குர்தா"},
    "lab_coat": {"slot": "outfit", "price": 250, "level": 4, "en": "Scientist coat", "ta": "விஞ்ஞானி கோட்"},
    "glasses": {"slot": "accessory", "price": 0, "level": 1, "en": "Glasses", "ta": "கண்ணாடி"},
    "cricket_cap": {
        "slot": "accessory",
        "price": 80,
        "level": 1,
        "en": "Cricket cap",
        "ta": "கிரிக்கெட் தொப்பி",
    },
    "jasmine": {"slot": "accessory", "price": 60, "level": 1, "en": "Jasmine", "ta": "மல்லிகை"},
    "headphones": {"slot": "accessory", "price": 140, "level": 2, "en": "Headphones", "ta": "ஹெட்ஃபோன்"},
    "grad_cap": {
        "slot": "accessory",
        "price": 200,
        "level": 3,
        "en": "Graduation cap",
        "ta": "பட்டமளிப்புத் தொப்பி",
    },
    "sunglasses": {"slot": "accessory", "price": 180, "level": 3, "en": "Sunglasses", "ta": "குளிர் கண்ணாடி"},
    "crown": {"slot": "accessory", "price": 500, "level": 6, "en": "Golden crown", "ta": "தங்க கிரீடம்"},
}
FREE_ITEMS = {k for k, v in ITEMS.items() if v["price"] == 0}

LEAGUES = [  # by XP earned this week
    (0, "bronze", "🥉"),
    (150, "silver", "🥈"),
    (400, "gold", "🥇"),
    (800, "diamond", "💎"),
]


def league_for(weekly_xp: int) -> dict:
    name, icon = LEAGUES[0][1], LEAGUES[0][2]
    for threshold, n, i in LEAGUES:
        if weekly_xp >= threshold:
            name, icon = n, i
    return {"name": name, "icon": icon}
