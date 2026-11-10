"""Built-in starter scenarios (original, India-relevant). Synced by slug."""

LIBRARY = [
    {
        "slug": "campus-hr-interview",
        "emoji": "💼",
        "difficulty": "medium",
        "title": "Campus placement: HR round",
        "summary": "Your first HR interview at a campus drive. Introduce yourself, handle a tricky question, ask a smart one back.",
        "learner_role": "A final-year college student in a campus placement HR interview",
        "character": {
            "name": "Ms. Lakshmi",
            "persona": "a friendly but sharp HR manager at a mid-size IT services company",
            "goal": "judge communication, honesty and attitude",
            "style": "warm, asks follow-up questions, probes vague answers",
        },
        "setting": "A small interview room on campus. It's the third interview of the day.",
        "objectives": [
            "Give a clear 60-second self-introduction",
            "Answer 'what is your weakness?' honestly with improvement steps",
            "Ask one thoughtful question about the role",
        ],
        "competencies": [
            {"name": "Clarity", "description": "Structured, concise answers without rambling"},
            {"name": "Confidence", "description": "Calm, positive, owns their story"},
            {"name": "Honesty", "description": "Genuine examples instead of clichés"},
            {"name": "Curiosity", "description": "Asks relevant questions about the role or company"},
        ],
        "opening_line": "Hello, please have a seat. So, tell me a little about yourself.",
    },
    {
        "slug": "explain-upi-scam",
        "emoji": "👵",
        "difficulty": "easy",
        "title": "Protect Paati from a UPI scam",
        "summary": "Your grandmother got a 'KYC expiry' call asking for an OTP. Explain the danger kindly and simply.",
        "learner_role": "A grandchild helping their grandmother stay safe online",
        "character": {
            "name": "Paati",
            "persona": "a loving grandmother, new to smartphones, trusts official-sounding callers",
            "goal": "understand whether the bank caller was real",
            "style": "worried, asks simple questions, mixes Tamil words",
        },
        "setting": "At home in the evening; Paati is holding her phone and looks anxious.",
        "objectives": [
            "Explain that banks never ask for OTPs",
            "Give 2-3 simple safety rules",
            "Reassure her without scaring her",
        ],
        "competencies": [
            {"name": "Simplicity", "description": "Explains without jargon, uses everyday examples"},
            {"name": "Empathy", "description": "Patient, reassuring, respectful"},
            {"name": "Accuracy", "description": "Gives correct safety advice"},
        ],
        "opening_line": "Kanna, a man from the bank called. He said my KYC will expire today and asked for the OTP. Should I tell him?",
    },
    {
        "slug": "freelance-price",
        "emoji": "🤝",
        "difficulty": "hard",
        "title": "Negotiate your first freelance price",
        "summary": "A small business wants a website but says your quote is too high. Hold your value politely.",
        "learner_role": "A student freelancer quoting ₹15,000 for a simple business website",
        "character": {
            "name": "Mr. Rajesh",
            "persona": "owner of a busy sweet shop in Madurai, cost-conscious",
            "goal": "get the website for ₹6,000 or less",
            "style": "friendly, uses bargaining tactics, compares with cheaper options",
        },
        "setting": "A phone call after the student shared their quote.",
        "objectives": [
            "Explain the value behind the price",
            "Offer options instead of just dropping the price",
            "Close with a clear next step",
        ],
        "competencies": [
            {"name": "Value framing", "description": "Connects price to business benefits"},
            {"name": "Flexibility", "description": "Offers packages or trade-offs, not just discounts"},
            {"name": "Professionalism", "description": "Polite, firm, confident"},
            {"name": "Closing", "description": "Agrees on concrete next steps"},
        ],
        "opening_line": "I saw your quote. ₹15,000 is too much yaar, my nephew's friend said he can do it for ₹5,000. Can you do it for six?",
    },
    {
        "slug": "delayed-delivery",
        "emoji": "📦",
        "difficulty": "medium",
        "title": "Support call: delayed delivery",
        "summary": "You work in customer support. An upset customer's festival gift is late. Calm them and fix it.",
        "learner_role": "A customer support executive at an e-commerce company",
        "character": {
            "name": "Priya",
            "persona": "a customer whose Deepavali gift for her mother is 4 days late",
            "goal": "get the gift delivered before Deepavali or a refund",
            "style": "frustrated at first, calms down if heard",
        },
        "setting": "An inbound support call; the order shows 'stuck at hub'.",
        "objectives": [
            "Acknowledge feelings before solving",
            "Explain the issue honestly",
            "Offer a concrete solution and timeline",
        ],
        "competencies": [
            {"name": "Empathy", "description": "Acknowledges frustration sincerely"},
            {"name": "Problem solving", "description": "Proposes realistic options"},
            {"name": "Clarity", "description": "Clear timelines and next steps"},
        ],
        "opening_line": "Hello? I ordered a gift for my mother 10 days ago and it still hasn't come! Deepavali is in 3 days. What is going on?",
    },
    {
        "slug": "science-fair",
        "emoji": "🔬",
        "difficulty": "medium",
        "title": "Present your project to a judge",
        "summary": "Explain your AI-based crop disease project to a science fair judge in 2 minutes and answer their questions.",
        "learner_role": "A Class 12 student presenting an app that detects leaf disease from photos",
        "character": {
            "name": "Dr. Fathima",
            "persona": "an agricultural scientist judging the state science fair",
            "goal": "test whether the student truly understands their project and its limits",
            "style": "curious, asks 'why' and 'what if' questions",
        },
        "setting": "The project stall at a busy science fair.",
        "objectives": [
            "Explain the problem and solution simply",
            "Describe how the model was trained",
            "Admit limitations honestly",
        ],
        "competencies": [
            {"name": "Explanation", "description": "Clear problem → solution story"},
            {"name": "Technical depth", "description": "Understands data and training"},
            {"name": "Critical thinking", "description": "Discusses limits and improvements"},
        ],
        "opening_line": "Good morning! I have a few minutes. Tell me what your project does and why it matters.",
    },
    {
        "slug": "ask-teacher-help",
        "emoji": "🙋",
        "difficulty": "easy",
        "title": "Ask your teacher for help",
        "summary": "You didn't understand today's maths topic. Ask your teacher for help clearly and confidently after class.",
        "learner_role": "A Class 10 student who is confused about quadratic equations",
        "character": {
            "name": "Mr. Senthil",
            "persona": "a busy but kind maths teacher with 2 minutes before the next class",
            "goal": "understand exactly what the student is stuck on",
            "style": "encouraging, asks the student to be specific",
        },
        "setting": "The classroom doorway right after the bell.",
        "objectives": [
            "Say specifically what you don't understand",
            "Ask for a concrete next step",
            "Thank the teacher",
        ],
        "competencies": [
            {"name": "Specificity", "description": "Pinpoints the exact doubt"},
            {"name": "Confidence", "description": "Speaks up without apologising too much"},
            {"name": "Politeness", "description": "Respectful and appreciative"},
        ],
        "opening_line": "Yes, tell me quickly — I have another class in two minutes. What's the doubt?",
    },
]


def ensure_library():
    """Create the built-in scenarios when they are missing (fresh database, admin delete, new built-ins).
    Checks the DB, not a process flag, so new rows appear without a restart. One cheap COUNT query."""
    from .models import Scenario

    if Scenario.objects.filter(source="library").count() != len(LIBRARY):
        sync_library()


def sync_library():
    from .models import Scenario

    for s in LIBRARY:
        Scenario.objects.update_or_create(
            source="library", slug=s["slug"], defaults={k: v for k, v in s.items() if k != "slug"}
        )
