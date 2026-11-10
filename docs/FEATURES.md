# Aasan – Complete Features List

Release 1.3.0 · Nov 2, 2026 · Vigneshwaran T

Every feature of the Aasan (ஆசான்) platform, marked by status: ✅ built · ⚙️ needs an API key or config · 🏫 switchable per organisation · 🧪 API only, not yet in the UI · 🚧 deferred.

## 1. Overview

Aasan is a Tamil-first AI mentor platform: learners pick a companion (Kili the parrot, Yaanai the elephant or Mayil the peacock) that teaches, grades, coaches and reacts as they learn. The product spans a learner app, a creator studio, a school and company console, AI workshops, a platform admin console and a browser extension.

**Stack**

| Part | Technology |
| --- | --- |
| API | Django 5.2, Django REST Framework, Channels (WebSockets), Celery worker + beat, Postgres 16, Redis |
| Web | React 19, Vite, TypeScript, Tailwind 4, TanStack Query, Zustand, i18next, PWA service worker |
| AI | Anthropic, OpenAI, Gemini for text and vision; Sarvam, Deepgram, Google Cloud, OpenAI and browser engines for speech |
| Payments | Razorpay (one-time, auto-renew subscriptions, refunds, GST invoices) |
| Extension | Manifest V3 (Chrome 116+, Edge), plain JavaScript, no build step |
| Infra | docker-compose: Postgres, Redis x2, Mailpit, API (gunicorn/uvicorn), Celery worker + beat, nginx |

**Who uses it**

| Role | What they get |
| --- | --- |
| Learner | Courses, lessons, mentor chat, role-play, live class, workshops, review, planner, gamification, certificates |
| Minor learner + guardian | Age band at consent; the guardian agrees by an emailed link before AI features unlock; weekly progress-only email and a read-only page |
| Creator | Creator Lab and Studio: author, import, export, publish to catalog, guest links, Connect Claude |
| Organisation owner / admin / teacher | Teacher cockpit: classes, members, assignments, surveys, analytics, certificates, workshops, journeys |
| Unit admin | A scoped cockpit for one sub-school or department |
| Staff (superadmin, support, finance, content) | Admin console sections by role; every change audited |
| Guest (no account) | Public course page, guest links, public surveys, certificate verification |

**Scale of the product**

| Measure | Count |
| --- | --- |
| Django apps | 25 |
| Web routes | 84 learner/creator/org routes + 16 admin sections |
| Lesson activity types | 19 |
| Interface languages | 9 (English and Tamil hand-written, 7 machine-translated beta) |
| WebSocket channels | 5 |
| Scheduled background jobs | 9 |
| Management commands | 12 |
| Configuration settings in `.env.example` | 66 |

## 2. Sign-in, onboarding & personalisation

Accounts use email and password, passkeys or Google; every new account passes a consent gate and an eight-step onboarding that builds the first course.

**Authentication and account security**

| Feature | What it does | Where | Status |
| --- | --- | --- | --- |
| Email sign-up and sign-in | Name, email, 8+ character password; terms acceptance | `/signup`, `/login` | ✅ |
| Passkeys (WebAuthn) | Passwordless sign-in, add/rename/remove passkeys, step-up re-authentication before sensitive changes | `/login`, `/account` | ✅ |
| Google sign-in | Verifies a Google ID token and signs in or creates the account | `POST /api/users/google/` | 🧪 API only; no button on the login page |
| Sign in with your organisation (SSO) | OpenID Connect with an organisation's Google Workspace or Microsoft Entra ID (single tenant): work email → organisation sign-in page → back to `/sso/callback`; creates or links the account (same unverified-account rule as Google) and joins the organisation with its default role and class; shown only when some organisation has SSO on; "Require SSO" turns password sign-in and sign-up off for the organisation's verified domains (owners keep a password break-glass, passkeys unaffected) | `/login`, `/sso/callback` | ✅ ⚙️ per organisation |
| Email verification | Tokened link; banner with rate-limited Resend | `/verify-email` | ✅ |
| Password reset | Emailed 6-digit code (15 min, 5 tries) or one-time link; never reveals whether the account exists | `/forgot-password`, `/reset-password` | ✅ |
| Login lockout | 10 failed attempts lock the account for 15 minutes; nginx limits auth routes to 30/min per IP | API | ✅ |
| Sessions | 30-minute access token held in memory; 30-day refresh token in an HttpOnly cookie, rotated and blacklisted on use; "sign out everywhere" | API | ✅ |
| Referral sign-up | `?ref=` code gives both people 100 coins | `/signup` | ✅ |
| Consent gate | Age band (18+ or under 18), guardian email for minors, Terms and Privacy acceptance, re-shown when policies change | all signed-in pages | ✅ |
| Guardian consent | An under-18's guardian gets a link to agree or refuse; until they agree the AI mentor, voice, role-play, live class, workshops and document uploads stay locked (lessons work); a banner tells the learner and resends the email; a new guardian address must agree afresh; a minor can't switch to adult; no win-back, promo, step-up or learned-time nudges for minors | all signed-in pages, `/guardian/:token` | ✅ |
| Guardian updates | Weekly progress-only email, read-only page, "email the link now", revoke old links, stop emails | `/account`, `/guardian/:token` | ✅ |
| Browser companion pairing | 6-digit code pairs the extension; list and remove connected browsers | `/account` | ✅ |
| Notification preferences | Study reminders, plan reminders, workshop emails, comeback emails, companion tips; one-click unsubscribe | `/account`, `/unsubscribe` | ✅ |
| Notifications on this device | Web push: turn on, choose kinds (study, streak, reviews, workshops, teacher, plan), send a test, turn off on this device; a banner explains when reminders were reduced or paused for going unopened, with Resume (`/account#push`) | `/account` | ✅ ⚙️ |
| Download my data | JSON export of personal data (DPDP Act) | `/account` | ✅ |
| Delete my account | Type DELETE plus password or emailed 6-digit OTP; blocked for a sole org owner | `/account` | ✅ |

**Onboarding** (`/onboarding`, eight steps, companion mood changes per step; `?redo=1` replays it from Personalize while keeping existing courses)

1. Meet your companion: Kili, Yaanai or Mayil; name (24 characters); colour swatch.
2. Language: interface language and reply language (Auto, English, Tamil, Tanglish).
3. How to set up: chat with Kili (an interview that fills the profile, follows skills, guesses a level and sets a goal) or pick options manually.
4. What to learn: AI basics, Python, Data science, Web dev, Prompt engineering, AI for my career, or a custom goal.
5. Work or study and role: organisation look-up with an AI summary, role, key skills pre-selected.
6. Skills: follow skills and self-rate 1 to 5.
7. Level: beginner, intermediate, advanced, or a 5-question placement check.
8. Ready: builds the first course, or returns to a shared course the learner arrived from.

**Personalize** (`/personalize`, every change saves immediately with a live companion preview and "Try moods")

| Group | Options |
| --- | --- |
| My companion | Character, name, colour; outfit (Veshti, School uniform, Festive kurta, Scientist coat); accessories (Glasses, Cricket cap, Jasmine, Headphones, Graduation cap, Sunglasses, Golden crown); position; chattiness 0 to 3; show or hide |
| Mentor style | Personality (Anna/Akka, Strict teacher, Funny buddy, Calm guru); depth (Simple, Detailed); reply language; example style (Cricket, Cinema, Farming, Coding, Daily life) |
| Look and feel | Interface language; theme (Light, Dark, Kolam, Temple, Ocean, Night study); accent colour; font (Mukta Malar, Noto Sans Tamil, Catamaran, Easy-read for dyslexia); text size 80 to 160%; reduced motion; sound effects |
| Learning | Adaptive recommendations; daily goal 5 to 120 minutes; pace (Relaxed, Steady, Intense); difficulty (Auto, Easy, Medium, Hard) |

**Public pages (no account)**

| Route | Page |
| --- | --- |
| `/s/:token` | Shared course page; lesson 1 playable without an account |
| `/g/:slug`, `/g/:slug/lesson/:id`, `/g/:slug/role-play`, `/g/:slug/done` | Guest-link landing, lesson, role-play and summary with "keep your progress" sign-up |
| `/p/:token` | Anonymous public survey with save-and-resume |
| `/verify/:code` | Certificate verification |
| `/guardian/:token` | Guardian weekly progress page |
| `/privacy`, `/terms`, `/refunds`, `/contact`, `/dpa` | Legal pages with grievance officer and effective date |
| `/unsubscribe` | One-click email unsubscribe |

## 3. Home, Ask Aasan & the companion

Home is the daily launch pad; Ask Aasan is a streaming mentor chat with voice; the companion reacts across the whole app.

**Home** (`/`)

| Card | What it shows | Status |
| --- | --- | --- |
| Continue learning | Next lesson, or "Start your first course" | ✅ |
| For You | Adaptive next-best actions with a reason: Review, Continue, Practice, Up next, New skill, Path | ✅ |
| Today card | Revision stations progress | ✅ |
| Journey card | Day X of N of an HR onboarding journey | ✅ |
| Member fields prompt | Organisation asking for missing member details | ✅ |
| Pinned charts | Up to 4 charts pinned from Progress | ✅ |
| Survey banner | Surveys waiting from teachers | ✅ |
| My assignments | Teacher-assigned courses and role-plays; mandatory and overdue first | ✅ |
| Cohort courses | Partner-programme courses with their access window | ✅ |
| Ask Aasan box | Question plus suggestion chips, handed to the mentor | ✅ |
| Tiles | Today's goal minutes, streak days, reviews due | ✅ |
| Recent conversations | Last 6 chats | ✅ |

**Ask Aasan (mentor)** (`/mentor`, `/mentor/:id`, WebSocket `ws/assistant/`)

| Feature | Detail | Status |
| --- | --- | --- |
| Streaming answers | Token-by-token over WebSocket with reconnect, backoff and re-authentication | ✅ |
| Conversations | New chat, history, URL-addressed threads; 30-message history window, 4,000-character input cap | ✅ |
| Rich answers | Markdown with GFM tables, KaTeX maths, click-to-load external images | ✅ |
| Grounded in notes | Uploaded documents are searched and cited | ✅ |
| Answer feedback | Thumbs up or down with reason (Wrong, Confusing, Too long, Not appropriate, Other), links to Report a problem | ✅ |
| Voice mode | Full-screen voice conversation (like a phone call): each pause sends the turn; Aasan's own voice is never taken as the learner's words. With Deepgram (`stt.streaming`) the learner interrupts just by talking; on the browser recogniser the mic rests while Aasan talks and a tap on the orb or Interrupt cuts in | ✅ (Deepgram, server voices ⚙️) |
| Mentor personality | Anna/Akka, Strict teacher, Funny buddy, Calm guru; reply language; example style | ✅ |
| Limits | Free plan 30 messages per day; quota refunded on provider errors; school can switch the mentor off | ✅ 🏫 |
| Stop generation | Cancels the stream | ✅ |

**Companion (Kili, Yaanai, Mayil)**

