# ruff: noqa: ISC004 — long article bodies are split across lines on purpose
"""Starter help articles (original copy). Admins edit them in the console; this only seeds empty databases."""

ARTICLES = [
    (
        "start",
        "welcome",
        "Welcome to Aasan",
        "Aasan-க்கு வரவேற்கிறோம்",
        "Aasan is your AI learning mentor. Tell it what you want to learn and it builds a course with short lessons, activities and reviews.\n\n"
        "- **Home** shows what to do next.\n- **Today** has quick revision stations.\n- **Ask Aasan** answers your questions in English or Tamil.\n- **Kili** (the parrot) cheers you on and explains things.",
        "ஆசான் உங்கள் AI கற்றல் வழிகாட்டி. நீங்கள் என்ன கற்க விரும்புகிறீர்கள் என்று சொன்னால், சிறு பாடங்கள், செயல்பாடுகள், மீள்பார்வைகளுடன் ஒரு பாடநெறியை உருவாக்கும்.\n\n"
        "- **முகப்பு** அடுத்து என்ன செய்வது என்று காட்டும்.\n- **இன்று** விரைவு மீள்பார்வை நிலையங்கள்.\n- **ஆசானிடம் கேள்** ஆங்கிலம் அல்லது தமிழில் பதில் சொல்லும்.\n- **கிளி** உங்களை ஊக்கப்படுத்தி விளக்கும்.",
    ),
    (
        "start",
        "create-course",
        "Create your first course",
        "உங்கள் முதல் பாடநெறியை உருவாக்குங்கள்",
        'Go to **Learn → New course**, type a goal (for example *"Learn Excel for my shop accounts"*) and choose a level. Aasan writes the outline in a few seconds; each lesson is prepared when you open it.\n\n'
        "Tip: you can also start from a template or a learning path, or build a course from your own notes in **My notes**.",
        '**கற்றல் → புதிய பாடநெறி** சென்று இலக்கை எழுதுங்கள் (எ.கா. *"என் கடைக் கணக்குகளுக்கு Excel கற்க"*), நிலையைத் தேர்ந்தெடுங்கள். சில நொடிகளில் சுருக்கம் தயாராகும்; ஒவ்வொரு பாடமும் திறக்கும்போது தயாராகும்.\n\n'
        "குறிப்பு: வார்ப்புரு, கற்றல் பாதை, அல்லது **என் குறிப்புகள்** இலிருந்தும் தொடங்கலாம்.",
    ),
    (
        "learn",
        "lessons-activities",
        "Lessons, activities and hints",
        "பாடங்கள், செயல்பாடுகள், குறிப்புகள்",
        "Each lesson has a short explanation and a few activities (quiz, fill in the blanks, sorting, code, role-play and more). Your first try counts for the lesson score; you can always try again.\n\n"
        "Stuck? Tap **Give me a nudge** — it's free. A fuller hint or a worked example costs a few coins and never gives away the answer. Select any words in a lesson and tap **Explain this** for a simple explanation.",
        "ஒவ்வொரு பாடத்திலும் சிறு விளக்கமும் சில செயல்பாடுகளும் உண்டு (வினாடி வினா, இடைவெளி நிரப்பு, வகைப்படுத்தல், கோடு, ரோல்-ப்ளே…). முதல் முயற்சி மதிப்பெண்ணுக்குக் கணக்கு; மீண்டும் முயற்சிக்கலாம்.\n\n"
        "சிக்கலா? **ஒரு சிறு தூண்டல்** இலவசம். முழுக் குறிப்பு அல்லது தீர்த்த எடுத்துக்காட்டுக்குச் சில நாணயங்கள்; பதிலைச் சொல்லாது. பாடத்தில் சொற்களைத் தேர்ந்தெடுத்து **இதை விளக்கு** என்பதைத் தொடுங்கள்.",
    ),
    (
        "learn",
        "review-today",
        "Reviews and the Today screen",
        "மீள்பார்வையும் இன்று திரையும்",
        "Aasan brings back what you learnt just before you'd forget it (spaced repetition). **Review** shows cards that are due.\n\n"
        "**Today** puts a few short stations together — due reviews, a weak spot, a quick quiz and a mini role-play. Pick a focus skill, swap a station with **Another one**, and finish them all for bonus XP.",
        "மறப்பதற்குச் சற்று முன் ஆசான் நீங்கள் கற்றதை மீண்டும் காட்டும் (இடைவெளி மீள்பார்வை). **மீள்பார்வை** காத்திருக்கும் அட்டைகளைக் காட்டும்.\n\n"
        "**இன்று** சில சிறு நிலையங்களைத் தரும் — மீள்பார்வை, பலவீனம், விரைவு வினாடி வினா, சிறு ரோல்-ப்ளே. கவனத் திறனைத் தேர்ந்தெடுங்கள், **வேறொன்று** மூலம் மாற்றுங்கள்; அனைத்தையும் முடித்தால் கூடுதல் XP.",
    ),
    (
        "learn",
        "mentor-voice-live",
        "Ask Aasan, voice and Live Class",
        "ஆசானிடம் கேள், குரல், நேரலை வகுப்பு",
        "**Ask Aasan** is a chat mentor. Turn on the microphone to talk instead of typing. In **Live Class** you can show your notebook or screen and talk to Kili like a tutor.\n\n"
        "Answers can be wrong sometimes — tap 👎 and **Report a problem** if something looks off.",
        "**ஆசானிடம் கேள்** ஒரு உரையாடல் வழிகாட்டி. தட்டச்சுக்குப் பதில் மைக்கை இயக்கிப் பேசலாம். **நேரலை வகுப்பில்** உங்கள் நோட்டு அல்லது திரையைக் காட்டி கிளியிடம் ஆசிரியரிடம் போலப் பேசலாம்.\n\n"
        "பதில்கள் சில சமயம் தவறாகலாம் — 👎 தொட்டு **சிக்கலைத் தெரிவி**.",
    ),
    (
        "learn",
        "translate-offline",
        "Other languages and offline learning",
        "பிற மொழிகளும் இணையமில்லாக் கற்றலும்",
        "Open a lesson and use **Read in** to read it in Tamil, Hindi, Telugu, Kannada, Malayalam, Bengali, Marathi, Gujarati or English.\n\n"
        "Bad network? On a course page tap **Save for offline**. Saved lessons open without internet; your answers are kept and checked automatically when you're back online.",
        "பாடத்தைத் திறந்து **படிக்கும் மொழி** மூலம் தமிழ், இந்தி, தெலுங்கு, கன்னடம், மலையாளம், வங்காளம், மராத்தி, குஜராத்தி அல்லது ஆங்கிலத்தில் படிக்கலாம்.\n\n"
        "இணையம் சரியில்லையா? பாடநெறிப் பக்கத்தில் **இணையமின்றிப் படிக்கச் சேமி** என்பதைத் தொடுங்கள். சேமித்த பாடங்கள் இணையமின்றித் திறக்கும்; உங்கள் பதில்கள் இணையம் வந்ததும் தானாகச் சரிபார்க்கப்படும்.",
    ),
    (
        "learn",
        "planner-pause",
        "Planner, pauses and study buddies",
        "திட்டம், இடைநிறுத்தம், படிப்புத் தோழர்",
        "The **Planner** turns your study days into short study blocks. Drag a block to another day, or skip it — Aasan moves it to your next free day.\n\n"
        "Going away or have exams? Add a **pause**: your streak is protected and reminders stop. Invite a **study buddy** to see each other's streak.",
        "**திட்டம்** உங்கள் படிப்பு நாட்களைச் சிறு நேரங்களாக மாற்றும். ஒரு நேரத்தை வேறு நாளுக்கு இழுக்கலாம் அல்லது தவிர்க்கலாம் — அடுத்த காலி நாளுக்கு நகர்த்தப்படும்.\n\n"
        "வெளியூர் அல்லது தேர்வா? **இடைநிறுத்தம்** சேருங்கள்: தொடர் பாதுகாக்கப்படும், நினைவூட்டல்கள் நிற்கும். **படிப்புத் தோழரை** அழைத்து ஒருவருக்கொருவர் தொடரைப் பாருங்கள்.",
    ),
    (
        "teach",
        "for-schools",
        "For schools and companies",
        "பள்ளிகளுக்கும் நிறுவனங்களுக்கும்",
        "Create an organisation under **Organizations**, add classes, and invite learners by email, a join code, or a joining link with a limit.\n\n"
        "Assign courses with due dates, follow progress in the cockpit, run surveys (also public ones for parents), and download Excel reports or PowerPoint slides for class.",
        "**நிறுவனங்கள்** இல் ஒரு நிறுவனத்தை உருவாக்கி, வகுப்புகளைச் சேர்த்து, மின்னஞ்சல், சேர்க்கைக் குறியீடு அல்லது வரம்புள்ள இணைப்பு மூலம் மாணவர்களை அழையுங்கள்.\n\n"
        "கெடுவுடன் பாடநெறிகளை ஒதுக்குங்கள், முன்னேற்றத்தைப் பாருங்கள், கருத்துக்கணிப்புகள் நடத்துங்கள் (பெற்றோருக்குப் பொது இணைப்பும்), Excel அறிக்கை அல்லது PowerPoint ஸ்லைடுகளைப் பதிவிறக்குங்கள்.",
    ),
    (
        "teach",
        "creator-lab",
        "Creator Lab: build your own courses",
        "படைப்பாளர் ஆய்வகம்: சொந்தப் பாடநெறிகள்",
        "In the **Creator Lab** you can let AI draft an outline, write lessons yourself, or chat with Kili (**Build with Kili**) and accept the changes you like. Add lecture videos, research a topic on the web, attach your notes, undo any change, and publish by link or to the catalog.",
        "**படைப்பாளர் ஆய்வகத்தில்** AI சுருக்கம் வரையலாம், நீங்களே பாடம் எழுதலாம், அல்லது **கிளியுடன் உருவாக்கு** மூலம் உரையாடி விரும்பிய மாற்றங்களை ஏற்கலாம். விரிவுரை வீடியோ சேர்க்கலாம், இணையத்தில் ஆய்வு செய்யலாம், குறிப்புகளை இணைக்கலாம், எந்த மாற்றத்தையும் செயல்தவிர்க்கலாம், இணைப்பு அல்லது பட்டியல் மூலம் வெளியிடலாம்.",
    ),
    (
        "account",
        "plans-payments",
        "Plans, payments and refunds",
        "திட்டங்கள், கட்டணம், பணத்திருப்பம்",
        "The free plan has daily limits. Paid plans (UPI, cards, net banking via Razorpay) raise them; renewing early adds days, nothing is lost. You get a GST invoice for every payment under **Plans → Payment history**.\n\n"
        "Have a promo code or a prepaid code from your school? Enter it on the **Plans** page. Refund rules are on the **Refunds** page.",
        "இலவசத் திட்டத்தில் தினசரி வரம்புகள் உண்டு. கட்டணத் திட்டங்கள் (Razorpay மூலம் UPI, அட்டை, நெட் பேங்கிங்) அவற்றை உயர்த்தும்; முன்கூட்டியே புதுப்பித்தால் நாட்கள் சேரும். ஒவ்வொரு கட்டணத்துக்கும் **திட்டங்கள் → கட்டண வரலாறு** இல் GST விலைப்பட்டியல் கிடைக்கும்.\n\n"
        "தள்ளுபடி அல்லது பள்ளி முன்கட்டணக் குறியீடு உள்ளதா? **திட்டங்கள்** பக்கத்தில் உள்ளிடுங்கள். பணத்திருப்ப விதிகள் **பணத்திருப்பம்** பக்கத்தில்.",
    ),
    (
        "account",
        "privacy-data",
        "Your privacy and data",
        "உங்கள் தனியுரிமையும் தரவும்",
        "We use only essential storage, no ads and no tracking cookies. In **Account** you can download all your data or delete your account. Learners under 18 need a parent or guardian's consent; the guardian gets a weekly progress summary — never chats or answers.",
        "அத்தியாவசியச் சேமிப்பு மட்டுமே; விளம்பரங்களோ கண்காணிப்புக் குக்கீகளோ இல்லை. **கணக்கு** பக்கத்தில் உங்கள் தரவை முழுவதும் பதிவிறக்கலாம் அல்லது கணக்கை நீக்கலாம். 18 வயதுக்குட்பட்டோருக்குப் பெற்றோர்/பாதுகாவலர் ஒப்புதல் தேவை; அவருக்கு வாராந்திர முன்னேற்றச் சுருக்கம் மட்டுமே — உரையாடல்கள் அல்லது பதில்கள் இல்லை.",
    ),
    (
        "faq",
        "faq-wrong-answer",
        "The AI said something wrong. What should I do?",
        "AI தவறாகச் சொன்னது. என்ன செய்வது?",
        "Tap 👎 under the answer and choose a reason, or use **Report a problem** with a short note. We read every report. For important facts, check a trusted source too.",
        "பதிலின் கீழ் 👎 தொட்டுக் காரணத்தைத் தேர்ந்தெடுங்கள், அல்லது சிறு குறிப்புடன் **சிக்கலைத் தெரிவி**. ஒவ்வொரு அறிக்கையையும் படிக்கிறோம். முக்கியத் தகவல்களை நம்பகமான மூலத்திலும் சரிபாருங்கள்.",
    ),
    (
        "faq",
        "faq-streak",
        "How do streaks and coins work?",
        "தொடரும் நாணயங்களும் எப்படி?",
        "Learn something every day to grow your streak. A streak freeze (from the wardrobe shop) saves one missed day, and a planned pause protects it for longer. Coins come from lessons and reviews; spend them on hints and Kili's outfits.",
        "ஒவ்வொரு நாளும் ஏதாவது கற்றால் தொடர் வளரும். அலமாரிக் கடையிலிருந்து தொடர் உறைவு ஒரு தவறிய நாளைக் காக்கும்; திட்டமிட்ட இடைநிறுத்தம் நீண்ட காலம் காக்கும். நாணயங்கள் பாடங்களிலிருந்தும் மீள்பார்வைகளிலிருந்தும் வரும்; குறிப்புகளுக்கும் கிளியின் உடைகளுக்கும் செலவிடலாம்.",
    ),
    (
        "faq",
        "faq-limits",
        "I hit a limit. What now?",
        "வரம்பை அடைந்துவிட்டேன். இப்போது?",
        "Free limits reset daily (courses reset monthly). You can wait, use a promo or school code, or upgrade on the **Plans** page.",
        "இலவச வரம்புகள் தினமும் மீட்டமைக்கப்படும் (பாடநெறிகள் மாதந்தோறும்). காத்திருக்கலாம், தள்ளுபடி அல்லது பள்ளிக் குறியீட்டைப் பயன்படுத்தலாம், அல்லது **திட்டங்கள்** பக்கத்தில் மேம்படுத்தலாம்.",
    ),
]


def seed(apps, schema_editor=None):
    HelpArticle = apps.get_model("support", "HelpArticle")
    for i, (cat, slug, title, title_ta, body, body_ta) in enumerate(ARTICLES):
        HelpArticle.objects.get_or_create(
            slug=slug,
            defaults={
                "category": cat,
                "title": title,
                "title_ta": title_ta,
                "body_md": body,
                "body_ta_md": body_ta,
                "order": i,
            },
        )
