"""Built-in survey templates (original wording)."""

SURVEY_TEMPLATES = {
    "course_feedback": {
        "title": "Course feedback",
        "description": "Quick feedback on the course you just finished.",
        "questions": [
            {"id": "q1", "type": "rating", "text": "How useful was this course for you?"},
            {"id": "q2", "type": "rating", "text": "How clear were the lessons?"},
            {
                "id": "q3",
                "type": "choice",
                "text": "What was the pace like?",
                "options": ["Too slow", "Just right", "Too fast"],
            },
            {"id": "q4", "type": "text", "text": "What should we improve?"},
        ],
    },
    "wellbeing": {
        "title": "Weekly check-in",
        "description": "A 1-minute check on how you're doing. Answers are anonymous.",
        "questions": [
            {"id": "q1", "type": "rating", "text": "How confident do you feel about your studies this week?"},
            {
                "id": "q2",
                "type": "choice",
                "text": "How is your study load?",
                "options": ["Light", "Manageable", "Heavy", "Overwhelming"],
            },
            {"id": "q3", "type": "text", "text": "Anything your teachers should know?"},
        ],
    },
    "ai_readiness": {
        "title": "AI readiness",
        "description": "Where are you with AI tools today?",
        "questions": [
            {
                "id": "q1",
                "type": "choice",
                "text": "How often do you use AI tools?",
                "options": ["Never", "Monthly", "Weekly", "Daily"],
            },
            {
                "id": "q2",
                "type": "rating",
                "text": "How comfortable are you checking AI answers for mistakes?",
            },
            {
                "id": "q3",
                "type": "nps",
                "text": "How likely are you to recommend learning AI to a friend? (0-10)",
            },
            {"id": "q4", "type": "text", "text": "What would you most like to learn?"},
        ],
    },
}