| Feature | Detail |
| --- | --- |
| Moods | idle, watching, thinking, talking, cheer, hmm, confused, sleepy, fire, celebrate, wave; temporary moods time out |
| Dock | Floating, draggable; eyes follow the pointer; click for "Any doubts?", double-click opens the mentor; minimise |
| Speech bubbles | `mascot.say(text, {actions})` with action buttons; server can drive moods over any WebSocket |
| Lip-sync | Mouth follows real audio level during speech |
| Look | Colour, outfit and accessories drawn as SVG parts per species |
| Sounds | Correct, wrong, pop, level-up tones (switchable) |
| Where it speaks | First greeting, once-per-session nudge, lesson reactions, course building, path updates, plan sheets, tours |

**Notifications**

| Channel | Detail |
| --- | --- |
| In-app bell | Unread dot, title, body, deep link; workshop announcements and reminders |
| Companion nudges | Once per session: reviews due, streak at risk, close to next level |
| Email | Study reminders (only if not yet studied that day), plan expiry reminders, workshop emails, guardian weekly digest, daily nudge digest, important emails always |
| Teacher nudges | From the cockpit "Needs attention" list and the workshop live monitor |
| Web push | Opt-in per device from Account (or Kili's offer after the first lesson): study reminders, streak at risk and reviews piling up (from each learner's nudge time, once a day each), step-up after a miss, workshop reminders, teacher nudges, plan ending; per-kind switches, test push, turn off on this device; endpoints limited to the browsers' push services, 10 devices per account, dead ones dropped; system-timed pushes never 22:00-08:00; needs VAPID keys |
| Companion voice | Push titles/bodies and the bell for study, streak at risk, step-up, reviews, win-back and the back-off notice speak in the learner's mentor personality (Anna/Akka, Strict teacher, Funny buddy, Calm guru) with the companion's name and emoji (🦜 🐘 🦚); 2-3 hand-written variants per moment in English and Tamil, rotated so a line never repeats twice running; no AI call; emails keep their own copy |
| Learned study time | Nightly: the median time of the first activity of the day over the last 21 days (needs 5+ active days); nudges go 30 minutes before it (or before the chosen reminder time), kept within 08:00-21:30. A reminder time the learner picked on Plan is kept exactly; otherwise Plan shows "We'll nudge you around HH:MM" |
| Step-up after a miss | For learners with a push device: the day the streak break is noticed (2 days after the last lesson) a "your streak can come back" nudge to the repair offer, the next day a last call with the hours left; learners without a streak get one "missed you yesterday" nudge if yesterday was a study day; once per lapse |
| Back off when ignored | Taps on reminder pushes are counted (and opening the app within 6 hours of one). 5 unopened since the last activity → reminders every other day; 8 → paused (only win-back), with one notice; at most 2 reminder pushes a day. Any tap, any lesson or Resume on Account brings them back; teacher, workshop and plan pushes are never reduced |
| Platform announcements | Admin "Announce" for a workshop run notifies every user once, in batches |
| Win-back | Daily: learners away exactly 3, 7 or 30 days (not if they opened the app in the last 2 days, are in away mode or opted out) get one personal email (the course they left, reviews due, their lost streak) + bell + push; the 7- and 30-day mails offer to revive a 3+ day streak (`/achievements?repair=1`); once per lapse episode. Day 3 is also step-up day 2: when the streak repair offer is open or step-up already sent its last nudge, the 3-day win-back sends only the email |

## 4. Courses & lessons

A learner starts from a topic or a goal, gets an AI-built course, and works through lessons that each carry a dozen learning tools and a set of graded activities.

**Creating a course** (`/learn`)

| Feature | Detail | Status |
| --- | --- | --- |
| Guided creation (GoalWizard) | Topic plus "about you"; Kili suggests three real-world scenarios and a foundations track, or checks your own use case (accept, split into smaller steps, decline); fit questions: prior knowledge, no-code, hours per week, deadline, level | ✅ |
| Direct creation | Goal and level; tone (Friendly, Professional, Playful, Exam-focused); lesson length 5/10/20 minutes; learning style (Explanations, Exercises, Examples, Videos, Role-play) | ✅ |
| Course from notes | "Build a course from this" on any uploaded document | ✅ |
| Templates strip | Start from a shared template, best matches for followed skills first | ✅ |
| Course order | Drag, arrows or keyboard reorder; AI "Suggest an order" | ✅ |
| Limits | Free plan 2 AI courses per 30 days; max two courses generating at once | ✅ |
| Course languages | English, Tamil, Tanglish | ✅ |

**Course page** (`/learn/:id`)

| Feature | Detail | Status |
| --- | --- | --- |
| Kolam progress | One petal drawn per finished lesson | ✅ |
| Save for offline | Pre-fetches every ready lesson in the chosen reading language; remove copy | ✅ |
| Start this course over | Clears progress, answers and review cards | ✅ |
| Edit my course | AI "Add a section", hide or unhide sections and lessons, move lessons, undo and redo, manage attached source documents | ✅ |
| Your path (adaptive) | See section 6 | ✅ |
| Before-and-after test | 8-question pre-test, post-test near the end, learning gain, retake after 1 hour | ✅ |
| Map view (default) | Dashboard-style map: sections around the learner's companion, a section rail, lesson cards joined by connectors (one column on phones), next lesson highlighted, scores on done cards, locked cards dashed; choice saved per learner (also in Personalize) | ✅ |
| Quest path | Path view, one tap from the map. Winding lesson nodes: done, current, locked; badges for quick check, practice, listened | ✅ |
| Section checkpoint quiz | Unlocks when a section is complete | ✅ |
| Boss battle | Section boss: correct answers hit its HP, wrong answers cost one of 3 hearts; bonus XP and coins | ✅ |
| Retry generation | For failed outlines | ✅ |

**Lesson page** (`/learn/:courseId/lesson/:lessonId`)

| Tool | Detail | Status |
| --- | --- | --- |
| Lesson generation | Generated on first open, with retry | ✅ |
| Read in | Machine translation into any of the 9 languages plus Tanglish; ids and answer keys untouched | ✅ |
| Fast-track | "I already know this": harder MCQs; all correct completes the lesson; daily budget | ✅ |
| Learn with Kili | Chat-paced tutoring one idea at a time, checks understanding, then hands over to activities; school-switchable | ✅ 🏫 |
| Interactive widget | AI-built widget in a sandboxed iframe with no internet; optional checkpoint checked on the server; owner can regenerate with instructions | ✅ |
| Explain this | Select 2 to 600 characters for an inline simple explanation | ✅ |
| Ask Aasan about this | Inline mentor chat seeded with the lesson | ✅ |
| Live class | Opens Live Class linked to the lesson | ✅ |
| Listen | Part-by-part narration: previous/next, ±10 s, speed 0.75 to 1.5×, autoplay; 80% listened marks "Listened" | ✅ |
| Explainer video | AI scene script animated in sync with narration, transcript, regenerate when the lesson changes; daily budget | ✅ |
| Podcast | Two-host episode (learner and expert voices), 3 to 6 minutes, tappable transcript, warm-up quiz while it builds | ✅ |
| Activities | Graded activities with Kili's hint ladder (section 5) | ✅ |
| Pulse check-in | Pace, difficulty, energy, expectations halfway through; offers a simpler view or go further | ✅ |
| Finish lesson | Queued offline; adaptive gate below pass mark (Start practice, Read again, Back to path) | ✅ |
| Recap | Score, confetti at 70%+, key points, star rating, too easy/just right/too hard, comment, one "about you" question, Practice more, Practise in a role-play, Next lesson | ✅ |
| Practice sets | Fresh AI practice (`/.../practice`), "More practice", 20 sets per day; unlocks finishing in adaptive courses | ✅ |

**Other learning pages**

| Route | Feature | Status |
| --- | --- | --- |
| `/catalog` | Public course catalog with level, lessons, creator and learner count | ✅ |
| `/s/:token` | Shared course page; enrol; lesson 1 free for guests | ✅ |
| `/documents`, `/documents/:id` | My notes: upload PDF, DOCX, TXT, MD up to 10 MB (text only kept); up to 30; "Ask about your notes" with page citations; build a course; school-shared notes | ✅ |
| `/paths`, `/paths/:slug` | Curated learning paths; join; each step starts an AI course | ✅ |
| `/careers`, `/careers/:slug` | Indian-market career paths with salary bands; CV upload (not kept) to detect skills; "I want to become" gap analysis; AI role assessment; role ladder; you-vs-role radar; 30-day plan with dated goals | ✅ |
| `/careers/:slug/plan/print` | Printable 30-day career plan | ✅ |
| `/skills` | Followed skills with mastery, assessed level, self-rating, reorder, unfollow, hide | ✅ |
| `/journey` | My HR onboarding journey: day X of N, phases, today/earlier/coming up, items (lesson, role-play, shadow a colleague, document, HR note), ticks | ✅ |

## 5. Lesson activity types

Nineteen activity types are graded on the server; answer keys never reach the browser. All are built (✅) and all can be authored in Creator Lab.

| Type | Label | How the learner interacts | Grading |
| --- | --- | --- | --- |
| `quiz` | Quiz | A to D choices, single or multiple answer | Key |
| `fill_blank` | Fill in the blanks | Text input per blank | Key |
| `sequencing` | Put in order | Drag or arrow buttons | Key |
| `categorization` | Sort into groups | Tap an item, then a bucket | Key |
| `matching` | Match pairs | Tap left, then right | Key |
| `open_input` | Explain in your own words | Free text, 3+ characters | AI |
| `code` | Python | Editor with Tab support, Run in the browser via Pyodide in a sandboxed iframe with timeout, expected output, model solution | AI |
| `diagram` | Diagram | Mermaid diagram plus a choice question | Key |
| `slides` | Narrated slides | Previous/next with Listen; question unlocks after all slides | Key |
| `concept_map` | Concept map | SVG map; pick each link's relationship | Key |
| `viz` | Explore | Function plot with parameter sliders, or a probability simulator (coin/die, ×1 to ×1000) plus a question | Key |
| `decision_tree` | Story | Branching story with restart; voice mode reads the scene and takes a spoken choice | Key |
| `task` | Try it | Do a real-world task, paste the result or describe it | AI |
| `map` | Find on the map | Leaflet map; tap the location; shows true spot and km off | Key |
| `hotspot` | Label the picture | Select a label and tap where it goes on the image | Key |
| `video` | Video | YouTube or uploaded lecture with start/end; pauses at timed checkpoint questions | Key |
| `browser_task` | Do it and show | Upload a screenshot proof with a note; vision model grades it; image not stored; the browser extension can watch the steps live | AI (vision) |
| `roleplay` | Role-play | Mini role-play inside the card with voice; finish for feedback, then Check to save the score | AI |
| `artifact_check` | Publish and check | Paste a public https URL; server fetches the live page against a checklist (phrases, headings, links, image count) | Server fetch |

**Shared options on every activity**

| Feature | Detail |
| --- | --- |
| Hint ladder | Nudge (free), Hint (2 coins), Worked example (5 coins); "Show again" |
| Confidence | In review sessions: Guessing, Think so, Sure; flags overconfident misses |
| Offline queue | Answers queued per activity and checked on reconnect |
| Reactions | Companion mood, sound, XP and coin toasts on check |
| Spoken answers | Spoken choice matched to an option by AI (`/api/learn/match-choice/`) |
| Error states | Grading unavailable, grading budget exceeded |

## 6. Adaptive learning engine

