"""Companion voice: the push title/body and in-app bell text for every reminder, in the learner's mentor personality,
with the companion's name and emoji, rotating through a few variants so the same line never repeats twice running.

`CATALOG[moment][lang][personality]` is a list of `Variant(id, title, body)`; English and Tamil share ids and
placeholders (both are hand-written here, side by side). Static text: no LLM call ever happens on this path.

Placeholders: {name} first name, {companion} the companion's name, {emoji} its emoji, {n} streak / card count,
{course} the course in progress, {minutes} the daily goal, {hours} hours left to repair a streak. A variant whose
placeholders are not all available is skipped; variant 0 of every list uses only the moment's guaranteed ones
(GUARANTEED), so `pick()` always has something to send. Emails keep their own subject and body."""

import logging
import string
from dataclasses import dataclass

log = logging.getLogger(__name__)

TITLE_MAX, BODY_MAX = 60, 140
LANGS = ("en", "ta")
PERSONALITIES = ("anna_akka", "strict_teacher", "funny_buddy", "calm_guru")  # = preferences.PERSONALITIES
DEFAULT_PERSONALITY = "anna_akka"
EMOJI = {"kili": "🦜", "yaanai": "🐘", "mayil": "🦚"}  # keys = companions.COMPANIONS
ALWAYS = frozenset({"companion", "emoji", "minutes"})
GUARANTEED = {
    "study": ALWAYS,
    "streak_risk": ALWAYS | {"n"},
    "streak_lost_1": ALWAYS | {"n"},
    "streak_lost_2": ALWAYS | {"n", "hours"},
    "missed_day": ALWAYS,
    "reviews": ALWAYS | {"n"},
    "winback_3": ALWAYS,
    "winback_7": ALWAYS,
    "winback_30": ALWAYS,
    "backoff_notice": ALWAYS,
}
PLACEHOLDERS = frozenset({"name", "companion", "emoji", "n", "course", "minutes", "hours"})


@dataclass(frozen=True)
class Variant:
    id: str
    title: str
    body: str


@dataclass(frozen=True)
class Message:
    title: str
    body: str
    variant: str


