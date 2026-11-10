"""Deterministic offline provider for tests and keyless local dev."""

import asyncio
import json
import re
import time

from ..base import LLMRequest, StreamEvent

CANNED = {
    "[[TASK:journey_draft]]": {
        "name": "Support associate onboarding",
        "description": "Your first month, one day at a time.",
        "phases": [
            {"title": "Week 1: Settle in", "start_day": 1, "end_day": 7},
            {"title": "Weeks 2-3: Learn the job", "start_day": 8, "end_day": 21},
            {"title": "Week 4: Fly solo", "start_day": 22, "end_day": 30},
            {"title": "Out of range", "start_day": 40, "end_day": 50},
        ],
        "items": [
            {
                "day": 1,
                "kind": "note",
                "title": "Collect your laptop and ID card",
                "notes": "HR desk, 10 am.",
                "ref_id": 0,
                "colleague_role": "",
            },
            {
                "day": 2,
                "kind": "lesson",
                "title": "Product basics",
                "notes": "Finish before lunch.",
                "ref_id": 999999,
                "colleague_role": "",
            },
            {
                "day": 3,
                "kind": "shadow",
                "title": "Sit with a senior agent",
                "notes": "Listen to five calls.",
                "ref_id": 0,
                "colleague_role": "a senior support agent",
            },
            {
                "day": 4,
                "kind": "scenario",
                "title": "Calm an upset customer",
                "notes": "Practise twice.",
                "ref_id": 0,
                "colleague_role": "",
            },
            {
                "day": 99,
                "kind": "note",
                "title": "Beyond the plan",
                "notes": "",
                "ref_id": 0,
                "colleague_role": "",
            },
            {
                "day": 5,
                "kind": "hack",
                "title": "Unknown kind",
                "notes": "",
                "ref_id": 0,
                "colleague_role": "",
            },
        ],
    },
    "[[TASK:career_plan_30]]": {
        "summary": "Four focused weeks will close your biggest gaps.",
        "weeks": [
            {"week": 1, "theme": "Foundations"},
            {"week": 2, "theme": "Practice"},
            {"week": 3, "theme": "Projects"},
            {"week": 4, "theme": "Show your work"},
        ],
        "goals": [
            {
                "week": 1,
                "title": "Write your first SQL queries",
                "skill": "sql",
                "course_id": 0,
                "lesson_id": 0,
                "course_goal": "SQL from zero for data analysts",
            },
            {
                "week": 1,
                "title": "Clean a messy sheet",
                "skill": "spreadsheets",
                "course_id": 999999,
                "lesson_id": 0,
                "course_goal": "",
            },
            {
                "week": 2,
                "title": "Summarise a dataset",
                "skill": "statistics",
                "course_id": 0,
                "lesson_id": 0,
                "course_goal": "Statistics for everyday decisions",
            },
            {
                "week": 3,
                "title": "Build a simple dashboard",
                "skill": "data-visualization",
                "course_id": 0,
                "lesson_id": 0,
                "course_goal": "Dashboards with Google Sheets",
            },
            {
                "week": 4,
                "title": "Present your findings",
                "skill": "english-communication",
                "course_id": 0,
                "lesson_id": 0,
                "course_goal": "Presenting data clearly",
            },
            {
                "week": 9,
                "title": "Out of range week",
                "skill": "sql",
                "course_id": 0,
                "lesson_id": 0,
                "course_goal": "x",
            },
        ],
        "people": [
            {
                "role": "a senior data analyst in your team",
                "why": "They know which reports matter.",
                "ask": "Which report do you rely on most?",
            },
            {
                "role": "a product manager who uses dashboards",
                "why": "They decide with data.",
                "ask": "What question do you wish data could answer?",
            },
        ],
    },
    "[[TASK:podcast_episode]]": {
        "title": "Tables, explained over chai",
        "host_a": "Meera",
        "host_b": "Arjun",
        "turns": [
            {"speaker": "A", "text": "Arjun, everyone keeps saying tables. What is a table, really?"},
            {
                "speaker": "B",
                "text": "Think of your school attendance register. Each row is one student, each column is one detail.",
            },
            {"speaker": "A", "text": "So a row is one record?"},
            {
                "speaker": "B",
                "text": "Exactly. One row, one record. Columns tell you what kind of detail is stored.",
            },
            {"speaker": "A", "text": "That is simpler than I thought."},
            {
                "speaker": "B",
                "text": "Recap: rows are records, columns are fields. Try spotting them in your UPI history.",
            },
        ],
    },
    "[[TASK:fast_track_check]]": {
        "questions": [
            {
                "prompt": "A shop keeps one line per sale with date, item and price. What is each line?",
                "options": ["A record (row)", "A column", "A table", "A key"],
                "correct": 0,
                "explanation": "Each sale is one record.",
            },
            {
                "prompt": "Which change adds a new field to every record?",
                "options": ["Adding a column", "Adding a row", "Deleting a row", "Sorting"],
                "correct": 0,
                "explanation": "A new column is a new field.",
            },
            {"prompt": "Bad key", "options": ["x", "y", "z"], "correct": 4, "explanation": "dropped"},
        ]
    },
    "[[TASK:course_order_suggest]]": {
        "order": [999999],
        "reasons": [{"id": 999999, "reason": "Not a real course"}],
        "note": "Finish what is nearly done first, then build on it.",
    },
    "[[TASK:lx_widget]]": {
        "title": "EMI explorer",
        "html": '<!doctype html><html><head><style>body{font:16px system-ui;margin:12px;color:#222;background:#fff}label{display:block;margin:8px 0}output{font-weight:bold}</style></head><body><label>Interest rate (% per year) <input id="r" type="range" min="1" max="20" step="0.5" value="9"> <output id="ro">9</output></label><p>EMI on a loan of ₹1,00,000 for 12 months: <output id="emi"></output></p><label>At 12% the EMI is about ₹ <input id="a" type="number"></label><button id="b">Check</button><script>var r=document.getElementById("r");function emi(p,y,n){var m=y/1200;return p*m*Math.pow(1+m,n)/(Math.pow(1+m,n)-1);}function draw(){document.getElementById("ro").textContent=r.value;document.getElementById("emi").textContent="₹"+Math.round(emi(100000,+r.value,12));}r.addEventListener("input",draw);draw();document.getElementById("b").addEventListener("click",function(){parent.postMessage({type:"aasan-widget-answer",answer:Number(document.getElementById("a").value)},"*");});</script></body></html>',
        "checkpoint_question": "What is the EMI at 12% (to the nearest rupee)?",
        "answer_kind": "number",
        "answer_value": "8885",
        "answer_tolerance": 5,
    },
    "[[TASK:lx_tutor_teach]]": {
        "message": "Think of a model like a child learning to spot ripe mangoes from many examples.",
        "question": "What does a model learn from?",
    },
    "[[TASK:lx_tutor_turn]]": {
        "score": 0.9,
        "feedback": "Yes — exactly right!",
        "reexplain": "Another way to see it: a cricket coach learns from many matches.",
        "reexplain_question": "So what does the coach learn from?",
        "next_message": "Next idea: more good examples make better guesses.",
        "next_question": "Why do more examples help?",
    },
    "[[TASK:connect_demo_lesson]]": {
        "course_title": "Smart Saving with UPI",
        "description": "A five-minute taste of everyday money habits.",
        "lesson_title": "Track every rupee",
        "objective": "See how small UPI payments add up",
        "explanation_md": "**Small payments** add up, like drops filling a matka. Check your UPI history weekly.",
        "key_points": ["Small spends add up", "Check history weekly", "Set a simple budget"],
        "activities": [
            {
                "type": "quiz",
                "title": "Spot the habit",
                "prompt": "Which habit helps you save?",
                "options": ["Checking UPI history weekly", "Ignoring receipts", "Paying twice"],
                "correct": [0],
                "multiple": False,
                "explanation": "Looking back shows where money goes.",
            },
            {
                "type": "sequencing",
                "title": "Order it",
                "prompt": "Put the steps in order",
                "items_in_order": ["Check spends", "Set a limit", "Review next week"],
                "explanation": "Know first, then plan.",
            },
            {
                "type": "open_input",
                "title": "Not allowed in demos",
                "prompt": "Explain",
                "model_answer": "x",
                "rubric": ["y"],
            },
        ],
    },
    "[[TASK:roleplay_facts]]": {
        "facts": [{"text": "The restaurant bill was ₹1,240."}, {"text": "Refunds are allowed within 7 days."}]
    },
    "[[TASK:roleplay_track]]": {
        "objectives": [
            {"score": 2, "reason": "You named the problem clearly."},
            {"score": 7, "reason": "Out of range gets clamped."},
        ],
        "competencies": [{"score": 1, "reason": "Started simply."}],
        "contradictions": [
            {
                "fact_index": 0,
                "learner_quote": "₹1,420",
                "correction": "Check: the bill was ₹1,240, not ₹1,420",
                "confidence": 0.95,
            },
            {
                "fact_index": 0,
                "learner_quote": "₹1,240",
                "correction": "Same number: not a mismatch",
                "confidence": 0.99,
            },
            {
                "fact_index": 1,
                "learner_quote": "30 days",
                "correction": "Check: refunds are within 7 days",
                "confidence": 0.4,
            },
            {"fact_index": 9, "learner_quote": "₹1,420", "correction": "No such fact", "confidence": 0.99},
        ],
    },
    "[[TASK:roleplay_hint]]": {"hint": "Try asking what they need from you before giving the answer."},
    "[[TASK:org_setup_chat]]": {
        "reply": "Lovely! Here is a first setup you can accept or skip.",
        "proposals": [
            {
                "op": "set_description",
                "text": "A Chennai school for classes 6–10 focused on science and spoken English.",
            },
            {"op": "add_group", "title": "Class 8 A"},
            {"op": "set_target_roles", "roles": ["data-analyst", "not-a-real-role"]},
            {"op": "set_feature", "feature": "leaderboard", "on": False},
            {
                "op": "course_idea",
                "title": "Science basics with AI",
                "text": "Short lessons on everyday science with quick quizzes.",
            },
            {"op": "add_unit", "title": "Primary", "text": "Classes 1–5"},
        ],
    },
    "[[TASK:kb_topics]]": {"topics": ["Leave Policy", "Onboarding", "leave policy", "Safety Checklist"]},
    "[[TASK:survey_chat]]": {
        "reply": "Here are my suggestions — accept the ones you like.",
        "changes": [
            {
                "op": "update",
                "target": "q1",
                "after": "",
                "text": "",
                "summary": "Make Q1 a 1–5 scale",
                "question": {
                    "type": "scale",
                    "text": "How useful are the lessons?",
                    "required": True,
                    "section": "Lessons",
                    "options": [],
                    "rows": [],
                    "min": 1,
                    "max": 5,
                    "min_label": "Not useful",
                    "max_label": "Very useful",
                    "correct": [],
                    "accepted": [],
                    "points": 0,
                },
            },
            {
                "op": "add",
                "target": "",
                "after": "q1",
                "text": "",
                "summary": "Add a section on canteen food",
                "question": {
                    "type": "choice",
                    "text": "How is the canteen food?",
                    "required": False,
                    "section": "Canteen food",
                    "options": ["Good", "OK", "Poor"],
                    "rows": [],
                    "min": 0,
                    "max": 0,
                    "min_label": "",
                    "max_label": "",
                    "correct": ["Good"],
                    "accepted": [],
                    "points": 2,
                },
            },
            {
                "op": "remove",
                "target": "q99",
                "after": "",
                "text": "",
                "summary": "Remove a question that does not exist",
                "question": {
                    "type": "text",
                    "text": "x",
                    "required": False,
                    "section": "",
                    "options": [],
                    "rows": [],
                    "min": 0,
                    "max": 0,
                    "min_label": "",
                    "max_label": "",
                    "correct": [],
                    "accepted": [],
                    "points": 0,
                },
            },
            {
                "op": "title",
                "target": "",
                "after": "",
                "text": "Term feedback (short)",
                "summary": "Shorter title",
                "question": {
                    "type": "text",
                    "text": "x",
                    "required": False,
                    "section": "",
                    "options": [],
                    "rows": [],
                    "min": 0,
                    "max": 0,
                    "min_label": "",
                    "max_label": "",
                    "correct": [],
                    "accepted": [],
                    "points": 0,
                },
            },
        ],
    },
    "[[TASK:survey_from_doc]]": {
        "title": "Photosynthesis check",
        "description": "A quick test on the notes",
        "questions": [
            {
                "type": "choice",
                "text": "Where does photosynthesis happen?",
                "required": True,
                "section": "Basics",
                "options": ["Chloroplast", "Nucleus", "Root"],
                "rows": [],
                "min": 0,
                "max": 0,
                "min_label": "",
                "max_label": "",
                "correct": ["Chloroplast"],
                "accepted": [],
                "points": 2,
            },
            {
                "type": "multi",
                "text": "Which are inputs?",
                "required": True,
                "section": "Basics",
                "options": ["Water", "Sunlight", "Salt"],
                "rows": [],
                "min": 0,
                "max": 0,
                "min_label": "",
                "max_label": "",
                "correct": ["Water", "Sunlight"],
                "accepted": [],
                "points": 1,
            },
            {
                "type": "text",
                "text": "Name the green pigment",
                "required": False,
                "section": "Words",
                "options": [],
                "rows": [],
                "min": 0,
                "max": 0,
                "min_label": "",
                "max_label": "",
                "correct": [],
                "accepted": ["chlorophyll"],
                "points": 1,
            },
            {
                "type": "choice",
                "text": "Broken key",
                "required": False,
                "section": "",
                "options": ["A", "B"],
                "rows": [],
                "min": 0,
                "max": 0,
                "min_label": "",
                "max_label": "",
                "correct": ["C"],
                "accepted": [],
                "points": 1,
            },
        ],
    },
    "[[TASK:share_progress]]": {
        "text": "This quarter I completed 3 lessons on Aasan and kept a 4-day streak.",
        "hashtags": ["Learning", "Aasan", "bad tag!", "#Growth"],
    },
    "[[TASK:guest_demo]]": {
        "course_title": "AI for Logistics Teams",
        "description": "A five-minute taste of AI for dispatch planners.",
        "lesson_title": "Smarter delivery routes",
        "objective": "See how AI suggests faster routes from past trips",
        "explanation_md": "**AI** learns from past trips, like a dispatcher who remembers which roads jam at 6 pm.",
        "key_points": ["AI learns from past trips", "Better data, better routes", "People still decide"],
        "activities": [
            {
                "type": "quiz",
                "title": "Spot the AI",
                "prompt": "Which task suits AI best?",
                "options": ["Predicting late deliveries", "Signing a contract", "Painting a truck"],
                "correct": [0],
                "multiple": False,
                "explanation": "Predictions come from patterns in past data.",
            },
            {
                "type": "sequencing",
                "title": "Order it",
                "prompt": "Put the steps in order",
                "items_in_order": ["Collect trip data", "Train a model", "Suggest routes"],
                "explanation": "Data comes first.",
            },
            {
                "type": "open_input",
                "title": "Not allowed in demos",
                "prompt": "Explain",
                "model_answer": "x",
                "rubric": ["y"],
            },
        ],
        "email_subject": "A short AI demo lesson for your dispatch team",
        "email_body": "Hello team,\n\nWe prepared a five-minute interactive lesson showing how AI can help plan delivery routes. Give it a try.\n\nWarm regards,\nDemo Academy",
    },
    "[[TASK:teach_roleplay_concept]]": {
        "summary": "Most learners listen well but few agree a next step.",
        "got_right": ["Warm greeting"],
        "got_wrong": ["About half forget to confirm the next step"],
        "reteach_tips": ["Practise closing lines in pairs"],
    },
    "[[TASK:teach_roleplay_insights]]": {
        "headline": "The class opens politely but struggles to close.",
        "strengths": ["Most learners greet warmly"],
        "struggles": ["About half forget to confirm next steps"],
        "teaching_tips": ["Model a strong closing line"],
    },
    "[[TASK:teach_misconceptions]]": {
        "summary": "One main mix-up.",
        "misconceptions": [
            {
                "topic": "Confusing terms",
                "questions": ["Quiz"],
                "learners": 1,
                "explanation": "Learners mix up the two ideas.",
                "reteach_tip": "Contrast them side by side.",
            }
        ],
    },
    "[[TASK:explainer_video]]": {
        "title": "What is AI? — in 90 seconds",
        "scenes": [
            {
                "heading": "Machines that learn",
                "points": ["Learns from examples", "Not magic"],
                "visual": "🤖",
                "narration": "Imagine teaching a child to spot mangoes. You show many mangoes, and soon they can tell. AI learns the same way.",
            },
            {
                "heading": "Recap",
                "points": ["Examples in, patterns out"],
                "visual": "✅",
                "narration": "So remember: AI finds patterns in examples.",
            },
        ],
    },
    "[[TASK:checkpoint_quiz]]": {
        "items": [
            {
                "prompt": f"Checkpoint question {i + 1}: which is true about AI?",
                "options": ["It learns from examples", "It is magic", "It never errs", "It has feelings"],
                "correct": 0,
                "explanation": "AI learns patterns from examples.",
                "lesson": "What is AI?",
            }
            for i in range(5)
        ]
    },
    "[[TASK:add_section]]": {
        "title": "AI at work",
        "summary": "Using AI tools in everyday jobs.",
        "subsections": [
            {"title": "AI for emails", "objective": "Draft a polite email with AI", "skills": ["Prompting"]},
            {"title": "AI for spreadsheets", "objective": "Summarise a sheet with AI", "skills": []},
        ],
    },
    "[[TASK:company_summary]]": {
        "summary": "A Chennai software services company building apps for banks.",
        "industry": "IT services",
    },
    "[[TASK:role_summary]]": {
        "summary": "Analyses data to help teams decide.",
        "skills": ["Excel", "SQL", "Data visualisation", "Communication"],
    },
    "[[TASK:cv_parse]]": {
        "current_role": "Accounts assistant",
        "years_experience": 2,
        "skills": ["Excel", "Tally", "Communication"],
        "summary": "Two years in accounts; strong with spreadsheets.",
    },
    "[[TASK:target_role_plan]]": {
        "required": ["Excel", "SQL", "Data visualisation", "Statistics"],
        "missing": ["SQL", "Data visualisation"],
        "courses": ["SQL basics for analysts", "Charts that tell a story"],
    },
    "[[TASK:pulse_adapt]]": {
        "message": "Thanks for telling me! Let's slow down a little.",
        "tip": "Try the hint button on the next question.",
        "simpler": "AI is like a student who learns from many examples.",
        "extra": "Next, look at how recommendations work on YouTube.",
    },
    "[[TASK:curriculum_outline]]": {
        "title": "AI Basics for Beginners",
        "description": "A friendly first course on what AI is and how it learns.",
        "skills": ["AI concepts", "Machine learning intuition", "Prompting"],
        "sections": [
            {
                "title": "What is AI?",
                "summary": "Meet AI in daily life.",
                "subsections": [
                    {
                        "title": "AI around you",
                        "objective": "Identify three AI apps you already use",
                        "skills": ["AI concepts", "Not a course skill"],
                    },
                    {
                        "title": "How machines learn",
                        "objective": "Explain learning from examples",
                        "skills": ["Machine learning intuition"],
                    },
                ],
            },
            {
                "title": "Talking to AI",
                "summary": "Get great answers.",
                "subsections": [
                    {"title": "Writing good prompts", "objective": "Write a clear prompt with context"},
                ],
            },
        ],
    },
    "[[TASK:lesson_package]]": {
        "explanation_md": "**AI** learns from examples, like a cricket coach who watches many balls.",
        "key_points": ["AI learns patterns from data", "More examples usually help"],
        "activities": [
            {
                "type": "quiz",
                "title": "Spot the AI",
                "prompt": "Which app uses AI?",
                "options": ["Calculator", "Maps traffic ETA", "Torch"],
                "correct": [1],
                "multiple": False,
                "explanation": "ETA predicts from traffic data.",
            },
            {
                "type": "fill_blank",
                "title": "Fill it",
                "prompt": "Complete the sentence",
                "text": "AI learns from [[1]].",
                "blanks": [{"id": "1", "answers": ["data", "examples"]}],
                "explanation": "Data = examples.",
            },
            {
                "type": "sequencing",
                "title": "Order",
                "prompt": "Put the steps in order",
                "items_in_order": ["Collect data", "Train model", "Make predictions"],
                "explanation": "Data first.",
            },
            {
                "type": "categorization",
                "title": "Sort",
                "prompt": "AI or not?",
                "categories": ["AI", "Not AI"],
                "items": [
                    {"text": "Spam filter", "category": "AI"},
                    {"text": "Light switch", "category": "Not AI"},
                ],
                "explanation": "Spam filters learn.",
            },
            {
                "type": "matching",
                "title": "Match",
                "prompt": "Match terms",
                "pairs": [
                    {"left": "Data", "right": "Examples"},
                    {"left": "Model", "right": "Learned pattern"},
                ],
                "explanation": "Basics.",
            },
            {
                "type": "open_input",
                "title": "Explain",
                "prompt": "Explain AI to a friend",
                "model_answer": "Software that learns patterns from examples.",
                "rubric": ["mentions learning", "mentions examples/data"],
            },
            {
                "type": "code",
                "title": "Hello AI",
                "prompt": "Print hello",
                "starter_code": "# print hello\n",
                "model_solution": "print('hello')",
                "expected_output": "hello",
                "rubric": ["prints hello"],
            },
            {
                "type": "diagram",
                "title": "Flow",
                "prompt": "What comes after training?",
                "mermaid": 'graph LR\n  A["Data"] --> B["Train"] --> C["Predict"]',
                "options": ["Data", "Predict"],
                "correct": [1],
                "explanation": "Prediction follows training.",
            },
        ],
    },
    "[[TASK:practice_set]]": {
        "explanation_md": "Fresh practice!",
        "key_points": ["Patterns come from data"],
        "activities": [
            {
                "type": "quiz",
                "title": "Practice quiz",
                "prompt": "Which learns from data?",
                "options": ["Rule", "ML model"],
                "correct": [1],
                "multiple": False,
                "explanation": "ML learns.",
            },
            {
                "type": "matching",
                "title": "Practice match",
                "prompt": "Match",
                "pairs": [{"left": "A", "right": "1"}, {"left": "B", "right": "2"}],
                "explanation": "ok",
            },
        ],
    },
    "[[TASK:single_activity]]": {
        "explanation_md": "",
        "key_points": [],
        "activities": [
            {
                "type": "quiz",
                "title": "Teacher quiz",
                "prompt": "Pick the ML example",
                "options": ["Spam filter", "Light switch"],
                "correct": [0],
                "multiple": False,
                "explanation": "Learns from data.",
            }
        ],
    },
    "[[TASK:roleplay_scenario]]": {
        "allowed": True,
        "emoji": "🎤",
        "title": "Pitch your idea",
        "summary": "Pitch a project idea to a mentor.",
        "learner_role": "A student pitching an app idea",
        "character": {
            "name": "Anand",
            "persona": "a startup mentor",
            "goal": "test the idea",
            "style": "curious",
        },
        "setting": "A college incubator",
        "objectives": ["State the problem", "Explain the solution"],
        "competencies": [
            {"name": "Clarity", "description": "clear"},
            {"name": "Persuasion", "description": "convincing"},
        ],
        "opening_line": "So, what's your idea?",
    },
    "[[TASK:roleplay_eval]]": {
        "overall": 72,
        "competencies": [
            {
                "name": "Simplicity",
                "score": 4,
                "evidence": ["banks never ask for OTP", "I made this up"],
                "comment": "Clear.",
            },
            {"name": "Empathy", "score": 3, "evidence": [], "comment": "Kind."},
        ],
        "objectives_met": [True, False],
        "strengths": ["Clear safety rule"],
        "improvements": ["Reassure more"],
        "better_phrasing": [
            {
                "learner_said": "Banks never ask for OTP Paati",
                "try_saying": "Paati, no real bank ever asks for an OTP.",
            },
            {"learner_said": "words never spoken", "try_saying": "x"},
        ],
        "summary": "Good start.",
    },
    "[[TASK:org_insights]]": {
        "headline": "Your class is getting started.",
        "insights": ["2 learners active this week"],
        "actions": ["Send a friendly nudge"],
    },
    "[[TASK:survey_summary]]": {
        "themes": ["Pace"],
        "positives": ["Clear lessons"],
        "concerns": ["Too fast for some"],
        "suggested_actions": ["Add a recap session"],
    },
    "[[TASK:live_summary]]": {
        "title": "Fractions practice",
        "covered": ["Adding fractions with different denominators"],
        "mistakes": ["Added denominators directly — find a common denominator first"],
        "next_steps": ["Try 3 more problems with unlike denominators"],
    },
    "[[TASK:grade_screenshot]]": {
        "score": 0.9,
        "feedback": "Your screenshot shows the chatbot answering with a clear role and format — well done.",
    },
    "[[TASK:video_questions]]": {
        "checkpoints": [
            {
                "at": 45,
                "question": "What does a model learn from?",
                "options": ["Examples", "Magic", "Nothing"],
                "correct": [0],
            }
        ]
    },
    "[[TASK:match_spoken_choice]]": {"index": 1, "confident": True},
    "[[TASK:adaptive_scenarios]]": {
        "scenarios": [
            {
                "title": "Build a WhatsApp order-reply helper for your shop",
                "deliverable": "Prompts and a simple flow that answer common order questions.",
                "level": "beginner",
                "weeks": 4,
                "foundations": False,
            },
            {
                "title": "Forecast next month's stock from your sales sheet",
                "deliverable": "A sheet where AI helps estimate what to reorder.",
                "level": "beginner",
                "weeks": 3,
                "foundations": False,
            },
            {
                "title": "Write product descriptions in Tamil and English",
                "deliverable": "A reusable prompt that writes listings in both languages.",
                "level": "beginner",
                "weeks": 2,
                "foundations": False,
            },
            {
                "title": "Understand AI basics first",
                "deliverable": "Explain what AI is, how it learns and how to use it well.",
                "level": "beginner",
                "weeks": 3,
                "foundations": True,
            },
        ]
    },
    "[[TASK:adaptive_verify]]": {
        "verdict": "accept",
        "reason": "",
        "scenario": {
            "title": "Reply to customer orders with AI",
            "deliverable": "A prompt set that drafts replies to customer orders.",
            "level": "beginner",
            "weeks": 3,
            "foundations": False,
        },
        "alternatives": [],
    },
    "[[TASK:adaptive_graph]]": {
        "concepts": [
            {
                "key": "ai-in-daily-life",
                "title": "AI in daily life",
                "description": "Where AI already shows up around you.",
                "prereqs": [],
                "critical": True,
            },
            {
                "key": "learning-from-examples",
                "title": "Learning from examples",
                "description": "Models learn patterns from data.",
                "prereqs": ["ai-in-daily-life", "learning-from-examples", "no-such-concept"],
                "critical": True,
            },
            {
                "key": "Prompting Basics!",
                "title": "Prompting",
                "description": "Ask clearly, with context.",
                "prereqs": ["ai-in-daily-life"],
                "critical": True,
            },
            {
                "key": "ai-history",
                "title": "A little AI history",
                "description": "Nice to know.",
                "prereqs": [],
                "critical": False,
            },
        ],
        "lessons": [
            {"lesson": 1, "concepts": ["ai-in-daily-life", "ai-history"]},
            {"lesson": 2, "concepts": ["learning-from-examples"]},
            {"lesson": 3, "concepts": ["Prompting Basics!"]},
            {"lesson": 9, "concepts": ["ai-in-daily-life"]},
        ],
    },
    "[[TASK:placement_quiz]]": {
        "questions": [
            {
                "skill": "AI",
                "difficulty": d,
                "prompt": f"Q{i}",
                "options": ["a", "b", "c", "d"],
                "correct": 0,
                "explanation": "e",
            }
            for i, d in enumerate([1, 1, 2, 2, 3])
        ]
    },
    "[[TASK:role_assessment]]": {
        "questions": [
            {
                "skill": "Spreadsheets (Excel/Sheets)",
                "difficulty": 2,
                "prompt": "Q",
                "options": ["a", "b", "c", "d"],
                "correct": 1,
                "explanation": "e",
            },
            {
                "skill": "SQL & databases",
                "difficulty": 3,
                "prompt": "Q2",
                "options": ["a", "b", "c", "d"],
                "correct": 2,
                "explanation": "e",
            },
        ]
    },
    "[[TASK:smart_onboarding]]": {
        "reply": "Nice to meet you! What would you like to learn?",
        "done": False,
        "profile": {
            "goals": ["learn AI"],
            "background": "",
            "interests": ["prompting"],
            "minutes_per_day": 20,
            "level_guess": "beginner",
            "first_course_goal": "Learn AI basics",
        },
    },
    "[[TASK:activity_hint]]": {
        "text": "Think about what the question is really asking. Which idea from the lesson fits?"
    },
    "[[TASK:explain_selection]]": {
        "text": "This means the computer learns patterns from many examples, like a child learning to spot mangoes."
    },
    "[[TASK:progress_insights]]": {
        "headline": "You're building a steady habit!",
        "strengths": ["Regular practice"],
        "focus": ["Do today's review"],
        "summary": "You have been learning steadily.",
    },
    "[[TASK:ask_your_data]]": {
        "supported": True,
        "metric": "xp",
        "group_by": "day",
        "days": 14,
        "chart": "bar",
        "title": "XP per day",
        "note": "",
    },
    "[[TASK:org_ask]]": {
        "supported": True,
        "metric": "completion",
        "group_by": "class",
        "days": 30,
        "chart": "bar",
        "title": "Completion by class",
        "class_id": None,
        "assignment_id": None,
        "note": "",
    },
    "[[TASK:authoring_chat]]": {
        "reply": "Here's a plan: add a practice section with one lesson.",
        "changes": [
            {"op": "add_section", "title": "Practice", "text": "Hands-on practice"},
            {"op": "add_lesson", "ref": 0, "title": "Try it yourself", "text": "Apply what you learnt"},
            {"op": "write_lesson", "lesson_id": -1, "text": "Should be rejected: bad id"},
        ],
    },
    "[[TASK:lecture_segments]]": {
        "segments": [
            {
                "start": 0,
                "end": 50,
                "title": "Intro",
                "summary": "What we'll learn",
                "checkpoints": [
                    {"at": 48, "question": "Topic?", "options": ["AI", "Cooking"], "correct": [0]}
                ],
            },
            {
                "start": 50,
                "end": 120,
                "title": "Main idea",
                "summary": "How it works",
                "checkpoints": [
                    {
                        "at": 118,
                        "question": "Learns from?",
                        "options": ["Examples", "Nothing"],
                        "correct": [0],
                    }
                ],
            },
        ]
    },
    "[[TASK:quarterly_review]]": {
        "title": "Your quarterly review",
        "overview": "A steady quarter.",
        "covered": ["SQL basics"],
        "mastered": ["Rows and columns"],
        "growth": ["Practice joins"],
        "next_quarter": ["Finish SQL", "Start Python", "Review weekly"],
    },
    "[[TASK:survey_writer]]": {
        "title": "Class feedback",
        "description": "Tell us how it's going",
        "questions": [
            {
                "type": "rating",
                "text": "How useful are the lessons?",
                "required": True,
                "options": [],
                "rows": [],
                "min": 0,
                "max": 0,
                "min_label": "",
                "max_label": "",
            },
            {
                "type": "matrix",
                "text": "Rate each part",
                "required": False,
                "options": ["Poor", "OK", "Great"],
                "rows": ["Videos", "Quizzes"],
                "min": 0,
                "max": 0,
                "min_label": "",
                "max_label": "",
            },
            {
                "type": "choice",
                "text": "Broken",
                "required": False,
                "options": ["only one"],
                "rows": [],
                "min": 0,
                "max": 0,
                "min_label": "",
                "max_label": "",
            },
            {
                "type": "text",
                "text": "Anything else?",
                "required": False,
                "options": [],
                "rows": [],
                "min": 0,
                "max": 0,
                "min_label": "",
                "max_label": "",
            },
        ],
    },
    "[[TASK:ask_help]]": {
        "answer": "Go to Learn → New course and type your goal.",
        "sources": ["create-course", "made-up-slug"],
        "covered": True,
    },
    "[[TASK:grade_open]]": {"score": 0.75, "feedback": "Good start! Mention that AI learns from examples."},
    "[[TASK:grade_code]]": {"score": 1.0, "feedback": "Correct — nicely done!"},
    "[[TASK:workshop_check]]": {
        "answered": True,
        "score": 0.9,
        "note": "They described it in their own words.",
    },
    "[[TASK:workshop_agent_judge]]": {
        "score": 0.9,
        "feedback": "Used the right tool and gave a clear answer.",
    },
    "[[TASK:workshop_help]]": {
        "reply_md": "The formula is missing a closing bracket.\n\n1. Click cell D2.\n2. Add `)` at the end.",
        "summary": "Sheets formula parse error: missing closing bracket in the distance formula.",
    },
}