Every course has a concept graph; each learner gets their own path over the unchanged syllabus, with skip-checks where they already know the material and practice where a concept is shaky.

| Feature | Detail | Where | Status |
| --- | --- | --- | --- |
| Goal interview | From a topic: three real-life scenario cards plus a foundations track; or verify the learner's own use case (accept, split, decline) | `POST /api/adaptive/goals/`, `.../choose/` | ✅ |
| Constraints | Prior knowledge, no-code, hours per week, deadline, level | `.../constraints/` | ✅ |
| Concept graph | Concepts, prerequisite edges, lessons teaching 1 to 3 concepts each; AI-extracted for new outlines, one concept per lesson for older courses without AI | `adaptive.graph` | ✅ |
| Diagnostic | The course pre-test seeds mastery | checkpoint | ✅ |
| Mastery model | Bayesian Knowledge Tracing on first attempts only | `ConceptMastery` | ✅ |
| Learner path | Items: lesson, skip\_check (fast-track), remediation (practice), checkpoint, final; pure planner re-plans only pending items | `GET /api/adaptive/courses/<id>/path/` | ✅ |
| Re-planning triggers | Lesson complete, checkpoint, fast-track, practice | `adaptive.services` | ✅ |
| Completion gating | A lesson below the pass mark cannot be finished until its practice step is done (returns 200 `passed:false`) | lesson complete | ✅ |
| Certificate gating | Adaptive learners need every critical concept at 0.8 or above | credentials | ✅ |
| Skill map | Goal skills as Mastered, Learning, Needs practice, Not started | `GET .../skill-map/` | ✅ |
| Path panel | Progress, "Coming up" with reasons, "Your path was updated" notices | course page | ✅ |
| Generation uses learner state | Lesson generation reads prior knowledge and constraints | learning | ✅ |
| Adaptive toggle | Learner can switch adaptive recommendations off | Personalize | ✅ |

## 7. Review, Today, Planner & Progress

Spaced repetition, a daily revision circuit, a weekly planner synced with the learner's calendar, and analytics with AI insights.

**Review** (`/review`, `/api/review/`)

| Feature | Detail | Status |
| --- | --- | --- |
| Spaced-repetition deck | Cards due now, next review time, deck size, reviewed today, due per course | ✅ |
| Session | One card at a time with confidence prompt; done screen with average and confetti | ✅ |
| Modes | `section` checkpoint quiz, `course` quiz, `quick` quiz, `exam` timed 5-minute round | ✅ |
| Mastery graph | `/mastery/:id`: clickable lesson graph (New, Learning, Practicing, Mastered, review due), skill bars | ✅ |

**Today** (`/today`, `/api/study/today/`)

| Feature | Detail | Status |
| --- | --- | --- |
| Stations | Spaced review, weak-spot drill, quick quiz, mini role-play, continue lesson, timed exam round | ✅ |
| Focus theme | Mixed or a followed skill | ✅ |
| Station actions | Start, open again, mark done, swap (limited), one more circuit | ✅ |
| Revision tiers | Seedling, Sprout, Explorer, Achiever, Scholar, Master | ✅ |
| Weekly revision board | Score = reviews + 3 × stations; privacy toggle | ✅ |

**Planner** (`/plan`, `/api/study/blocks|pauses|buddies/`, `/api/calendar/`, `/api/game/plan*`)

| Feature | Detail | Status |
| --- | --- | --- |
| Week planner | Drag blocks between days; done, skip (re-plans), undo, delete, move; custom blocks; kinds Today's revision, Learn, Practice, Review, Study | ✅ |
| Calendar connect | Google Calendar or Outlook, read-only free/busy; "Re-plan around my calendar" over 14 days | ✅ ⚙️ OAuth client ids |
| Pause / away mode | From, to, reason (Away, Exams, Festival, Not well, Other), up to 60 days; protects streak, mutes reminders | ✅ |
| Study buddies | Invite link, see each other's streak and week, remove | ✅ |
| Study days and time | Drives reminders and the daily goal; when no time was picked, shows the learned study time the nudges follow | ✅ |
| Add to my calendar | `.ics` download with a 10-minute reminder | ✅ |
| Subscribe | Private auto-updating `webcal:` feed with token rotation | ✅ |

**Progress** (`/progress`, `/api/study/progress/`)

| Feature | Detail | Status |
| --- | --- | --- |
| Ranges | 7, 30, 90, 365 days | ✅ |
| Stats | Time, active days, first-try accuracy, lessons, sessions, XP, streak, best streak | ✅ |
| Kili's weekly insights | AI headline, summary, strengths, focus next | ✅ |
| Ask about your learning | Natural-language question; AI picks a chart from a fixed metric catalog (never runs model-written queries) | ✅ |
| Charts | Learning time per day, XP per day, skill mastery, first-try accuracy by activity type, minutes by weekday; each pinnable to Home | ✅ |
| Knowledge graph | Concept view | ✅ |
| Quarterly review | `/progress/review`: AI-written covered, mastered, room to grow, next-quarter goals; PDF (print) and Excel; share panel | ✅ |
| Checkpoints | `/checkpoints`: before/after scores and learning gain per course | ✅ |
| Excel export | `/api/studio/exports/progress.xlsx` | ✅ |

## 8. Gamification

XP, coins, streaks, badges and a wardrobe shop run through every learning action; awards are idempotent on the server.

| Feature | Detail | Where | Status |
| --- | --- | --- | --- |
| XP and levels | Level ring in the top bar, daily-goal XP bar, level-up toasts and sound | GameBar, `/achievements` | ✅ |
| Coins | Earned on activities; spent on hints and wardrobe | GameBar | ✅ |
| Streaks | Daily streak, best streak, streak freezes (bought in the shop, capped) | `/achievements`, `/shop` | ✅ |
| Streak repair | A broken streak (2+ days) can be brought back for 7 days: 300 coins, or free by finishing 3 lessons or Today circuits within 72 hours of coming back (granted automatically); offer shows before the first activity; restores the streak plus the days since, best streak and badges | Home, `/today`, `/achievements` (`?repair=1`) | ✅ 🏫 |
| Kolam rings | Learning kolams at 6, 12, 18, 24, 30 petals | `/achievements` | ✅ |
| Badges | Catalog of badges with last-4-weeks activity | `/achievements` | ✅ |
| Invite friends | Referral link `/signup?ref=`; both get 100 coins | `/achievements` | ✅ |
| Leaderboard | Weekly XP, first names only, leagues Bronze, Silver, Gold, Diamond; opt-in visibility; your rank even outside the top 20 | `/leaderboard` | ✅ 🏫 |
| Class and school leaderboards | Tabs for Everyone, your organisation and each of your classes (`?scope=org|class`); members only (teachers by their class scope), follows the organisation's Leaderboard switch and each learner's opt-in | `/leaderboard` | ✅ 🏫 |
| Wardrobe shop | Outfits and accessories, level-locked items, wear; streak freeze purchase | `/shop` | ✅ 🏫 |
| Boss battles | Section boss with HP and 3 hearts; result decided server-side from checkpoint answers | `/learn/:id/boss/:sectionId` | ✅ |
| Reward toasts | Floating +XP, badge, level-up | AppShell | ✅ |
| Role-play rewards | Capped at 5 rewarded role-plays per day | API | ✅ |

## 9. Practice: Role-play & Live Class

Role-play puts the learner in a conversation with an AI character and a live coach; Live Class is a hands-free voice lesson that can watch a notebook or a screen.

**Role-play** (`/roleplay`, `/roleplay/:id`, `/api/roleplay/`, WebSocket `ws/roleplay/`)

| Feature | Detail | Status |
| --- | --- | --- |
| Scenario studio | Custom prompt plus difficulty (Easy, Medium, Hard); unsafe scenarios refused; built-in India-relevant library; your own scenarios; teacher-assigned scenarios with due badges | ✅ |
| Player | Streaming character replies, "You are…", turns left, goals, Enter to send, voice mode | ✅ |
| Live coach | Objective and skill chips filling turn by turn (Not yet, Started, Almost, Done), gentle fact checks, limited private hints | ✅ |
| 3D avatar | three.js animated bust with per-character look, moods, lip movement, captions; falls back to chat without WebGL | ✅ |
| Coaching report | Overall and skill scores, goals met, what went well, try next time, stronger phrasings, turn-by-turn coach report | ✅ |
| Lesson tie-in | "Practise in a role-play" builds a scenario from the lesson | ✅ |
| Answer feedback | Thumbs on replies | ✅ |
| Limits | 150 AI turns per day, 5 rewarded role-plays per day; school can switch role-play off | ✅ 🏫 |

**Live Class** (`/live`, `/live/:id`, `/api/live/`, WebSocket `ws/live/`)

| Feature | Detail | Status |
| --- | --- | --- |
| Modes | Camera (notebook or whiteboard), Share screen, Voice only | ✅ |
| On-device vision gating | Change detection sends a JPEG snapshot (up to 1024 px) only when the page changes and holds still, or on "Look at this" | ✅ (vision model ⚙️) |
| Hands-free voice | Starts automatically; mute, pause camera, switch front/back camera | ✅ |
| Captions and transcript | Big caption of the companion's last line with a 👁 marker when it looked; collapsible transcript; typed questions | ✅ |
| Recap | What we covered, mistakes to fix, practise next; past classes with transcript and "Make a recap" | ✅ |
| Privacy | Frames are never stored; only the transcript is kept | ✅ |
| Limits | 60-minute session cap; free plan 10 live minutes per day; 600 vision frames per day; school can switch Live off | ✅ 🏫 |

## 10. AI Workshops

Learner-paced workshops run by the companion with no human trainer: teach, check, do-it-yourself, build hand-ins, an agent builder and a final assessment that issues a certificate. The server owns all state; keys, rubrics and hidden tests never leave it.

**Learner flow** (`/workshops`, `/api/workshops/`, WebSocket `ws/workshop/<session_id>/`)