# moment → personality → [(en title, en body, ta title, ta body), …]
_RAW = {
    "study": {
        "anna_akka": [
            (
                "{emoji} Time for today's lesson",
                "Just {minutes} minutes and today is done. {companion} is right here with you.",
                "{emoji} இன்றைய பாடத்துக்கு நேரம்",
                "{minutes} நிமிடம் போதும், இன்றைய வேலை முடிந்துவிடும். {companion} உங்களுடன் இருக்கிறது.",
            ),
            (
                "{name}, shall we study a little?",
                "Pick up “{course}” where you left off. I'll keep it short and simple.",
                "{name}, கொஞ்சம் படிக்கலாமா?",
                "“{course}” விட்ட இடத்திலிருந்து தொடரலாம். சின்னதாக, எளிதாக முடிப்போம்.",
            ),
            (
                "{emoji} {companion} saved you a seat",
                "A quick {minutes}-minute session keeps you moving. Come, let's start together.",
                "{emoji} {companion} உங்களுக்காக இடம் பிடித்துள்ளது",
                "இன்று {minutes} நிமிடம் படித்தால் போதும். வாங்க, சேர்ந்து தொடங்கலாம்.",
            ),
        ],
        "strict_teacher": [
            (
                "{emoji} Study time. No excuses today",
                "Your {minutes}-minute goal is waiting. Open the lesson and finish it.",
                "{emoji} படிக்கும் நேரம். இன்று சாக்குப்போக்கு வேண்டாம்",
                "உங்கள் {minutes} நிமிட இலக்கு காத்திருக்கிறது. பாடத்தைத் திறந்து முடியுங்கள்.",
            ),
            (
                "{name}, class has started",
                "“{course}” will not finish itself. Begin now.",
                "{name}, வகுப்பு தொடங்கிவிட்டது",
                "“{course}” தானாக முடியாது. இப்போதே தொடங்குங்கள்.",
            ),
            (
                "{emoji} Discipline beats motivation",
                "{minutes} focused minutes, every day. That is how progress is made.",
                "{emoji} ஊக்கத்தைவிட ஒழுக்கமே முக்கியம்",
                "தினமும் {minutes} நிமிடம் கவனமாக. முன்னேற்றம் இப்படித்தான் வரும்.",
            ),
        ],
        "funny_buddy": [
            (
                "{emoji} Psst! Your brain wants a snack",
                "{minutes} minutes of learning, zero calories. {companion} promises it's tasty.",
                "{emoji} ஹலோ! உங்கள் மூளைக்குப் பசிக்குதாம்",
                "{minutes} நிமிடப் பாடம், கலோரி பூஜ்யம். சுவையா இருக்கும், {companion} கியாரண்டி!",
            ),
            (
                "{name}, the lesson feels lonely",
                "“{course}” keeps asking about you. Go say hi?",
                "{name}, பாடம் தனியா ஃபீல் பண்ணுது",
                "“{course}” உங்களைப் பற்றியே கேட்டுக்கிட்டு இருக்கு. ஒரு ஹாய் சொல்லலாமா?",
            ),
            (
                "{emoji} {companion} is doing a study dance",
                "It only stops when you open today's lesson. Please. For everyone's sake.",
                "{emoji} {companion} படிப்பு டான்ஸ் ஆடுது",
                "இன்றைய பாடத்தைத் திறந்தால்தான் நிற்கும். ப்ளீஸ், எல்லோருக்காகவும்!",
            ),
        ],
        "calm_guru": [
            (
                "{emoji} A quiet moment to learn",
                "Breathe, sit, and give {minutes} minutes to your lesson. Small steps make a long road.",
                "{emoji} கற்க ஒரு அமைதியான நேரம்",
                "அமைதியாக அமர்ந்து {minutes} நிமிடம் பாடத்துக்குக் கொடுங்கள். சிறு அடிகளே நீண்ட பயணம்.",
            ),
            (
                "{name}, your lesson awaits",
                "Return to “{course}” gently. Today's step is enough.",
                "{name}, உங்கள் பாடம் காத்திருக்கிறது",
                "மெதுவாக “{course}”-க்குத் திரும்புங்கள். இன்றைய ஒரு அடி போதும்.",
            ),
            (
                "{emoji} Water wears the stone slowly",
                "A little practice each day, {minutes} minutes, and the hardest idea softens.",
                "{emoji} துளி துளியாய்ப் பாறையும் தேயும்",
                "தினமும் {minutes} நிமிடப் பயிற்சி; கடினமான கருத்தும் எளிதாகும்.",
            ),
        ],
    },
    "streak_risk": {
        "anna_akka": [
            (
                "🔥 Your {n}-day streak ends tonight",
                "One short lesson keeps it alive. {companion} believes in you.",
                "🔥 உங்கள் {n} நாள் தொடர் இன்றிரவு முடியும்",
                "ஒரு சிறிய பாடம் போதும், தொடர் தொடரும். {companion} உங்களை நம்புகிறது.",
            ),
            (
                "{name}, don't let {n} days slip away",
                "You worked hard for this streak. Five minutes now and it's safe.",
                "{name}, {n} நாள் உழைப்பை விட்டுவிடாதீர்கள்",
                "இந்தத் தொடருக்காக உழைத்திருக்கிறீர்கள். இப்போது ஐந்து நிமிடம் போதும்.",
            ),
            (
                "{emoji} Let's protect your {n}-day streak",
                "Just one lesson before bed. I'll be right there with you.",
                "{emoji} உங்கள் {n} நாள் தொடரைக் காப்போம்",
                "தூங்கும் முன் ஒரே ஒரு பாடம். நானும் கூடவே இருக்கிறேன்.",
            ),
        ],
        "strict_teacher": [
            (
                "🔥 {n}-day streak. Ends at midnight",
                "Complete one lesson today. A streak is a promise you keep.",
                "🔥 {n} நாள் தொடர். நள்ளிரவில் முடியும்",
                "இன்று ஒரு பாடத்தை முடியுங்கள். தொடர் என்பது நீங்கள் காக்கும் வாக்குறுதி.",
            ),
            (
                "{name}, your streak is at risk",
                "{n} days of effort. Do not waste them. Finish a lesson now.",
                "{name}, உங்கள் தொடர் ஆபத்தில்",
                "{n} நாள் உழைப்பு. வீணாக்காதீர்கள். இப்போதே ஒரு பாடத்தை முடியுங்கள்.",
            ),
            (
                "{emoji} No lesson yet today",
                "Your {n}-day record depends on the next few hours. Act now.",
                "{emoji} இன்று இன்னும் பாடம் இல்லை",
                "உங்கள் {n} நாள் சாதனை அடுத்த சில மணி நேரத்தில் உள்ளது. இப்போதே செயல்படுங்கள்.",
            ),
        ],
        "funny_buddy": [
            (
                "🔥 Your {n}-day streak is sweating",
                "It's scared of midnight. One lesson and it can relax. {companion} too.",
                "🔥 உங்கள் {n} நாள் தொடருக்கு வியர்க்குது",
                "நள்ளிரவைப் பார்த்துப் பயப்படுது. ஒரு பாடம் போதும், அதுக்கும் {companion}-க்கும் நிம்மதி!",
            ),
            (
                "{name}! {n} days. Don't ghost it now",
                "Your streak sent 47 worried messages. Okay, just this one. Open a lesson?",
                "{name}! {n} நாள் தொடரை இப்போ கைவிடாதீங்க",
                "உங்கள் தொடர் 47 கவலை மெசேஜ் அனுப்பியிருக்கு. சரி, இது ஒன்றுதான். பாடம் திறக்கலாமா?",
            ),
            (
                "{emoji} Streak emergency! 🚨",
                "Your {n}-day streak needs one tiny lesson. No pressure. Okay, a little pressure.",
                "{emoji} தொடர் அவசரநிலை! 🚨",
                "உங்கள் {n} நாள் தொடருக்கு ஒரு குட்டிப் பாடம் தேவை. அழுத்தம் இல்லை. சரி, கொஞ்சம் இருக்கு.",
            ),
        ],
        "calm_guru": [
            (
                "🔥 Tend your {n}-day flame",
                "A single lesson tonight keeps it burning. There is still time.",
                "🔥 உங்கள் {n} நாள் சுடரைக் காத்திடுங்கள்",
                "இன்றிரவு ஒரு பாடம், சுடர் அணையாது. இன்னும் நேரம் இருக்கிறது.",
            ),
            (
                "{name}, {n} days of steady practice",
                "Do not let today break the chain. One calm lesson is enough.",
                "{name}, {n} நாள் தொடர் பயிற்சி",
                "இன்றைய நாள் சங்கிலியை உடைக்க வேண்டாம். அமைதியான ஒரு பாடம் போதும்.",
            ),
            (
                "{emoji} The day is not over yet",
                "Your {n}-day streak rests on one small act. Sit for a few minutes.",
                "{emoji} நாள் இன்னும் முடியவில்லை",
                "உங்கள் {n} நாள் தொடர் ஒரு சிறு செயலில் உள்ளது. சில நிமிடம் அமருங்கள்.",
            ),
        ],
    },
    "streak_lost_1": {
        "anna_akka": [
            (
                "{emoji} Your {n}-day streak can come back",
                "Missed a day? It happens. Repair it today and carry on.",
                "{emoji} உங்கள் {n} நாள் தொடர் மீண்டும் வரலாம்",
                "ஒரு நாள் விட்டுப்போனதா? பரவாயில்லை. இன்றே சரிசெய்து தொடருங்கள்.",
            ),
            (
                "{name}, let's fix your streak together",
                "Your {n} days aren't gone yet. A lesson or two brings them back.",
                "{name}, உங்கள் தொடரைச் சேர்ந்து சரிசெய்வோம்",
                "உங்கள் {n} நாட்கள் இன்னும் போகவில்லை. ஒன்றிரண்டு பாடங்கள் போதும்.",
            ),
            (
                "{emoji} {companion} kept your streak safe",
                "{n} days are waiting to be repaired. Come back and claim them.",
                "{emoji} {companion} உங்கள் தொடரைப் பத்திரமாக வைத்துள்ளது",
                "{n} நாட்கள் சரிசெய்யக் காத்திருக்கின்றன. வந்து மீட்டெடுங்கள்.",
            ),
        ],
        "strict_teacher": [
            (
                "{emoji} Streak broken. Repair it today",
                "You lost a {n}-day streak. You can still win it back. Start now.",
                "{emoji} தொடர் உடைந்தது. இன்றே சரிசெய்யுங்கள்",
                "{n} நாள் தொடரை இழந்தீர்கள். இன்னும் மீட்கலாம். இப்போதே தொடங்குங்கள்.",
            ),
            (
                "{name}, yesterday was missed",
                "Recover your {n}-day streak with a repair. Do it before the offer closes.",
                "{name}, நேற்று பாடம் தவறியது",
                "உங்கள் {n} நாள் தொடரை மீட்டெடுங்கள். சலுகை முடியும் முன் செய்யுங்கள்.",
            ),
            (
                "{emoji} {n} days on the line",
                "One missed day is a mistake. Two is a habit. Repair your streak now.",
                "{emoji} {n} நாட்கள் ஆபத்தில்",
                "ஒரு நாள் தவறுவது பிழை. இரண்டு நாள் பழக்கம். இப்போதே தொடரைச் சரிசெய்யுங்கள்.",
            ),
        ],
        "funny_buddy": [
            (
                "{emoji} Oops! Your streak tripped",
                "Your {n}-day streak fell over, but it's fine. Help it up with a repair?",
                "{emoji} அச்சச்சோ! தொடர் தடுக்கி விழுந்தது",
                "உங்கள் {n} நாள் தொடர் விழுந்துவிட்டது, பரவாயில்லை. சரிசெய்து தூக்கிவிடலாமா?",
            ),
            (
                "{name}, plot twist: the streak lives",
                "Your {n} days can still be rescued. Be the hero. Cape optional.",
                "{name}, ட்விஸ்ட்: தொடர் இன்னும் உயிரோடு!",
                "உங்கள் {n} நாட்களை இன்னும் காப்பாற்றலாம். ஹீரோ ஆகுங்க. கேப் தேவையில்லை.",
            ),
            (
                "{emoji} {companion} is holding your streak",
                "It's getting heavy. {n} days heavy. Come grab it with a quick repair!",
                "{emoji} {companion} உங்கள் தொடரைத் தூக்கி வைத்துள்ளது",
                "ரொம்ப கனமா இருக்கு, {n} நாள் கனம்! சீக்கிரம் வந்து சரிசெய்யுங்க!",
            ),
        ],
        "calm_guru": [
            (
                "{emoji} A missed day is not the end",
                "Your {n}-day streak can be restored. Begin again, gently.",
                "{emoji} ஒரு நாள் தவறுவது முடிவல்ல",
                "உங்கள் {n} நாள் தொடரை மீட்கலாம். மெதுவாக மீண்டும் தொடங்குங்கள்.",
            ),
            (
                "{name}, the path is still here",
                "{n} days of practice can be mended. Return with one lesson.",
                "{name}, பாதை இன்னும் இங்கேயே உள்ளது",
                "{n} நாள் பயிற்சியைச் சீர்செய்யலாம். ஒரு பாடத்துடன் திரும்புங்கள்.",
            ),
            (
                "{emoji} Even rivers pause",
                "Then they flow again. Repair your {n}-day streak and continue.",
                "{emoji} நதியும் சற்று நிற்கும்",
                "பிறகு மீண்டும் ஓடும். உங்கள் {n} நாள் தொடரைச் சரிசெய்து தொடருங்கள்.",
            ),
        ],
    },
    "streak_lost_2": {
        "anna_akka": [
            (
                "{emoji} {hours} hours left to save your streak",
                "Your {n}-day streak can still come back. Don't let it go, okay?",
                "{emoji} தொடரைக் காக்க {hours} மணி நேரமே உள்ளது",
                "உங்கள் {n} நாள் தொடர் இன்னும் திரும்பி வரலாம். விட்டுவிடாதீர்கள், சரியா?",
            ),
            (
                "{name}, last chance for your {n} days",
                "Only {hours} hours left to repair it. I'll wait for you.",
                "{name}, உங்கள் {n} நாட்களுக்குக் கடைசி வாய்ப்பு",
                "சரிசெய்ய இன்னும் {hours} மணி நேரமே உள்ளது. உங்களுக்காகக் காத்திருக்கிறேன்.",
            ),
        ],
        "strict_teacher": [
            (
                "{emoji} Final notice: {hours} hours left",
                "Repair your {n}-day streak now or lose it for good.",
                "{emoji} இறுதி அறிவிப்பு: {hours} மணி நேரம்",
                "உங்கள் {n} நாள் தொடரை இப்போதே சரிசெய்யுங்கள், இல்லையேல் நிரந்தரமாக இழப்பீர்கள்.",
            ),
            (
                "{name}, the deadline is close",
                "{hours} hours to recover {n} days of work. Do it today.",
                "{name}, காலக்கெடு நெருங்குகிறது",
                "{n} நாள் உழைப்பை மீட்க {hours} மணி நேரம். இன்றே செய்யுங்கள்.",
            ),
        ],
        "funny_buddy": [
            (
                "{emoji} Streak rescue: {hours}h left ⏳",
                "Your {n}-day streak is waving dramatically from the window. Save it!",
                "{emoji} தொடர் மீட்பு: {hours} மணி நேரம் ⏳",
                "உங்கள் {n} நாள் தொடர் ஜன்னலிலிருந்து கை அசைக்குது. காப்பாத்துங்க!",
            ),
            (
                "{name}, tick tock 🕰️",
                "{hours} hours until your {n}-day streak becomes a legend. Bring it back!",
                "{name}, டிக் டாக் 🕰️",
                "{hours} மணி நேரத்தில் உங்கள் {n} நாள் தொடர் வெறும் கதையாகிடும். மீட்டெடுங்க!",
            ),
        ],
        "calm_guru": [
            (
                "{emoji} {hours} hours remain",
                "Your {n}-day streak can still be restored. Choose to return.",
                "{emoji} இன்னும் {hours} மணி நேரம்",
                "உங்கள் {n} நாள் தொடரை இன்னும் மீட்கலாம். திரும்ப வரத் தீர்மானியுங்கள்.",
            ),
            (
                "{name}, the door is still open",
                "For {hours} more hours, your {n} days can be mended. Step through.",
                "{name}, கதவு இன்னும் திறந்தே உள்ளது",
                "இன்னும் {hours} மணி நேரம் உங்கள் {n} நாட்களைச் சீர்செய்யலாம். உள்ளே வாருங்கள்.",
            ),
        ],
    },
    "missed_day": {
        "anna_akka": [
            (
                "{emoji} We missed you yesterday",
                "No worries. A short {minutes}-minute lesson today gets you back on track.",
                "{emoji} நேற்று உங்களைக் காணவில்லை",
                "கவலை வேண்டாம். இன்று {minutes} நிமிடப் பாடம் போதும், மீண்டும் தொடரலாம்.",
            ),
            (
                "{name}, ready for today?",
                "Yesterday was a rest day. Today let's do a little together.",
                "{name}, இன்றைக்குத் தயாரா?",
                "நேற்று ஓய்வு நாள். இன்று சேர்ந்து கொஞ்சம் படிப்போம்.",
            ),
        ],
        "strict_teacher": [
            (
                "{emoji} You skipped yesterday's study",
                "Make it up today. {minutes} minutes, starting now.",
                "{emoji} நேற்றைய படிப்பைத் தவறவிட்டீர்கள்",
                "இன்று ஈடுசெய்யுங்கள். {minutes} நிமிடம், இப்போதே தொடங்குங்கள்.",
            ),
            (
                "{name}, back to routine",
                "Missing one day is fine. Missing two is not. Study today.",
                "{name}, மீண்டும் வழக்கத்துக்கு",
                "ஒரு நாள் தவறலாம். இரண்டு நாள் கூடாது. இன்று படியுங்கள்.",
            ),
        ],
        "funny_buddy": [
            (
                "{emoji} Yesterday called in sick",
                "Today is feeling great though! {minutes} minutes of learning?",
                "{emoji} நேற்று லீவு போட்டாச்சு",
                "ஆனா இன்று ஜாலியா இருக்கு! {minutes} நிமிடம் படிக்கலாமா?",
            ),
            (
                "{name}, {companion} counted the hours",
                "All 24 of them. Come back so it can stop counting.",
                "{name}, {companion} மணி நேரங்களை எண்ணியது",
                "இருபத்து நான்கும்! நீங்க வந்தாதான் எண்ணுவதை நிறுத்தும்.",
            ),
        ],
        "calm_guru": [
            (
                "{emoji} A new day, a fresh start",
                "Yesterday has passed. Give today {minutes} quiet minutes.",
                "{emoji} புதிய நாள், புதிய தொடக்கம்",
                "நேற்று கடந்துவிட்டது. இன்று {minutes} நிமிடம் அமைதியாகப் படியுங்கள்.",
            ),
            (
                "{name}, return to your practice",
                "One pause does not undo the journey. Take the next small step.",
                "{name}, பயிற்சிக்குத் திரும்புங்கள்",
                "ஒரு இடைவேளை பயணத்தை அழிக்காது. அடுத்த சிறு அடியை எடுங்கள்.",
            ),
        ],
    },
    "reviews": {
        "anna_akka": [
            (
                "🔁 {n} review cards are waiting",
                "Five minutes now saves an hour later. Let's go through them together.",
                "🔁 {n} மீள்பார்வை அட்டைகள் காத்திருக்கின்றன",
                "இப்போது ஐந்து நிமிடம், பிறகு ஒரு மணி நேரம் மிச்சம். சேர்ந்து பார்ப்போம்.",
            ),
            (
                "{name}, time for a quick revision",
                "{n} cards are due. Revising now helps it stick for good.",
                "{name}, ஒரு சிறிய மீள்பார்வை செய்வோமா?",
                "{n} அட்டைகள் தயாராக உள்ளன. இப்போது பார்த்தால் நன்றாக நினைவில் நிற்கும்.",
            ),
            (
                "{emoji} {companion} found {n} cards for you",
                "A quick review keeps what you learned fresh. Shall we?",
                "{emoji} {companion} உங்களுக்காக {n} அட்டைகள் வைத்துள்ளது",
                "சிறிய மீள்பார்வை, கற்றது மறக்காது. தொடங்கலாமா?",
            ),
        ],
        "strict_teacher": [
            (
                "🔁 {n} reviews due",
                "Revise them now, before you forget. Memory needs practice.",
                "🔁 {n} மீள்பார்வைகள் நிலுவையில்",
                "மறக்கும் முன் இப்போதே மீள்பார்வை செய்யுங்கள். நினைவுக்குப் பயிற்சி தேவை.",
            ),
            (
                "{name}, your reviews are piling up",
                "{n} cards. Clear them today. Do not let them grow.",
                "{name}, மீள்பார்வைகள் குவிகின்றன",
                "{n} அட்டைகள். இன்றே முடியுங்கள். மேலும் சேரவிடாதீர்கள்.",
            ),
            (
                "{emoji} Revision is not optional",
                "{n} cards are waiting. Ten focused minutes. Begin.",
                "{emoji} மீள்பார்வை கட்டாயம்",
                "{n} அட்டைகள் காத்திருக்கின்றன. பத்து நிமிடம் கவனமாக. தொடங்குங்கள்.",
            ),
        ],
        "funny_buddy": [
            (
                "🔁 {n} cards are throwing a party",
                "You're the guest of honour. Show up for five minutes?",
                "🔁 {n} அட்டைகள் பார்ட்டி வைக்குது",
                "நீங்கதான் சிறப்பு விருந்தினர். ஐந்து நிமிடம் வரலாமா?",
            ),
            (
                "{name}, your flashcards miss you",
                "{n} of them made a sad little queue. Go cheer them up!",
                "{name}, உங்கள் அட்டைகள் உங்களைத் தேடுது",
                "{n} அட்டைகள் சோகமா வரிசையில் நிக்குது. போய் உற்சாகப்படுத்துங்க!",
            ),
            (
                "{emoji} Brain gym is open 💪",
                "{n} review cards today. Quick reps, big gains.",
                "{emoji} மூளை ஜிம் திறந்தாச்சு 💪",
                "இன்று {n} மீள்பார்வை அட்டைகள். சின்ன பயிற்சி, பெரிய பலன்.",
            ),
        ],
        "calm_guru": [
            (
                "🔁 {n} cards to revisit",
                "What is reviewed is remembered. Spend a few calm minutes.",
                "🔁 மீண்டும் பார்க்க {n} அட்டைகள்",
                "மீண்டும் பார்ப்பதே நினைவில் நிற்கும். சில நிமிடம் அமைதியாகச் செலவிடுங்கள்.",
            ),
            (
                "{name}, return to what you learned",
                "{n} cards are ready. Revisit them and let them settle.",
                "{name}, கற்றதை மீண்டும் பாருங்கள்",
                "{n} அட்டைகள் தயார். மீண்டும் பார்த்து மனதில் பதிய விடுங்கள்.",
            ),
            (
                "{emoji} Memory is a garden",
                "{n} cards need watering today. A little care goes far.",
                "{emoji} நினைவு ஒரு தோட்டம்",
                "இன்று {n} அட்டைகளுக்கு நீர் ஊற்ற வேண்டும். சிறு கவனம், பெரும் பலன்.",
            ),
        ],
    },
    "winback_3": {
        "anna_akka": [
            (
                "{emoji} Your lessons miss you",
                "It's been a few days. One short lesson gets you going again.",
                "{emoji} உங்கள் பாடங்கள் உங்களை எதிர்பார்க்கின்றன",
                "சில நாட்கள் ஆகிவிட்டன. ஒரு சிறிய பாடம் போதும், மீண்டும் தொடங்கலாம்.",
            ),
            (
                "{name}, {companion} misses you",
                "Three days without you! Come back for just {minutes} minutes?",
                "{name}, {companion} உங்களைத் தேடுகிறது",
                "மூன்று நாள் ஆச்சு! {minutes} நிமிடத்துக்காவது வாங்களேன்?",
            ),
        ],
        "strict_teacher": [
            (
                "{emoji} Three days without study",
                "Habits fade fast. Return today with one lesson.",
                "{emoji} மூன்று நாட்களாகப் படிப்பு இல்லை",
                "பழக்கம் விரைவில் மறையும். இன்று ஒரு பாடத்துடன் திரும்புங்கள்.",
            ),
            (
                "{name}, you have work pending",
                "“{course}” is unfinished. Resume it today.",
                "{name}, உங்கள் வேலை நிலுவையில் உள்ளது",
                "“{course}” இன்னும் முடியவில்லை. இன்றே தொடருங்கள்.",
            ),
        ],
        "funny_buddy": [
            (
                "{emoji} Is this thing on? 🎤",
                "{companion} here! Three days of silence. One lesson and we're friends again.",
                "{emoji} ஹலோ, கேக்குதா? 🎤",
                "{companion} இங்கே! மூணு நாளா சத்தமே இல்ல. ஒரு பாடம், மீண்டும் நண்பர்கள்!",
            ),
            (
                "{name}, I've been practising alone",
                "It's not the same without you. {minutes} minutes, for old times' sake?",
                "{name}, நான் தனியா பயிற்சி பண்றேன்",
                "நீங்க இல்லாம சரியில்ல. பழைய நினைவுக்காக {minutes} நிமிடம்?",
            ),
        ],
        "calm_guru": [
            (
                "{emoji} The lesson waits patiently",
                "A few days have passed. Return whenever you are ready; today is good.",
                "{emoji} பாடம் பொறுமையாகக் காத்திருக்கிறது",
                "சில நாட்கள் கடந்தன. தயாரானதும் திரும்புங்கள்; இன்றே நல்ல நாள்.",
            ),
            (
                "{name}, come back to the quiet",
                "A few minutes with your lesson can steady the whole day.",
                "{name}, அமைதிக்குத் திரும்புங்கள்",
                "பாடத்துடன் சில நிமிடங்கள், முழு நாளையும் நிதானமாக்கும்.",
            ),
        ],
    },
    "winback_7": {
        "anna_akka": [
            (
                "{emoji} It's been a week. Pick up where you left off",
                "Everything is just as you left it. Come back for a short lesson.",
                "{emoji} ஒரு வாரம் ஆகிவிட்டது. விட்ட இடத்திலிருந்து தொடருங்கள்",
                "நீங்கள் விட்டபடியே எல்லாம் இருக்கிறது. ஒரு சிறிய பாடத்துக்கு வாருங்கள்.",
            ),
            (
                "{name}, a week away is fine",
                "Here's the easiest way back in: {minutes} minutes, starting now.",
                "{name}, ஒரு வார இடைவெளி பரவாயில்லை",
                "திரும்பி வர எளிய வழி: {minutes} நிமிடம், இப்போதே.",
            ),
        ],
        "strict_teacher": [
            (
                "{emoji} One week without practice",
                "Restart today, before the gap grows wider.",
                "{emoji} ஒரு வாரமாகப் பயிற்சி இல்லை",
                "இடைவெளி பெரிதாகும் முன் இன்றே மீண்டும் தொடங்குங்கள்.",
            ),
            (
                "{name}, time to get back on track",
                "A week is long enough. Open one lesson today.",
                "{name}, மீண்டும் வழிக்கு வர நேரம்",
                "ஒரு வாரம் போதும். இன்று ஒரு பாடத்தைத் திறங்கள்.",
            ),
        ],
        "funny_buddy": [
            (
                "{emoji} A whole week?! 😱",
                "{companion} has rearranged your lessons 14 times. Come and see!",
                "{emoji} ஒரு முழு வாரமா?! 😱",
                "{companion} உங்கள் பாடங்களை 14 தடவை அடுக்கி வச்சாச்சு. வந்து பாருங்க!",
            ),
            (
                "{name}, missing person report filed",
                "Last seen: a week ago. Reward: a lesson that takes {minutes} minutes.",
                "{name}, காணவில்லை புகார் கொடுத்தாச்சு",
                "கடைசியாகப் பார்த்தது: ஒரு வாரம் முன். பரிசு: {minutes} நிமிடப் பாடம்.",
            ),
        ],
        "calm_guru": [
            (
                "{emoji} A week has passed",
                "The path does not mind the pause. Take one step back onto it.",
                "{emoji} ஒரு வாரம் கடந்துவிட்டது",
                "இடைவேளையைப் பாதை பொருட்படுத்தாது. மீண்டும் ஒரு அடி எடுத்து வையுங்கள்.",
            ),
            (
                "{name}, begin again, gently",
                "Every return is a small victory. Today is a fine day for one.",
                "{name}, மெதுவாக மீண்டும் தொடங்குங்கள்",
                "ஒவ்வொரு திரும்புதலும் ஒரு சிறு வெற்றி. இன்று அதற்கு நல்ல நாள்.",
            ),
        ],
    },
    "winback_30": {
        "anna_akka": [
            (
                "{emoji} Come back to Aasan: 5 minutes is enough",
                "Everything you made is still here, waiting for you.",
                "{emoji} Aasan-க்கு மீண்டும் வாருங்கள்: 5 நிமிடம் போதும்",
                "நீங்கள் செய்தவை அனைத்தும் அப்படியே உங்களுக்காக இருக்கின்றன.",
            ),
            (
                "{name}, it's been a while",
                "No pressure at all. One small lesson whenever you're ready.",
                "{name}, ரொம்ப நாள் ஆச்சு",
                "எந்த அழுத்தமும் இல்லை. தயாரானதும் ஒரு சிறிய பாடம்.",
            ),
        ],
        "strict_teacher": [
            (
                "{emoji} A month away from study",
                "Start small, but start today. Five minutes.",
                "{emoji} ஒரு மாதமாகப் படிப்பு இல்லை",
                "சிறிதாகத் தொடங்குங்கள், ஆனால் இன்றே. ஐந்து நிமிடம்.",
            ),
            (
                "{name}, your goals are still waiting",
                "A month has passed. The best time to restart is now.",
                "{name}, உங்கள் இலக்குகள் காத்திருக்கின்றன",
                "ஒரு மாதம் கடந்துவிட்டது. மீண்டும் தொடங்கச் சிறந்த நேரம் இப்போதுதான்.",
            ),
        ],
        "funny_buddy": [
            (
                "{emoji} {companion} grew a beard waiting",
                "A whole month! Come back before it needs a haircut. Five minutes?",
                "{emoji} காத்திருந்து {companion}-க்குத் தாடி வளர்ந்தாச்சு",
                "ஒரு மாசம்! முடிவெட்டும் முன் வாங்க. ஐந்து நிமிடம்?",
            ),
            (
                "{name}, remember me? 👋",
                "It's been a month. I still remember everything you learned!",
                "{name}, என்னை நினைவிருக்கா? 👋",
                "ஒரு மாசம் ஆச்சு. நீங்க கற்றது எல்லாம் எனக்கு இன்னும் நினைவிருக்கு!",
            ),
        ],
        "calm_guru": [
            (
                "{emoji} The door is always open",
                "A month has passed. Five quiet minutes is a fine way to return.",
                "{emoji} கதவு எப்போதும் திறந்தே இருக்கிறது",
                "ஒரு மாதம் கடந்தது. அமைதியான ஐந்து நிமிடம், திரும்ப நல்ல வழி.",
            ),
            (
                "{name}, what you learned is still yours",
                "Return, and you will find it waiting. Begin with one lesson.",
                "{name}, கற்றது இன்னும் உங்களிடமே உள்ளது",
                "திரும்பி வாருங்கள், அது காத்திருக்கும். ஒரு பாடத்துடன் தொடங்குங்கள்.",
            ),
        ],
    },
    "backoff_notice": {
        "anna_akka": [
            (
                "{emoji} I'll remind you less often",
                "You haven't opened my reminders lately, so I've paused them. Turn them back on in Account.",
                "{emoji} இனி குறைவாக நினைவூட்டுவேன்",
                "சமீபத்தில் நினைவூட்டல்களைத் திறக்கவில்லை, அதனால் நிறுத்தியுள்ளேன். கணக்கு பக்கத்தில் மீண்டும் இயக்கலாம்.",
            ),
            (
                "{name}, I've paused your reminders",
                "I don't want to bother you. Study any time and they'll start again.",
                "{name}, நினைவூட்டல்களை நிறுத்தியுள்ளேன்",
                "உங்களைத் தொந்தரவு செய்ய விரும்பவில்லை. எப்போது படித்தாலும் மீண்டும் தொடங்கும்.",
            ),
        ],
        "strict_teacher": [
            (
                "{emoji} Reminders paused",
                "You ignored the last few. Study once, or resume them in Account.",
                "{emoji} நினைவூட்டல்கள் நிறுத்தப்பட்டன",
                "கடைசி சில நினைவூட்டல்களைத் திறக்கவில்லை. ஒருமுறை படியுங்கள், அல்லது கணக்கு பக்கத்தில் மீண்டும் இயக்குங்கள்.",
            ),
            (
                "{name}, reminders are on hold",
                "They will restart the moment you complete a lesson.",
                "{name}, நினைவூட்டல்கள் நிறுத்திவைக்கப்பட்டன",
                "நீங்கள் ஒரு பாடத்தை முடித்தவுடன் மீண்டும் தொடங்கும்.",
            ),
        ],
        "funny_buddy": [
            (
                "{emoji} Okay, I'll stop knocking 🚪",
                "Reminders paused. One lesson (or Resume in Account) and I'm back!",
                "{emoji} சரி, இனி கதவைத் தட்ட மாட்டேன் 🚪",
                "நினைவூட்டல்கள் நிறுத்தம். ஒரு பாடம் படிச்சா (அல்லது கணக்கு பக்கத்தில் இயக்கினா) திரும்ப வந்துருவேன்!",
            ),
            (
                "{name}, I'm taking the hint 🙈",
                "No more reminders for now. Study any time and I'll cheer again.",
                "{name}, புரிஞ்சுகிட்டேன் 🙈",
                "இப்போதைக்கு நினைவூட்டல் இல்லை. எப்போ படிச்சாலும் மீண்டும் உற்சாகப்படுத்துவேன்.",
            ),
        ],
        "calm_guru": [
            (
                "{emoji} Silence, for now",
                "Your reminders are paused. They return when you do, or with Resume in Account.",
                "{emoji} இப்போதைக்கு அமைதி",
                "நினைவூட்டல்கள் நிறுத்தப்பட்டுள்ளன. நீங்கள் திரும்பும்போது, அல்லது கணக்கு பக்கத்தில் இயக்கினால் மீண்டும் வரும்.",
            ),
            (
                "{name}, I will wait quietly",
                "Reminders are paused. Return whenever you are ready.",
                "{name}, அமைதியாகக் காத்திருப்பேன்",
                "நினைவூட்டல்கள் நிறுத்தப்பட்டுள்ளன. தயாரானதும் திரும்புங்கள்.",
            ),
        ],
    },
}