def _agent_step(content: str) -> dict:
    """Canned workshop-agent behaviour: maths → calculator, "N unit to unit" → units, then answer from the result."""
    import re

    def step(thought="", calls=(), answer=""):
        return {"thought": thought, "tool_calls": list(calls), "answer": answer}

    tools = set(
        re.findall(
            r"^- ([A-Za-z0-9_.-]+): ", content.split("<tools>", 1)[-1].split("</tools>", 1)[0], re.MULTILINE
        )
    )
    m = re.search(r"<user_message>\n(.*?)\n</user_message>", content, re.DOTALL)
    msg = (m.group(1) if m else "").replace(",", "")
    results = re.findall(r"<tool_result>\n(.*?)\n</tool_result>", content, re.DOTALL)
    if results:
        raw = results[-1]
        try:
            data = json.loads(raw)
        except ValueError:
            return step("I have the result.", answer=f"The tool said: {raw[:200]}")
        if isinstance(data, dict) and "result" in data:
            return step("I have the result.", answer=f"The answer is {data['result']}.")
        if isinstance(data, dict) and data.get("results"):
            return step("Found it in the notes.", answer=data["results"][0]["snippet"][:300])
        if isinstance(data, dict) and "weekday" in data:
            return step("I have the date.", answer=f"It is {data.get('date', '')}, a {data['weekday']}.")
        return step("I have the result.", answer=raw[:300])
    pct = re.search(r"(\d+(?:\.\d+)?)\s*%", msg)
    nums = re.findall(r"\d+(?:\.\d+)?", msg)
    if "calculator" in tools and pct and len(nums) >= 2:
        base = next(n for n in nums if n != pct.group(1))
        expr = f"{base} * {pct.group(1)} / 100"
        return step(
            "I'll use the calculator.",
            [{"name": "calculator", "arguments": json.dumps({"expression": expr})}],
        )
    date = re.search(r"\d{4}-\d{2}-\d{2}", msg)
    if "datetime" in tools and date:
        args = {"action": "weekday", "date": date.group(0)}
        return step("I'll check the date.", [{"name": "datetime", "arguments": json.dumps(args)}])
    arith = re.search(r"\d[\d\s.]*[-+*/][\d\s.+*/()-]*\d", msg)
    if "calculator" in tools and arith:
        expr = arith.group(0).strip()
        return step(
            "I'll use the calculator.",
            [{"name": "calculator", "arguments": json.dumps({"expression": expr})}],
        )
    conv = re.search(
        r"(\d+(?:\.\d+)?)\s*([A-Za-z/]+)\b.*?\b(?:to|in|into|how many)\s+([A-Za-z/]+)", msg, re.IGNORECASE
    )
    if "units" in tools and conv:
        args = {"value": float(conv.group(1)), "from": conv.group(2), "to": conv.group(3)}
        return step("I'll convert the units.", [{"name": "units", "arguments": json.dumps(args)}])
    if "workshop_notes" in tools and re.search(r"\b(agent|loop|tool|workshop|notes)\b", msg, re.IGNORECASE):
        words = " ".join(re.findall(r"[A-Za-z]{4,}", msg)[:6]) or msg[:60]
        return step(
            "I'll search the notes.", [{"name": "workshop_notes", "arguments": json.dumps({"query": words})}]
        )
    return step("I can answer directly.", answer="I'm your demo agent. Ask me a maths or unit question!")