| Feature | Detail | Status |
| --- | --- | --- |
| Workshop list | My, Upcoming (seats left, live-now countdown, free or ₹ price, level, minutes), Past | ✅ |
| Detail and enrolment | Agenda, prerequisites, enrol free or pay via Razorpay with GST details; seat granted only after capture; refund notice if paid but full; add to calendar; proctoring notice | ✅ |
| Reminders | Email 24 h and 15 min before the start | ✅ |
| Lobby | Countdown, prep checklist, join window, late-join rules | ✅ |
| Prerequisites screen | Tick items with how-to help, "Get help", optional mic check | ✅ |
| Live stage | Lip-synced companion, live captions, suggestion chips (Yes next, Not yet, Another example, Say it in Tamil, Done, I'm stuck), one big mic (tap or hands-free), typing | ✅ |
| Menu | Plan and transcript, raise hand, language (English or Tamil), hands-free switch, read replies aloud | ✅ |
| Stage rail | Learn, Do it yourself, Quick check, Build, Build your agent, Final | ✅ |
| Pace banner | On track, a little behind, grace period, over time; never blocks | ✅ |
| DIY help panel | Paste, drop or choose a screenshot up to 4 MB and/or an error log; one AI answer; screenshot never stored (200-character summary kept) | ✅ |
| Build task | Code, open answer or artifact check graded on the server; 5 tries per stage, best score, model solution | ✅ |
| Agent builder | Name, instructions, starter message; Aasan Tools (calculator, workshop notes, date and time, unit converter, word count); own remote MCP servers over https (token encrypted, never shown again); test chat with step trace and per-tool approval (Approve, Deny, Always allow); save | ✅ 🏫 external MCP |
| MCP server | Aasan Tools served as Streamable HTTP JSON-RPC at `POST /api/workshops/mcp/` with a per-session `awt_` token (24 h max, dies on submit) for use in the learner's own AI app | ✅ |
| Teacher nudges | "Message from your teacher" during institution runs | ✅ |
| Final assessment | MCQs plus a practical task, hidden agent tests, pass mark, up to 3 attempts, best score | ✅ |
| Result | Pass or fail, feedback, agent test results, certificate PDF and verify link | ✅ |

**Scheduling and oversight**

| Feature | Detail | Where | Status |
| --- | --- | --- | --- |
| Templates | Four launch workshops seeded (`seed_workshops`); proctoring mode per template | Admin → Workshops | ✅ |
| Public runs | Create from a template, IST start time, capacity, price ₹0 to 10,000, late join and lobby minutes; publish; announce to all users; cancel (flags refunds); stats | Admin → Workshops | ✅ |
| Test runs | Staff try any template privately | Admin → Workshops | ✅ |
| Institution runs | `workshops` is on for every org by default (only the platform admin can switch it off; an org cannot change it itself) and the platform admin sets monthly seats (0 until set, so nothing can be scheduled before then); org admins schedule free runs for classes and cohorts with proctoring (activity or strict full-screen) | Admin → Workshops → Organisations; cockpit Workshops tab | ✅ 🏫 |
| Live monitor | Faculty dashboard over `ws/workshop-runs/<run_id>/monitor/`: tiles with status filters (needs help, stuck, away, idle, overtime, grace, ready, engaged, DIY, finished, passed), raised hands, acknowledge, nudge up to 300 characters, learner timeline | `/org/:slug/workshops/:runId/live` | ✅ |
| Reports | PDF, PPTX and CSV per run; teachers see only their own classes | cockpit | ✅ |
| Status automation | scheduled → live → ended every 5 minutes; reminders; 7-day MCP token wipe; 90-day retention of transcripts and events | Celery beat | ✅ |
| Load check | `scripts/workshop_load.py` simulates \~100 learner sockets and prints monitor latency | repo | ✅ |

**Security model and limits**

- Everything a learner, error log, screenshot or external MCP server sends is fenced and defanged before any model sees it; no agent tool runs without the learner's approval.
- External MCP calls go through `safe_fetch`: https only, public IPs re-resolved and pinned, no redirects, 10-second and 256 KB caps, only the learner's own auth header forwarded.
- Attention signals only when proctoring is on, never during hands-on stages; there is no camera.
- Limits via settings: `WORKSHOP_SESSION_AI_UNITS` (400), `WORKSHOP_HELP_PER_HOUR` (20), `WORKSHOP_CAP_MULTIPLIER` (3), `WORKSHOP_AGENT_RUNS` (40), `WORKSHOP_EXTERNAL_MCP` (true), `WORKSHOP_EXTERNAL_PER_MIN` (30).

## 11. Creator Lab & Studio

Creators (granted by staff) author courses with AI, publish them by link or to the catalog, run guest campaigns and connect Claude to their organisation.

**Lab home** (`/lab`, `/api/lab/`, `/api/studio/`)

| Feature | Detail | Status |
| --- | --- | --- |
| New course | AI drafts the outline from a brief, audience notes and level, or start blank | ✅ |
| Templates | Reuse shared templates (mine, my org, everyone) | ✅ |
| Import | Pasted outline, JSON, YAML or file; activities re-validated | ✅ |
| Presets (saved pipelines) | Name, tone, level, language, lessons per section, activity mix, instructions | ✅ |
| Status badges | Draft, Shared by link, In review, In catalog, Needs changes; learner counts | ✅ |

**Course editor** (`/lab/:id`)

| Feature | Detail | Status |
| --- | --- | --- |
| Undo / redo | Full history with labels; Ctrl/⌘+Z and Shift+Ctrl/⌘+Z | ✅ |
| Named versions | Save, restore (undoable), delete | ✅ |
| Export | PowerPoint (answers in speaker notes), JSON, YAML; per-lesson slides PPTX | ✅ |
| Template sharing | Not a template, just me, my org, everyone (staff) | ✅ |
| Sources and style | House-style preset; up to 5 of my notes to ground generation; Research the web with cited sources | ✅ (web research ⚙️ model support) |
| Build with Kili | Plain-language change requests become proposed operations (rename, add, delete, write, generate, add activity); apply selected as one undo step | ✅ |
| Publish and share | Private, Link or Catalog (admin review with rejection notes); copy link; view as guest; reset share link | ✅ |
| Ratings strip | Average stars, difficulty split | ✅ |
| Outline | Sections and lessons: rename, move, archive (kept, hidden from learners), delete, add, reuse a lesson from my lessons or templates | ✅ |
| Lesson panel | Title, objective, generate or regenerate, Markdown text, key points (8), learner feedback, activities with live preview | ✅ |
| Images | Upload PNG/JPG/WebP up to 8 MB, generate with AI, "My images" library, alt text, "Illustrate with AI" | ✅ (AI images ⚙️) |
| Lecture video tool | Upload video or audio up to 50 MB or YouTube plus transcript; speech-to-text; AI segments with checkpoint questions; keep, trim or drop; add as video activities | ✅ ⚙️ STT |
| Activity editors | All 19 types; AI "Add with AI" with instructions; manual forms for video, hotspot, artifact check; Advanced JSON with validation | ✅ |
| Browser-task observation steps | 1 to 8 https URL patterns with optional text check; hosts the extension will watch; allow plain screenshots | ✅ |
| Interactive widget authoring | Create or regenerate the lesson widget with instructions | ✅ |
| Lab AI limit | Free plan 20 Lab AI calls per day | ✅ |

**Guest links and campaigns** (`/guests`, `/api/guests/`)

| Feature | Detail | Status |
| --- | --- | --- |
| Guest links | Label, target (course or role-play), custom slug, max guests, expiry, on/off, ask for name and email, org branding | ✅ |
| QR and stats | QR code; opens, started, finished, emails, signed up, conversion, daily chart; CSV export | ✅ |
| Claim progress | Guest progress moves into a new account | ✅ |
| Campaigns (org managers) | Prospects by paste or CSV (25 max); AI demo lesson and email per prospect in 10 languages; edit, send, send all, regenerate; daily cap; unsubscribe | ✅ |
| Guest AI pool | Shared daily AI units per link and per IP (`GUEST_AI_*` settings) | ✅ |

**Connect Claude** (`/connect`, `/connect/authorize`, `/api/connect/`, `POST /api/mcp`)

| Feature | Detail | Status |
| --- | --- | --- |
| OAuth 2.1 authorization server | Dynamic client registration (RFC 7591), PKCE S256 only, discovery via `/.well-known/oauth-*`, token rotation families, code reuse revokes the grant | ✅ |
| Consent screen | App name with unverified and "registered under a day ago" warnings, redirect host, capabilities, pick the organisation, Approve or Deny | ✅ |
| Remote MCP tools | org\_overview, list\_members, list\_assignments, assignment\_progress, list\_courses, get\_course\_outline, list\_surveys, survey\_results, create\_guest\_lesson (charged to the admin's AI allowance) | ✅ |
| Connected assistants | Approved by, connected on, last used, tool-call counts, disconnect; paged activity log | ✅ |
| Privacy | No emails or user ids in results; surveys aggregated; admin status re-checked on every call | ✅ |

## 12. Certificates & sharing

Certificates are issued automatically on completion or by an organisation, rendered as PDF with Tamil-capable fonts, and verifiable by anyone.

| Feature | Detail | Where | Status |
| --- | --- | --- | --- |
| Kinds | Course, role-play, knowledge test, workshop | `/certificates` | ✅ |
| Automatic issue | On course completion at `CERT_PASS_SCORE` (default 0.6); adaptive learners also need critical concepts mastered | credentials | ✅ |
| PDF | reportlab with Noto fonts for Tamil and Indic names; every value escaped | `GET /api/credentials/<id>/pdf/` | ✅ |
| Public verification | Name, what was completed, issuer, date, ID; hidden or revoked shows "not found"; throttled 120/h | `/verify/:code` | ✅ |
| Learner controls | Show publicly or hide; revoke (permanent); copy or open verify link | `/certificates` | ✅ |
| Organisation issuing | Pick a member, issue for finished assigned courses, role-plays and passed named tests; blocked if the name contains "Aasan" | cockpit → Certificates | ✅ |
| Template designer | Layout, colours, wording, logo, signature, per kind and language, live PDF preview; platform-wide (staff) or per organisation | Admin → Certificates; cockpit → Settings | ✅ |
| Admin controls | Search and filter every certificate, revoke, refresh the learner's name, CSV export | Admin → Certificates | ✅ |
| Share your progress | AI-written "Note to my manager" or "LinkedIn post" from real numbers only; editable; share image drawn in the browser | `/certificates`, `/progress/review` | ✅ |

## 13. Organisations

Schools, colleges, coaching centres and companies get a teacher cockpit with classes, assignments, analytics, surveys, certificates, onboarding journeys and institution workshops. Roles rank owner > admin > manager/teacher > learner, with scoped unit admins.

**Joining and learner side** (`/orgs`, `/surveys`, `/api/orgs/`)

| Feature | Detail | Status |
| --- | --- | --- |
| Create an organisation | Name and type (School, College, Coaching, Company) | ✅ |
| Join | Class code, email invite link, campaign link, referral link; wrong-account and expired errors | ✅ |
| Learner surveys | Stars, scale, NPS, one or several choices, text, grid; autosaved drafts; knowledge tests with score, pass mark, review, attempts, cooldown | ✅ |
| Member fields prompt | Fill in missing org-defined fields | ✅ |
| Org branding | Logo, colour and name in the sidebar and guest pages | ✅ |
| Shared notes | Org documents readable by learners | ✅ |
| Privacy promise | Teachers see assigned-course progress only, never chats or notes | ✅ |

**Teacher cockpit tabs** (`/org/:slug`)

| Tab | Features | Status |
| --- | --- | --- |
| Overview | Set-up checklist (brand, fields, classes, invite, assign, DPA); KPIs; AI "Analyse my class" insights; Excel export; charts (active learners, XP, mastery, completion); Needs attention list with multi-select nudge | ✅ |
| Classes | Add class, copy join link, rotate code; "This week's top learners" per class (top 10 by XP, learners who hid themselves counted, not shown) | ✅ |
| Members | Invite by email with role; unsent invites when SMTP is off; pending invites with revoke; filter by field; inline field edit; seat badge; change role within your rank | ✅ |
| Assignments | Assign course or role-play to a class or everyone with due date, mandatory flag, note, end-of-training survey; progress; lesson drill-down with every learner's answers and teacher-only answer keys; Find misconceptions with re-teach tips; role-play analytics with attempt history and AI insights; role-play competency funnel and heat-map with stuck-learner threshold; CSV and Excel | ✅ |
| Certificates | Issue to a member for finished work; issued list | ✅ |
| Surveys | From template, Build your own, Write with Kili (multi-turn), Draft from a document; survey or knowledge test (pass mark, show answers, attempts, cooldown); random draw from question banks; public link; open, close, clone, delete; results with per-question charts, NPS bar, test stats, AI comment summary (3+ answers), CSV and Excel | ✅ |
| Competency | Target role heat-map of each learner's level 0 to 4 per required skill | ✅ |
| Pilot report | Date range; activation, sustained use, completion, learning gain, would recommend; weekly charts; PDF and PPTX | ✅ |
| Settings | Branding; About the organisation; member fields (text or select; editable, read-only, hidden); feature switches (Ask Aasan, Live Class, Role-play, Leaderboard, Wardrobe shop, external MCP); shared notes; certificate design | ✅ |
| Growth | Joining campaigns with quota and end date plus CSV email invites; referral programme with codes, rewards, payout ledger (approve, reject, mark paid) | ✅ |
| Seats | Plan, used/total, until; buy seats via Razorpay; give free seats; prepaid codes; invoices | ✅ |
| Units | Nested sub-schools or departments with description, target roles, courses in scope, classes, unit admins; per-unit assignments and learners | ✅ |
| Knowledge | Company knowledge base: PDF, DOCX, TXT, MD up to 10 MB, 50 documents; learners-can-read or staff-only; AI topic map | ✅ |
| Cohorts | Partner programmes with name, partner, dates, courses, members; upcoming, active, ended | ✅ |
| Set up with Kili | Chat proposes setup operations (description, classes, units, roles, toggles, course ideas); apply selected | ✅ |
| Workshops | Monthly seat quota; schedule template runs for classes or cohorts with proctoring and lobby settings; upcoming and past runs; live dashboard; reports | ✅ 🏫 on by default; platform admin only can switch off |
| DPA | Admins accept the Data Processing Agreement; banner until done | ✅ |

**Onboarding journeys** (`/org/:slug/journeys`, `/api/journeys/`)

| Feature | Detail | Status |
| --- | --- | --- |
| Journey builder | Name, length in days, phases, day-by-day items (lesson or course, role-play, shadow a colleague, document, HR note) | ✅ |
| Draft with AI | Role, company, days; accept or skip each item | ✅ |
| Assign and track | Start date, class or individuals; progress with day, done, overdue, phase, stuck or on track; CSV | ✅ |
| Duplicate and delete | Reuse journeys | ✅ |

**Company integrations and compliance** (`/org/:slug`, `/api/orgs/<slug>/…`, `/api/v1/`)

| Feature | Detail | Status |
| --- | --- | --- |
| Training records | Append-only compliance record per learner and finished item (assigned course, assigned role-play, organisation workshop, passed knowledge test): organisation, learner name and email snapshot, title, assigned, started, completed, score, estimated minutes, certificate code and verify link. CSV, Excel and PDF from the Assignments and Certificates tabs (teachers get their classes only); learners see and download their own on `/account`; names anonymised when an account is deleted; `manage.py backfill_training_records` (idempotent) | ✅ |
| API keys | Cockpit → Integrations (owners and admins): up to 10 keys per organisation with scopes `read:progress`, `read:members`, `write:members`; the raw key is shown once and stored as a SHA-256 hash with an 11-character prefix for lists; revoke; last used. `/api/v1/orgs/<slug>/` members (list, invite learners, remove learners), assignments and per-learner progress, certificates, training records, each paged with CSV export; a per-key throttle (`API_KEY_RATE`, 600/h) | ✅ |
| Ask about my organisation | Cockpit Overview, under AI insights: a plain-language question ("Which class is behind?") becomes one query from a fixed catalog (completion by class or assignment, learners needing attention by class, active learners per day or week, mastery by skill or class, overdue by assignment or class, workshop pass rate); the AI never writes queries, class and assignment ids are checked against the organisation and the teacher's classes, the question is fenced; answers are a chart plus a first-name table; daily AI budget and 60/h | ✅ |
| Enterprise SSO | Cockpit → Settings (admins): Google Workspace or Microsoft Entra ID client, write-only secret, email domains proved with a DNS TXT record (`aasan-verify=…` at the domain or `_aasan.<domain>`; free mailbox providers refused; one organisation per verified domain), default role and class, on/off, Require SSO (owners only, with confirm); daily DNS re-check un-verifies after 7 failing days; platform support can switch it off from the admin console | ✅ |
| Webhooks | Up to 10 HTTPS endpoints per organisation for `member.joined`, `assignment.completed`, `course.completed`, `certificate.issued`, `workshop.passed`; HMAC-SHA256 signature over `timestamp.body` with a secret shown once (rotate any time); 5 tries with backoff, delivery log with redeliver, test ping (10/h); switched off after 20 dead deliveries in a row with admins told; payloads carry first names only | ✅ |

**Other organisation capabilities**

- Competency heat-map and AI org insights over the API (`/api/orgs/<slug>/competencies/`, `.../insights/`).
- Excel exports for analytics and surveys (`/api/studio/exports/orgs/<slug>/...`).
- CSV exports are formula-injection safe; invite emails have an allowance; join and public-survey endpoints are throttled.
- A demo organisation can be seeded with `manage.py seed_sample_org`.

## 14. Billing & plans

Razorpay handles one-time plans, auto-renew subscriptions, organisation seats and refunds; the server issues GST invoices and reconciles missed webhooks every 10 minutes.

**Learner side** (`/plans`, `/api/billing/`)

| Feature | Detail | Status |
| --- | --- | --- |
| Free plan limits | 2 AI courses per 30 days, 30 mentor messages per day, 3 documents, 10 voice minutes per day, 5,000 read-aloud characters per day, 10 live minutes per day, 20 Lab AI calls per day | ✅ |
| Usage meters | Every limit shown live; plan-limit sheet with "See plans" when a limit is hit | ✅ |
| Plan cards | Price including GST per N days, badge, limits; pay once or auto-renew (monthly, yearly, every N days); upgrade or add more time | ✅ |
| Checkout | Razorpay quote, order, verify, failed flows; test-mode banner with test card and UPI | ✅ ⚙️ keys |
| Subscriptions | Status, next charge, payment method, grace period, cancel auto-renew, resume | ✅ |
| Promo codes | Apply at checkout with per-plan quotes; guessing throttled | ✅ |
| Prepaid redeem codes | School or partner codes grant a plan | ✅ |
| GST invoices | 18% inclusive, CGST+SGST or IGST, numbered per financial year; business name and state; PDF download | ✅ |
| Payment history | Orders with invoice PDFs | ✅ |
| Organisation seats | Buy seats, assign seats, redeem codes, invoices | ✅ |
| Plan reminders | Email before and when a paid plan ends (family plans: the owner only) | ✅ |
| Family plan | A family plan is shared with up to N people in all (owner included). The owner invites by email; the invite link (24-byte token) and 6-character code are stored only as hashes, expire in 7 days and only work for the invited, verified email. Members get the owner's plan and limits for as long as the owner's paid time runs (renewals, grace days and refunds follow automatically); one family per person; a school seat on the same or a better plan wins; the highest-priced plan applies when windows overlap. Owners remove members or stop sharing; members leave from Plans or Account | ✅ ⚙️ keys + a family plan in Admin → Payments |
| Family invite page | `/family/<token>`: who invited you and to which plan; join with one click, or enter the code on Plans | ✅ |
| Gift a plan | "Gift this plan" on any paid plan: recipient email and a short message, paid once (never auto-renew; not for organisation seats or yourself). On payment the recipient is emailed a one-time code valid for a year with a `/plans?code=` link; redeeming it gives them the plan and tells the buyer. The buyer gets the GST invoice ("Gift: plan") and sees the gift in payment history (and the code, if the email couldn't be sent) | ✅ ⚙️ keys |
| Plan-lapse comeback offer | A paid plan that ended 3 to 10 days ago with no renewal, auto-renew, school seat or other plan gets one email with the active win-back promo code (Admin → Codes, "Use: Win-back email"), at most once per 180 days; the code is never put in push or the bell | ✅ |

**Back office**

| Feature | Detail | Where | Status |
| --- | --- | --- | --- |
| Razorpay config | Keys encrypted; live keys refused until "Allow live payments"; test connection; webhook secret and URL | Admin → Payments | ✅ |
| Webhook | `POST /api/billing/webhook/` with HMAC check; duplicate events ignored; payment, order, refund and subscription events | API | ✅ |
| Reconciliation | Grants anything captured that the webhook missed, every 10 minutes | Celery beat | ✅ |
| Plans editor | Name, on sale, price, days, badge, description, Razorpay plan id, limits; family plan switch with people in all (2–20, paid plans only); add a new plan | Admin → Payments | ✅ |
| Families & gifts | Every family group (owner, plan, members, pending invites, active until) for finance and support; gifted plans (buyer, recipient, status, code end) for finance; search and CSV export | Admin → Families & gifts | ✅ |
| Gift refunds | Refused once the gift code is redeemed; before that the refund voids the code (restored if the gateway call fails) | Admin → Refunds | ✅ |
| Manual grant | Free access by email with plan, days, note | Admin → Payments | ✅ |
| Refunds | Full or partial through Razorpay, optionally ending access; history | Admin → Refunds | ✅ |
| Codes | Promo codes (discount, plans, expiry, per-person limit) and redeem-code batches | Admin → Codes | ✅ |
| Overview money | Revenue, AI spend, MRR, churn, refunds; family plans (monthly value of one-time family orders, families, members); paying users exclude family members | Admin → Overview | ✅ |
| Row locking | `SELECT FOR UPDATE of=self` on entitlement grants, the family group while its members' access is rewritten, and gift codes at redeem and refund (Postgres) | API | ✅ |

## 15. Admin console

Staff see `/admin/*` sections by role; every non-GET admin request is written to an audit log with secrets masked. Lists page at 50 rows and export up to 5,000 rows as CSV with `?export=csv`.

**Roles** (`apps/accounts/staff.py`; a section missing from the table is superadmin-only; staff without a role row are superadmins)

| Section | superadmin | support | finance | content |
| --- | --- | --- | --- | --- |
| Overview | ✅ | ✅ | ✅ | ✅ |
| Model prices | ✅ |  | ✅ |  |
| Users | ✅ | ✅ | ✅ |  |
| Organisations | ✅ | ✅ | ✅ |  |
| Catalog | ✅ |  |  | ✅ |
| Creators | ✅ | ✅ |  | ✅ |
| Certificates | ✅ | ✅ |  | ✅ |
| Certificate templates | ✅ |  |  | ✅ |
| Workshops | ✅ |  |  | ✅ |
| Workshops: organisations | ✅ | ✅ |  |  |
| Payments, plans, promos, redeem codes, invoices, refunds | ✅ |  | ✅ |  |
| Reports (support inbox) | ✅ | ✅ |  |  |
| Help articles | ✅ | ✅ |  | ✅ |
| System check, providers, site, mail, calendar apps, staff, audit | ✅ |  |  |  |

**Sections** (`/admin/<section>`, `/api/admin/<section>/`)

| Section | Features | Status |
| --- | --- | --- |
| Overview | Learners, platform, learning and money metrics; AI usage by model (calls, tokens, cost); editable model prices in ₹ per 1M tokens; Excel export | ✅ |
| Users | Search by email, name or organisation; filters staff, creator, inactive, unverified, minor, paying; detail with plans, orgs, courses, certificates, AI use, devices; actions: verify email, sign out everywhere, deactivate, reactivate, grant or revoke creator | ✅ |
| Organisations | Members, seats used vs paid, paying status, workshop seats and learners per month; suspend with reason or lift | ✅ |
| Catalog | Grant or revoke Creator Lab access; review queue with approve or request changes | ✅ |
| Certificates | Search and filter, revoke, refresh name, platform template designer | ✅ |
| Workshops | Templates with proctoring mode and test run; scheduled runs (create, edit, publish, announce, cancel, stats); institution enablement and monthly seat cap | ✅ |
| Payments | Razorpay keys and mode, allow live, test, webhook; plans editor; grant free access; subscriptions table; payments with revenue, paid and failed totals | ✅ |
| Refunds | Find a paid order; full or partial refund; end access; history | ✅ |
| Codes | Promo codes; prepaid redeem-code batches; GST invoice list | ✅ |
| Support | Problem-report inbox with status and emailed reply; help-centre article editor in English and Tamil | ✅ |
| System | Pre-launch system check (keys, email, legal, HTTPS/HSTS, Sentry, leftover demo accounts) and an end-to-end validation checklist | ✅ |
| Providers | Per capability (tutor, utility, STT, TTS, vision, image, embedding): provider, model, voices, API key (masked `••••last4`, Fernet-encrypted), remove, test with default, English voice, Tamil voice, mic | ✅ |
| Calendar apps | Google and Microsoft OAuth client setup with redirect URI and read-only scopes | ✅ |
| Email | SMTP host, port, STARTTLS/SSL, credentials, from address; send a test email with the exact SMTP error | ✅ |
| Site | Brand, registered name and address, GSTIN, state, SAC code, jurisdiction, support contacts, grievance officer, refund window; drives legal pages and invoices | ✅ |
| Staff | Add or remove staff roles by email; searchable audit log (when, who, section, action, target, result, IP) | ✅ |
| Django admin | Stock Django admin at `DJANGO_ADMIN_PATH` (default `api/django-admin/`), sharing the login lockout | ✅ |

**Management commands**: `setup_env`, `check_llm`, `make_admin <email> --role`, `make_creator <email> [--revoke]`, `seed_demo [--full]`, `seed_sample_org`, `seed_workshops`, `seed_load_users`, `send_study_reminders`, `send_plan_reminders`, `clean_media [--dry-run]`, `translate_ui --langs`.

## 16. Browser extension: Aasan Companion

A Manifest V3 extension (version 0.2.0, Chrome 116+ and Edge, plain JavaScript, no remote code) that pairs with an account and proves "Do it and show" tasks from the learner's own browser.

| Feature | Detail | Endpoint | Status |
| --- | --- | --- | --- |
| Pairing | Account page issues a 6-digit code (single use, 10 minutes); the popup claims it for a device token stored locally and sent as `Authorization: AasanExt`; server keeps only the SHA-256 hash | `/api/ext/pair/start/`, `/api/ext/pair/claim/` | ✅ |
| Device list | Connected browsers listed and removable from Account | `/api/ext/devices/` | ✅ |
| Task list | Open browser tasks with course, lesson, last score, prompt, steps and the proof the screenshot must show; buttons: I've done it, Open site, Lesson, Watch steps | `/api/ext/tasks/` | ✅ |
| Toolbar badge | Count of tasks matching the current tab's host or URL pattern | local | ✅ |
| One-click proof | Captures the visible tab as JPEG under 2 MB and submits with URL and title; AI grades, screenshot not stored; result shows score, pass or fail, feedback | `/api/ext/tasks/<id>/submit/` | ✅ |
| Live step observation | For 1 to 8 authored steps: requests host permission for exactly those hosts, opens a side panel, ticks steps as URLs match https globs and optional text checks pass, then "Send for marking"; permissions removed on stop, disconnect, pass or task switch | side panel | ✅ |
| Server rules | `422 steps_required` and `422 wrong_site`; observed URLs re-checked before AI grading; public suffixes refused in patterns | API | ✅ |
| Settings | Change the server address (https or localhost); saving disconnects | popup | ✅ |
| Disconnect | Revokes the token server-side and forgets it locally | `/api/ext/disconnect/` | ✅ |
| Limits | Pair 10/h, claim 10/h, submit 60/h; same AI budget as the web | API | ✅ |
| Packaging | `extension/package.sh <server>` bakes the server origin and writes a store zip; icons regenerated by `icons/make_icons.py` | repo | ✅ |
| Tests | `node --test extension/test/*.test.js`; public-suffix list kept identical to the API copy | CI | ✅ |

## 17. Voice, languages, accessibility & platform UX

Voice runs in the browser or through server-side providers; the interface ships in 9 languages with Tamil first; the app installs as a PWA and works offline for saved lessons.

**Voice** (`web/src/voice/`, `/api/voice/`)

| Feature | Detail | Status |
| --- | --- | --- |
| Speech-to-text | Browser Web Speech, or a server engine (Sarvam saarika, Deepgram nova-3/nova-2, Google, OpenAI transcribe/whisper); `en-IN` and `ta-IN`; charged by clip size | ✅ (server ⚙️) |
| Text-to-speech | Server voices (Sarvam bulbul with Tamil and English speakers, Deepgram aura-2, Google Wavenet/Neural2, OpenAI tts) with lip-sync, falling back to browser `speechSynthesis` | ✅ (server ⚙️) |
| Voice modes | `conversation` (Ask Aasan voice screen, Live Class, role-play, hands-free workshops: talk any time with Deepgram, otherwise listening pauses while the AI talks; an echo tail drops the AI's own last words heard late), `tap` (tap to talk, auto-send on silence), `handsfree` (listening pauses while the reply plays) | ✅ |
| Live voice call | Self-hosted LiveKit (WebRTC) with Aasan's voice agent: Sarvam streaming listening (Tamil and English), Silero VAD + turn detector, Sarvam streaming voice; talk any time and Aasan stops at once; echo cancelled by the browser; Claude still writes the answers through each screen's own socket. On Ask Aasan, Live Class, Role-play and hands-free workshops; falls back to the browser/Deepgram voice when LiveKit isn't running | ✅ (`--profile voice`, Sarvam key ⚙️) |
| Echo check | Fuzzy (letter-pair similarity, merged or split words, Unicode-normalised) so Tamil echo is caught even when the recogniser spells it differently; wake words (Aasan, stop, wait, நிறுத்து) always cut in | ✅ |
| Voice activity detection | Energy-based start/end/cancel with an echo guard | ✅ |
| Narrator | Part-by-part narration with true ±10 s seeking on server voices; per-host voices and pitch for podcasts; Tanglish uses a Tamil voice | ✅ |
| Tamil-aware TTS | Sentence splitter picks a Tamil voice when it sees Tamil script | ✅ |
| iOS/Safari | Audio unlock on first tap | ✅ |
| Daily budgets | STT 1,800 s, TTS 60,000 characters, 600 vision frames, 30 images per user per day; 429 when exceeded | ✅ |

**Languages**

| Feature | Detail | Status |
| --- | --- | --- |
| Interface languages | English, Tamil (hand-written); Hindi, Telugu, Kannada, Malayalam, Bengali, Marathi, Gujarati (machine-translated beta via `translate_ui`, loaded on demand) | ✅ |
| Language pickers | Auth pages, onboarding, Personalize; stored in the profile and `localStorage`; sets `<html lang>` | ✅ |
| Content languages | Courses in English, Tamil, Tanglish; lesson "Read in" into 10 options; mentor reply language Auto/EN/TA/Tanglish; workshops EN or TA; guest campaign lessons in 10 languages | ✅ |
| Companion names | Default names shown in Tamil script for Tamil readers; `{{mascot}}` placeholder in every string | ✅ |
| Locale | Dates and numbers in `<lang>-IN` | ✅ |
| Help centre | Articles in English and Tamil | ✅ |

**Installable app and offline**

| Feature | Detail | Status |
| --- | --- | --- |
| PWA manifest | Standalone portrait app with maskable icons and shortcuts to Ask Aasan and Review; iOS meta tags | ✅ |
| Service worker | Caches the app shell and offline page; network-first for `me`, course list, course, lesson, game status; never sockets, payments or uploads | ✅ (production only) |
| Save course for offline | Pre-fetches ready lessons and the Lesson page code | ✅ |
| Offline queue | Answers and lesson completions deduplicated and flushed on reconnect; banner shows queued count | ✅ |
| Shared devices | Offline data cleared on logout | ✅ |

**Themes, accessibility, mobile and shortcuts**

| Feature | Detail | Status |
| --- | --- | --- |
| Themes | Light, Dark, Kolam, Temple, Ocean, Night study; accent colour; org brand colour and logo | ✅ (no automatic dark mode) |
| Fonts and size | Mukta Malar, Noto Sans Tamil, Catamaran, Atkinson Hyperlegible; text size 80 to 160% | ✅ |
| Reduced motion | Disables animations and confetti | ✅ |
| ARIA | About 240 live regions; roles for tabs, menus, dialogs, progress, timers; labelled icon buttons; focus management; Escape closes | ✅ |
| Known gap | No skip-to-content link | 🚧 |
| Mobile | Bottom tab bar with safe-area inset, section tab rows, `dvh` layouts, camera flip, workshop bottom sheets, admin icon bar | ✅ |
| Keyboard shortcuts | Ctrl/⌘+Z undo and redo in the editor; Enter/Shift+Enter in chats; Escape in tours, menus, dialogs; arrows in course reorder and admin tabs; Tab in the code editor; Ctrl+V screenshot paste | ✅ |
| Guided tours | App, Creator Lab, Teacher cockpit, Admin console; spotlight, auto-start once, replay from Help | ✅ |
| Dialogs and states | App-styled confirm, prompt, alert with danger style; not-found and error-with-retry pages | ✅ |
| Downloads | Excel, CSV, PDF, PPTX, ICS through one helper | ✅ |
| Print styles | Quarterly review and 30-day career plan | ✅ |

## 18. Platform, security & operations

One LLM router meters every call, every untrusted string is fenced before a prompt, outbound fetches are pinned to public IPs, and the production stack runs on docker-compose behind nginx with health probes on every service.

**LLM layer** (`api/llm/`)

| Feature | Detail | Status |
| --- | --- | --- |
| Router | Resolves a task to provider and model: `LLM_FORCE_PROVIDER` → admin console config → `.env`; a new client per call; every call metered to `LLMUsage` | ✅ |
| Providers | Anthropic (default: claude-sonnet-5-5 tutor, claude-haiku-5-5 utility), OpenAI (gpt-5, gpt-5-mini, gpt-5-nano), Gemini (2.5 pro, flash, flash-lite), fake (canned Tamil tutor for tests and load tests) | ✅ ⚙️ |
| Capabilities | tutor, utility, stt, tts, image (gpt-image-1, imagen-4), embedding (text-embedding-3, text-embedding-004), vision | ✅ |
| Task routing | tutor, author, adaptive\_graph → tutor; grade, suggest, onboarding, adaptive\_interview, org\_ask → utility; per-task overrides `LLM_ROUTE_<TASK>` | ✅ |
| Structured output | JSON-schema completions with Pydantic | ✅ |
| Web research | Anthropic web\_search, OpenAI Responses web\_search, Gemini Search grounding; live search in mentor chat, Ask Aasan voice, Lesson Ask, Documents, Live Class, role-play (in character) and workshops (never exercise answers); India date for "today"; daily per-learner cap; sources shown under replies | ✅ ⚙️ |
| Guardrails | Input screening (secrets masked, crisis note), output filter (no model-written links or images), shared guardrail prompt, red-team set `manage.py check_guardrails` | ✅ |
| Failover and spend | `LLM_FALLBACK` provider with a circuit breaker; monthly AI spend alerts at 50/80/95% of `LLM_MONTHLY_BUDGET` | ✅ ⚙️ |
| Prompt modules | adaptive, connect, credentials, curriculum, guests, journey, journeys, live, lx, orgs, paths, roleplay, studio, study, teach, tutor, workshop | ✅ |
| DB handback | Connection returned before slow AI calls | ✅ |

**Security controls**

| Control | Detail |
| --- | --- |
| Prompt fencing | `fence(tag, text)` and `defang()` on every learner, document, screenshot, error log or external-tool string |
| SSRF guard | `safe_fetch`: https only, DNS resolved and public IP pinned, no redirects for POST, 5 s / 1 MB (10 s / 256 KB for MCP), HTML only, no cookies |
| Formula and CSV safety | `safe_math` whitelist for visualisations; `csvsafe` on every export |
| Secrets | Fernet/MultiFernet with `AASAN_SECRETS_KEY` and rotation; provider, Razorpay, SMTP, calendar and MCP tokens encrypted; API shows last 4 only |
| Tokens | Extension, OAuth and guest tokens stored as hashes; JWT refresh in HttpOnly cookie with blacklist |
| Organisation SSO | Provider issuer, authorisation, token and JWKS URLs are constants (Microsoft: tenant UUID only); PKCE S256, single-use `state` (10 min) and `nonce`; fixed redirect `FRONTEND_URL/sso/callback`; ID token signature, audience, issuer, expiry and nonce checked; Google `email_verified` + `hd`, Microsoft `tid`; email domain must be a verified hosted domain; client secret encrypted and never returned; enforcement with owner break-glass |
| Organisation API keys | SHA-256 hashed, prefix shown, scoped, bound to one organisation, refused when revoked or the organisation is suspended; only API-key auth on `/api/v1/` (user JWTs refused) and keys refused on every JWT route; per-key throttle |
| Outbound webhooks | URL vetted at save and on every delivery through `safe_fetch` (https only, public DNS answers only, IP pinned, no redirects, 10 s, 256 KB), never our own host; HMAC-SHA256 over `f"{ts}.{body}"`; secrets encrypted; a refused URL is dead at once; auto-disable at 20 dead in a row; no emails in payloads; delivery log kept `WEBHOOK_RETENTION_DAYS` (30) |
| Widgets | AI-written widgets in `iframe sandbox="allow-scripts"` with signed token and strict CSP |
| Throttles | Auth 20/min, join 10/h, extension pair 10/h and submit 60/h, Lab guest 300/h read and 60/h attempt, CV 10/h, docs 20/h, public survey 60/h, guardian 60/h, support ask 30/h and report 10/h, connect register 10/h and 30/day, billing subscribe 20/h and quote 30/h, calsync 20/h and 30/h, verify 120/h, guests per IP 300/20/200/60/5 per hour, workshops checkout 30/h |
| Lockouts and caps | 10 failed logins lock 15 minutes; 5 verification and 5 reset mails per day; nginx 30/min on sign-in routes; lockouts, OTP tries and mail caps kept in a never-evicting Redis with atomic counters |
| Passwords and staff | Passwords found in public breaches refused (Have I Been Pwned, k-anonymity, fails open); staff without a role get no access; admin changes need a passkey or emailed code within 30 minutes |
| Admin | Roles per section, `AdminAudit` middleware on every mutation, superadmin-only provider and secret config |
| Media | Images re-encoded, EXIF and GPS stripped, unguessable names; lecture video with Range; screenshots never stored |
| Privacy | Account deletion with OTP; data export; guardian sees progress only; Sentry sends no personal data; workshop retention 90 days; MCP tokens wiped on submit or after 7 days; nightly retention: mentor chats idle 12 months, role-play transcripts 12 months, AI usage ~13 months, speech clips 6 months (`*_RETENTION_DAYS`) |
| Production hardening | HSTS, SSL redirect, secure cookies, nosniff, CORS and CSRF limited to `FRONTEND_URL`, proxy-aware client IP, non-root containers, `check --deploy` in CI; a public site refuses to start with unsafe settings (LiveKit dev keys, http, short keys, no `SENTRY_DSN`, a readable `api/.env`); any setting can come from a file (`NAME_FILE`); self-hosted Pyodide, no `unsafe-eval` |

**Operations**

| Area | Detail | Status |
| --- | --- | --- |
| Services | Postgres 16 (tuned), Redis broker and channels, Redis cache (LRU), Mailpit, one-shot migrate, API (gunicorn + uvicorn, daphne fallback), Celery worker, Celery beat, nginx web; health checks on all | ✅ |
| Health probes | `/api/health/` liveness; `/api/health/ready/` checks DB, cache and channel layer | ✅ |
| nginx | Auth rate limit, 300 s AI timeout, 12 MB default and 55 MB lecture uploads, widget iframe CSP, OAuth well-known proxy, direct media with Range, WebSocket 1 h idle, immutable assets, no-cache PWA files, strict CSP with no eval (Razorpay, YouTube, Google Fonts, OSM tiles; self-hosted Pyodide runner frame has its own CSP), HSTS 1 year | ✅ |
| TLS | Not in compose; Caddy or a load balancer in front, then `DJANGO_SECURE_SSL_REDIRECT` and `DJANGO_NUM_PROXIES` | ⚙️ operator |
| Backups | `infra/backup.sh` nightly `pg_dump` plus media tar, age-encrypted, sha256 manifest, required off-server copy, 14-day local retention; `infra/restore.sh` (`--drill`); optional WAL-G PITR overlay `infra/docker-compose.pitr.yml` | ✅ |
| Email | Admin-configured SMTP wins over `.env`; Mailpit locally | ✅ ⚙️ |
| Monitoring | Sentry via `SENTRY_DSN` (required on a public site); JSON logs with request id; slow-request log over `SLOW_REQUEST_MS`; `/api/metrics/` (Prometheus, token-protected); optional overlay `infra/docker-compose.monitoring.yml` (Prometheus, Alertmanager, Grafana, Loki 90-day logs) with alerts for queues, task failures, disk, Redis, DB connections, AI errors and webhooks | ✅ ⚙️ |
| Live voice capacity | `VOICE_LIVE_MAX_CALLS` per host (default 12); over it voice falls back to streamed listening; one call per user, 30-minute cap | ✅ |
| Background jobs | Celery with `acks_late`, prefetch 1, 900/960 s limits, child recycling; `LEARNING_JOBS_INLINE` for tests | ✅ |
| Scaling knobs | `WEB_CONCURRENCY`, DB pool sizes and statement timeouts, Celery concurrency, Postgres and Redis memory, WebSocket ping | ✅ |
| Load testing | `scripts/load_test.py` (HTTP + sockets, p50/p95/p99, exits 1 over error limit) and `scripts/workshop_load.py`; 500 concurrent users with 0 errors and p95 under 50 ms recorded in DEPLOY.md | ✅ |
| CI | api (ruff, migrations check, `check --deploy`, pytest with coverage, pip-audit), api-postgres, web (lint, test, build with tsc, audit), docker (build, `nginx -t`, non-root), extension tests; gitleaks, bandit, Trivy HIGH, SBOM, 90% coverage floor; release images to GHCR on a tag and a staging overlay; no automatic production deploy | ✅ |
| Help centre | Articles, BM25 search, Ask Help answering only from articles with citations, problem reports with page and browser attached | ✅ |

## 19. Reference

This section is the completeness check: every web route, API prefix and endpoint group, WebSocket, scheduled job, command and setting in the codebase as of 19 October 2026.

**Web routes** (`web/src/App.tsx`)

| Area | Routes |
| --- | --- |
| Public | `/login`, `/signup`, `/forgot-password`, `/reset-password`, `/verify-email`, `/s/:token`, `/g/:slug`, `/g/:slug/lesson/:id`, `/g/:slug/role-play`, `/g/:slug/done`, `/p/:token`, `/verify/:code`, `/guardian/:token`, `/unsubscribe`, `/privacy`, `/terms`, `/refunds`, `/contact`, `/dpa` |
| Home | `/`, `/today`, `/plan`, `/onboarding`, `/personalize`, `/account`, `/plans`, `/help`, `/help/:slug` |
| Learn | `/learn`, `/learn/:id`, `/learn/:courseId/lesson/:lessonId`, `/learn/:courseId/lesson/:lessonId/practice`, `/learn/:courseId/boss/:sectionId`, `/catalog`, `/documents`, `/documents/:id`, `/paths`, `/paths/:slug`, `/careers`, `/careers/:slug`, `/careers/:slug/plan/print`, `/journey` |
| Practice | `/mentor`, `/mentor/:id`, `/roleplay`, `/roleplay/:id`, `/live`, `/live/:id`, `/workshops`, `/workshops/:runId`, `/workshops/:runId/lobby`, `/workshops/session/:id`, `/workshops/session/:id/result` |
| Progress | `/progress`, `/progress/review`, `/checkpoints`, `/review`, `/mastery`, `/mastery/:id`, `/skills`, `/achievements`, `/leaderboard`, `/shop`, `/certificates` |
| Planner extras | `/buddy/:token`, `/calendar/callback/:provider` |
| Creator | `/lab`, `/lab/:id`, `/guests`, `/connect`, `/connect/authorize` |
| Organisations | `/orgs`, `/org/:slug`, `/org/:slug/journeys`, `/org/:slug/workshops/:runId/live`, `/surveys`, `/join/:code`, `/invite/:token`, `/join/c/:token`, `/join/r/:code` |
| Admin | `/admin/overview`, `users`, `orgs`, `catalog`, `certificates`, `workshops`, `payments`, `refunds`, `codes`, `support`, `system`, `providers`, `calendar-apps`, `email`, `site`, `staff` |

**API prefixes and endpoint groups** (`api/config/urls.py` → `apps/<app>/urls.py`)

| Prefix | App | Endpoint groups |
| --- | --- | --- |
| `/api/users/` | accounts | register, login, refresh-token, logout, google, me, profile, preferences, guardian, unsubscribe, email-verification request/confirm, password-reset request/verify-otp/confirm, passkeys list/rename/delete, passkey register and authenticate begin/complete, reauth, push (status with reminder back-off and learned time, subscriptions, test, opened, reminders/resume) |
| `/api/guardian/<token>/` | accounts | view, stop |
| `/api/assistant/` | mentor | conversations, conversations/\<id>, feedback/\<kind>/\<id> |
| `/api/learn/` | learning | curriculums (list/create/detail/retry/reset/edit/add-section/hidden/sources/reorder/undo/redo), subsections (detail/start/complete/practice/feedback/widget/widget-check/tutor/tutor-reply), widgets/\<id>/frame, activities/\<id>/attempt, activities/\<id>/roleplay, match-choice, continue |
| `/api/lab/`, `/api/catalog/`, `/api/share/` | learning | courses, sections, subsections (generate, video-questions, activities), activities, publish, share rotate; catalog; share/\<token> enroll, lesson, attempt |
| `/api/adaptive/` | adaptive | goals, goals/\<id>, choose, constraints, courses/\<id>/path, skill-map |
| `/api/study/` | study | hints, explain, today (focus/swap/done/circuit), revision-board, blocks, pauses, buddies, buddy/\<token>, progress (insights/ask), lessons/\<id> (explainer/podcast/listened/fast-track/pulse), fast-track/\<run>/submit, courses/\<id>/listened, course-order (suggest), about, courses/\<id>/checkpoint (submit), checkpoints |
| `/api/review/` | review | overview, session, cards/\<id>/answer, mastery/\<curriculum\_id> |
| `/api/game/` | game | status, achievements, shop, shop/buy, streak/repair, leaderboard (?scope=global|org|class), settings, boss/\<section>/result, notifications (read), nudges, plan, plan.ics, calendar-feed, calendar/\<token>.ics |
| `/api/roleplay/` | roleplay | scenarios (generate, detail), sessions (detail, end, coach, hint) |
| `/api/live/` | live | sessions, sessions/\<id> |
| `/api/workshops/` | workshops | runs (detail, enroll, checkout, session), sessions/\<id> (prereq, start, help, final, build, transcript, agent, agent/servers, refresh, run, approve, reset), mcp |
| `/api/docs/` | docs | list/upload, \<id> detail/delete |
| `/api/paths/` | paths | skills (reorder, bulk, \<slug>), recommendations, curated (\<slug>, join, steps), careers (\<slug>, assessment, plan, goals), assessments/\<id>/submit, placement (\<id>/submit), onboarding-chat, onboarding-apply, company, role-summary, cv, target-role |
| `/api/credentials/` | credentials | list, \<id> (revoke, pdf), verify/\<code>, share, share/facts, orgs/\<slug> (templates, preview, eligible, revoke) |
| `/api/journeys/` | journeys | me (\<aid>, items), orgs/\<slug> (options, people, ai-draft, \<id> duplicate/items/assign/assignees/progress/progress.csv) |
| `/api/orgs/` | orgs | list/create, join/\<code>, invites/\<token>/accept, me/\* (assignments, surveys, brand, documents, fields, cohorts), surveys respond/draft, public-surveys/\<token>, campaign/\<token>, referral/\<code>, survey-templates, \<slug>/\* (dpa, competencies, members, invitations, groups, assignments, nudge, analytics, insights, surveys and results/summary/clone/ai-draft/ai-chat/ai-doc, question-banks, settings, setup, member fields, campaigns and emails, referrals and ledger, documents, teach/*, workshops/*, units/\*, setup-chat, knowledge and graph, cohorts and members) |
| `/api/guests/` | guests | links (\<id>, qr, stats, export.csv), targets, claim, orgs/\<slug>/campaigns, campaigns/\<id> (send-all), prospects/\<id> (regenerate, send), unsubscribe, public/\<slug>/\* (start, resume, email-link, lesson, done, attempt, finish, summary, role-play, say, end) |
| `/api/ext/` | extension | pair/start, pair/claim, devices, disconnect, tasks, tasks/\<id>/submit, authoring/activities/\<id>/steps |
| `/api/billing/` | billing | overview, quote, checkout, verify, failed, history, webhook, subscribe, subscription (verify/cancel/resume), redeem, invoices/\<n>.pdf, orgs/\<slug> (assign-seats, redeem-codes) |
| `/api/calendar/` | calsync | status, replan, \<provider>/connect, callback, disconnect |
| `/api/connect/`, `/api/mcp`, `/.well-known/oauth-*` | connect | me, authorize, oauth/register, token, revoke, orgs/\<slug>/clients (\<id>), orgs/\<slug>/audit; MCP JSON-RPC; RFC 8414 and 9728 discovery |
| `/api/studio/` | studio | courses/\<id> (history, undo, redo, versions, template, export, export.pptx, preset, documents, research, chat, chat/apply), templates (\<id>/use), lesson-library, sections/\<id>/import-lesson, import, presets, subsections/\<id>/lectures, lectures/\<id> (build), exports (org analytics.xlsx, surveys xlsx, admin overview.xlsx, progress.xlsx), review, review.xlsx |
| `/api/media/` | media | upload, generate, mine, lectures/\<uid>/\<name>, \<name> |
| `/api/voice/` | providers | config, transcribe, speak |
| `/api/legal/` | legal | site, subprocessors, consent, export, delete-account |
| `/api/support/` | support | articles (\<slug>), ask, reports |
| `/api/admin/` | all console apps | staff, audit, users (\<id>, action), orgs (\<id>), catalog (\<id>), creators, certificates (\<id> revoke, refresh-name), certificate-templates (preview, \<id>), workshops (runs, publish, announce, cancel, stats, \<slug>/test-run, orgs), payments (config, test, orders, grant, subscriptions), plans, promos, redeem-codes, invoices, refunds, reports (\<id>), help (\<id>), site, mail (test), overview, model-prices, system-check, providers (\<capability>, test), calendar-apps (\<provider>) |
| `/api/health/` | config | liveness, ready |

**WebSockets** (`api/config/asgi.py`)

| Path | Purpose |
| --- | --- |
| `ws/assistant/` | Mentor chat stream with mascot cues |
| `ws/roleplay/` | Role-play character stream |
| `ws/live/` | Live Class voice and snapshots |
| `ws/workshop/<session_id>/` | One learner's workshop session |
| `ws/workshop-runs/<run_id>/monitor/` | Teacher live monitor |

**Scheduled jobs** (Celery beat)

| Job | Every |
| --- | --- |
| plan-reminders | 6 h |
| payment-reconcile | 10 min |
| study-reminders | 15 min |
| evening-checks | 15 min (from each learner's nudge time) |
| stepup-checks | 15 min (step-up after a miss, back-off notice) |
| reminder-nightly | 03:15 (learned study times, back-off, push log pruning) |
| winback-daily | 10:30 |
| clean-media | 24 h |
| guardian-digest | 6 h (sends Sundays) |
| workshop-agent-secrets | 24 h |
| workshop-reminders | 5 min |
| workshop-run-status | 5 min |
| workshop-retention | 24 h |

**Configuration settings** (`api/.env.example`; `setup_env` generates the secrets)

| Group | Settings |
| --- | --- |
| Django | `DJANGO_SECRET_KEY`, `AASAN_SECRETS_KEY`, `AASAN_SECRETS_KEY_OLD`, `DJANGO_DEBUG`, `FRONTEND_URL`, `DJANGO_ALLOWED_HOSTS`, `DJANGO_ADMINS`, `DJANGO_ADMIN_PATH` |
| Infrastructure | `DATABASE_URL`, `REDIS_URL`, `CACHE_REDIS_URL`, `MEDIA_ROOT`, `LOG_LEVEL`, `LOG_FORMAT`, `SLOW_REQUEST_MS`, `DJANGO_NUM_PROXIES` |
| AI providers | `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`, `SARVAM_API_KEY`, `DEEPGRAM_API_KEY`, `GOOGLE_CLOUD_API_KEY` |
| LLM routing and testing | `LLM_ROUTE_TUTOR`, `LLM_ROUTE_AUTHOR`, `LLM_ROUTE_GRADE`, `LLM_ROUTE_SUGGEST`, `LLM_ROUTE_ONBOARDING`, `LLM_FORCE_PROVIDER`, `LLM_FAKE_DELAY_MS`, `LLM_FAKE_TOKEN_MS`, `STT_CHARGE_BYTES_PER_SEC` |
| Payments | `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`, `RAZORPAY_WEBHOOK_SECRET` |
| Sign-in | `GOOGLE_CLIENT_ID`, `WEBAUTHN_RP_ID`, `WEBAUTHN_ORIGIN` |
| Calendar sync | `GOOGLE_CALENDAR_CLIENT_ID`, `GOOGLE_CALENDAR_CLIENT_SECRET`, `MICROSOFT_CALENDAR_CLIENT_ID`, `MICROSOFT_CALENDAR_CLIENT_SECRET` |
| Learning | `CERT_PASS_SCORE`, `ROLEPLAY_AI_DAILY`, `ROLEPLAY_REWARDS_PER_DAY`, `GUEST_AI_FREE_SHARE`, `GUEST_AI_NEW_SHARE`, `GUEST_AI_FREE_OWNER_SHARE` |
| Workshops | `WORKSHOP_SESSION_AI_UNITS`, `WORKSHOP_HELP_PER_HOUR`, `WORKSHOP_CAP_MULTIPLIER`, `WORKSHOP_AGENT_RUNS`, `WORKSHOP_EXTERNAL_MCP`, `WORKSHOP_EXTERNAL_PER_MIN` |
| Email and monitoring | `EMAIL_BACKEND`, `DEFAULT_FROM_EMAIL`, `SENTRY_DSN`, `SENTRY_TRACES` |
| Hardening | `DJANGO_SECURE_SSL_REDIRECT`, `DJANGO_HSTS_SECONDS`, `DJANGO_HSTS_SUBDOMAINS` |
| Compose-only (`infra/.env.example`) | `POSTGRES_PASSWORD`, `REDIS_PASSWORD`, `WEB_PORT`, `EMAIL_HOST/PORT/USER/PASSWORD/USE_TLS/USE_SSL`, `MAILPIT_*`, `WEB_CONCURRENCY`, `DB_POOL_MIN/MAX`, `DB_STATEMENT_TIMEOUT_MS`, `WORKER_DB_STATEMENT_TIMEOUT_MS`, `CELERY_CONCURRENCY`, `WORKER_DB_POOL_MAX`, `PG_MAX_CONNECTIONS`, `PG_SHARED_BUFFERS`, `PG_EFFECTIVE_CACHE_SIZE`, `REDIS_MAXMEMORY`, `REDIS_CACHE_MAXMEMORY`, `API_COMMAND` |

**Scripts**: `api/scripts/load_test.py`, `api/scripts/workshop_load.py`, `web/scripts/export-i18n.mjs`, `infra/backup.sh`, `extension/package.sh`, `extension/icons/make_icons.py`.

**Known gaps and deferred items**

| Item | Status |
| --- | --- |
| Google sign-in button on the login and sign-up pages (API endpoint exists) | 🧪 |
| Skip-to-content link | 🚧 |
| Automatic dark mode from the OS setting | 🚧 |
| TLS termination inside docker-compose | ⚙️ operator (Caddy or load balancer) |
| Continuous deployment | 🚧 CI checks and builds only |
| Object storage (S3) for media, analytics provider, email API provider | 🚧 not configurable; local volume and SMTP only |
| Admin console labels in languages other than English | 🚧 mostly hardcoded English |
| Vision provider for Live Class in the 2026-10-15 spec | ✅ shipped since; vision config stored per capability |