def _build() -> dict:
    out: dict = {}
    for moment, by_personality in _RAW.items():
        for personality, rows in by_personality.items():
            for i, (en_t, en_b, ta_t, ta_b) in enumerate(rows):
                vid = f"{moment}.{personality}.{i}"
                out.setdefault(moment, {}).setdefault("en", {}).setdefault(personality, []).append(
                    Variant(vid, en_t, en_b)
                )
                out[moment].setdefault("ta", {}).setdefault(personality, []).append(Variant(vid, ta_t, ta_b))
    return out


CATALOG = _build()
MOMENTS = tuple(CATALOG)


def fields(v: Variant) -> set[str]:
    return {f for text in (v.title, v.body) for _, f, _, _ in string.Formatter().parse(text) if f}


def first_name(user, fallback: str = "Hi") -> str:
    name = (getattr(getattr(user, "profile", None), "display_name", "") or "").strip()
    return name.split()[0][:30] if name else fallback


_first_name = first_name  # winback imports it under its old name


def lang_of(user) -> str:
    return "ta" if getattr(getattr(user, "profile", None), "language", "en") == "ta" else "en"


def _context(user, prefs: dict, ctx: dict) -> dict:
    from .companions import COMPANIONS, DEFAULT_CHARACTER

    character = prefs["mascot"].get("character") or DEFAULT_CHARACTER
    companion = (prefs["mascot"].get("name") or "").strip() or COMPANIONS.get(character, {}).get(
        "name", "Kili"
    )
    values = {
        "companion": companion[:24],
        "emoji": EMOJI.get(character, EMOJI[DEFAULT_CHARACTER]),
        "minutes": prefs["learning"].get("daily_goal_minutes") or 15,
        "name": first_name(user, ""),
    }
    values.update(ctx)
    if values.get("course"):
        values["course"] = str(values["course"])[:40]
    return {k: v for k, v in values.items() if v not in (None, "")}