def _env_seconds(name: str) -> float:
    """LLM_FAKE_DELAY_MS / LLM_FAKE_TOKEN_MS from settings, in seconds (0 when unset or not configured)."""
    from django.conf import settings
    from django.core.exceptions import ImproperlyConfigured

    try:
        return max(0, int(getattr(settings, name, 0) or 0)) / 1000
    except ImproperlyConfigured:  # settings not configured (plain-Python use)
        return 0.0


# A question the demo mentor "searches the web" for (tests and e2e of live web search).
_TIME_SENSITIVE = re.compile(
    r"(?i)\b(today|latest|current|news|price|score|this week|right now)\b|இன்று|இன்றைய"
)


class FakeProvider:
    """Canned replies, no network. For load tests, LLM_FAKE_DELAY_MS (time to first token) and LLM_FAKE_TOKEN_MS (per
    streamed chunk) make it as slow as a real model: asyncio.sleep in async paths, time.sleep in sync ones."""

    name = "fake"

    def __init__(self, delay: float | None = None, first_token: float | None = None):
        token = _env_seconds("LLM_FAKE_TOKEN_MS")
        self.delay = delay if delay is not None else (token or 0.02)  # per chunk; 0.02 s keeps old behaviour
        self.first_token = first_token if first_token is not None else _env_seconds("LLM_FAKE_DELAY_MS")

    def _reply(self, req: LLMRequest) -> str:
        if "[[TASK:translate_strings]]" in req.system:  # echo with a tag so tests can see what was translated
            content = req.messages[-1].content
            strings = json.loads(content.split("STRINGS:\n", 1)[1]) if "STRINGS:\n" in content else []
            return json.dumps({"translations": [f"«T» {x}" for x in strings]}, ensure_ascii=False)
        if "[[TASK:workshop_agent]]" in req.system:
            return json.dumps(_agent_step(req.messages[-1].content), ensure_ascii=False)
        for marker, payload in CANNED.items():
            if marker in req.system:
                return json.dumps(payload, ensure_ascii=False)
        return (
            "🧪 **Demo mode** — no AI model is connected yet, so this is a canned reply.\n\n"
            "Add an API key in `api/.env` and remove `LLM_FORCE_PROVIDER=fake` to talk to the real mentor.\n\n"
            "டெமோ முறை: உண்மையான AI இன்னும் இணைக்கப்படவில்லை."
        )

    async def stream(self, req: LLMRequest):
        text = self._reply(req)
        sources = []
        if req.web_search and req.messages and _TIME_SENSITIVE.search(req.messages[-1].content):
            yield StreamEvent(status="searching")
            sources = [{"title": "Example news (demo search)", "url": "https://example.org/news"}]
            text = "According to Example News (demo search), here is today's update. " + text
        if self.first_token:
            await asyncio.sleep(self.first_token)
        for word in text.split(" "):
            await asyncio.sleep(self.delay)
            yield StreamEvent(delta=word + " ")
        yield StreamEvent(
            done=True,
            stop_reason="end_turn",
            usage={"input_tokens": 0, "output_tokens": len(text.split())},
            model="fake",
            sources=sources,
        )

    def _whole_reply_seconds(self, text: str) -> float:
        """A non-streamed answer costs what streaming it would: first token, then the per-token delay for each chunk.
        Only when load-test latency is configured; otherwise complete() stays instant, as before."""
        token = _env_seconds("LLM_FAKE_TOKEN_MS")
        return self.first_token + (token * len(text.split(" ")) if token else 0)

    async def complete(self, req: LLMRequest) -> str:
        text = self._reply(req)
        wait = self._whole_reply_seconds(text)
        if wait:
            await asyncio.sleep(wait)
        return text

    def complete_sync(self, req: LLMRequest) -> str:
        """Blocking variant for sync callers that don't run an event loop."""
        text = self._reply(req)
        wait = self._whole_reply_seconds(text)
        if wait:
            time.sleep(wait)
        return text