def _render(v: Variant, values: dict) -> tuple[str, str]:
    safe = {k: values.get(k, "") for k in PLACEHOLDERS}
    return v.title.format(**safe)[:TITLE_MAX].strip(), v.body.format(**safe)[:BODY_MAX].strip()


def _rotate(user, moment: str, variants: list[Variant], usable: list[int]) -> Variant:
    from .cadence import state_for
    from .models import ReminderState

    st = state_for(user)
    last = (st.last_variants or {}).get(moment)
    ids = [v.id for v in variants]
    start = ids.index(last) + 1 if last in ids else (user.id or 0) % len(variants)
    for step in range(len(variants)):
        i = (start + step) % len(variants)
        if i in usable:
            chosen = variants[i]
            break
    else:
        chosen = variants[0]
    ReminderState.objects.filter(pk=st.pk).update(
        last_variants={**(st.last_variants or {}), moment: chosen.id}
    )
    return chosen


def pick(user, moment: str, **ctx) -> Message:
    """The next message for `moment` in the learner's language, personality and companion. Never raises."""
    try:
        from .preferences import upgrade

        prefs = upgrade(user.preferences.data)
        lang = lang_of(user)
        personality = prefs["mentor"].get("personality")
        if personality not in CATALOG[moment][lang]:
            personality = DEFAULT_PERSONALITY
        variants = CATALOG[moment][lang][personality]
        values = _context(user, prefs, ctx)
        usable = [i for i, v in enumerate(variants) if fields(v) <= set(values)]
        try:
            v = _rotate(user, moment, variants, usable)
        except Exception:
            log.exception("voice: rotation for user %s failed", getattr(user, "id", None))
            v = variants[usable[0] if usable else 0]
        title, body = _render(v, values)
        return Message(title, body, v.id)
    except Exception:
        log.exception("voice: picking %s for user %s failed", moment, getattr(user, "id", None))
        v = CATALOG.get(moment, CATALOG["study"])["en"][DEFAULT_PERSONALITY][0]
        title, body = _render(v, {"emoji": "🦜", "companion": "Kili", "minutes": 15, **ctx})
        return Message(title, body, v.id)
