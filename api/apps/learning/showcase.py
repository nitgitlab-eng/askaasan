"""A hand-built course that contains EVERY activity type — for end-to-end validation without spending AI calls."""

import io

from django.db import transaction
from django.utils import timezone
from PIL import Image, ImageDraw
from pydantic import TypeAdapter

from llm.prompts.curriculum import Activity as ActivitySchema

from . import activities as acts
from .models import Activity, Curriculum, Section, Subsection
from .services import _valid

TITLE = "Aasan Showcase: every activity type"


def _diagram_image(owner) -> str:
    """A simple 'input → model → output' picture for the hotspot activity (no text inside, labels come from the activity)."""
    from apps.media.images import process, store

    img = Image.new("RGB", (900, 420), (255, 250, 242))
    d = ImageDraw.Draw(img)
    boxes = [
        ((60, 150, 260, 270), (59, 130, 246)),
        ((350, 120, 550, 300), (249, 115, 22)),
        ((640, 150, 840, 270), (34, 197, 94)),
    ]
    for (x0, y0, x1, y1), c in boxes:
        d.rounded_rectangle((x0, y0, x1, y1), radius=28, fill=c)
    for x0, x1 in ((260, 350), (550, 640)):
        d.line((x0 + 8, 210, x1 - 18, 210), fill=(60, 50, 40), width=10)
        d.polygon([(x1 - 6, 210), (x1 - 30, 194), (x1 - 30, 226)], fill=(60, 50, 40))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    data, w, h = process(buf.getvalue())
    return store(owner, data, w, h, kind="upload", alt="Input, model and output boxes joined by arrows").url


def lessons(image_url: str) -> list[dict]:
    return [
        {
            "title": "Classic checks",
            "objective": "Recognise what AI is and how it learns from examples",
            "md": "**Artificial intelligence (AI)** learns patterns from *examples*, like a cricket coach who watches thousands of balls before predicting a googly.\n\nTry each activity below: they all check the same idea in different ways.",
            "points": ["AI learns from examples", "More good data → better predictions"],
            "acts": [
                {
                    "type": "quiz",
                    "title": "What does AI learn from?",
                    "prompt": "Pick the best answer.",
                    "options": ["Examples (data)", "Magic", "Only rules typed by hand"],
                    "correct": [0],
                    "multiple": False,
                    "explanation": "Modern AI learns patterns from data.",
                },
                {
                    "type": "fill_blank",
                    "title": "Complete the sentence",
                    "prompt": "Fill in the blank.",
                    "text": "A model learns patterns from [[1]].",
                    "blanks": [{"id": "1", "answers": ["data", "examples"]}],
                    "explanation": "Data = examples.",
                },
                {
                    "type": "sequencing",
                    "title": "Order the steps",
                    "prompt": "Put the steps of training in order.",
                    "items_in_order": ["Collect data", "Train the model", "Test it", "Use it"],
                    "explanation": "Data first, use last.",
                },
                {
                    "type": "categorization",
                    "title": "AI or not?",
                    "prompt": "Sort each item.",
                    "categories": ["Uses AI", "No AI"],
                    "items": [
                        {"text": "Spam filter", "category": "Uses AI"},
                        {"text": "Calculator", "category": "No AI"},
                        {"text": "Voice assistant", "category": "Uses AI"},
                        {"text": "Light switch", "category": "No AI"},
                    ],
                    "explanation": "AI products learn from data.",
                },
                {
                    "type": "matching",
                    "title": "Match the words",
                    "prompt": "Match each term to its meaning.",
                    "pairs": [
                        {"left": "Data", "right": "Examples to learn from"},
                        {"left": "Model", "right": "What learns the pattern"},
                        {"left": "Prediction", "right": "The model's answer"},
                    ],
                    "explanation": "",
                },
            ],
        },
        {
            "title": "Think, code and explain",
            "objective": "Explain AI in your own words and run a tiny program",
            "md": "Now explain, code and read diagrams.",
            "points": ["Explaining helps you remember"],
            "acts": [
                {
                    "type": "open_input",
                    "title": "Explain it",
                    "prompt": "In 2–3 sentences, explain how a spam filter learns.",
                    "model_answer": "It sees many emails labelled spam or not spam and learns which patterns usually mean spam.",
                    "rubric": ["mentions labelled examples", "mentions learning a pattern"],
                },
                {
                    "type": "code",
                    "title": "Your first Python",
                    "prompt": "Make the program print 5.",
                    "language": "python",
                    "starter_code": "a = 2\nb = 3\nprint(a + b)\n",
                    "model_solution": "print(2 + 3)",
                    "expected_output": "5",
                    "rubric": ["prints 5"],
                },
                {
                    "type": "diagram",
                    "title": "Read the flow",
                    "prompt": "What comes right after training?",
                    "mermaid": 'graph LR\n  A["Data"] --> B["Train"] --> C["Test"] --> D["Use"]',
                    "options": ["Test", "Data", "Use"],
                    "correct": [0],
                    "explanation": "Train → Test.",
                },
                {
                    "type": "slides",
                    "title": "Three quick slides",
                    "prompt": "Read, then answer.",
                    "slides": [
                        {"title": "Data", "text": "Examples the model learns from."},
                        {"title": "Model", "text": "Finds the pattern."},
                        {"title": "Prediction", "text": "Its answer for something new."},
                    ],
                    "options": ["The model", "The data"],
                    "correct": [0],
                    "explanation": "The model finds patterns.",
                },
                {
                    "type": "concept_map",
                    "title": "Label the links",
                    "prompt": "Choose the label for each arrow.",
                    "links": [
                        {"source": "Data", "target": "Model", "label": "trains"},
                        {"source": "Model", "target": "Prediction", "label": "makes"},
                    ],
                    "explanation": "",
                },
            ],
        },
        {
            "title": "Explore and decide",
            "objective": "Explore a changing graph and make decisions",
            "md": "Drag the slider, then play a short story.",
            "points": ["Steeper line = bigger change"],
            "acts": [
                {
                    "type": "viz",
                    "title": "Play with a line",
                    "prompt": "Move the slider. What happens when a gets bigger?",
                    "viz": {
                        "kind": "function_plot",
                        "expression": "a*x + 1",
                        "x_min": 0,
                        "x_max": 10,
                        "params": [{"name": "a", "min": 0, "max": 5, "step": 0.5, "value": 1}],
                        "sides": 2,
                    },
                    "options": ["The line gets steeper", "The line disappears"],
                    "correct": [0],
                    "explanation": "",
                },
                {
                    "type": "decision_tree",
                    "title": "Should you trust the answer?",
                    "prompt": "A chatbot gives you a fact for your exam.",
                    "explanation": "",
                    "tree": [
                        {
                            "id": "start",
                            "text": "The chatbot says the Kaveri flows into the Arabian Sea.",
                            "choices": [
                                {
                                    "text": "Write it in the exam",
                                    "next": "",
                                    "ending_score": 0.0,
                                    "feedback": "Always check! It flows into the Bay of Bengal.",
                                },
                                {
                                    "text": "Check the textbook",
                                    "next": "check",
                                    "ending_score": 0,
                                    "feedback": "",
                                },
                            ],
                        },
                        {
                            "id": "check",
                            "text": "The textbook says Bay of Bengal.",
                            "choices": [
                                {
                                    "text": "Trust the textbook",
                                    "next": "",
                                    "ending_score": 1.0,
                                    "feedback": "Great habit: verify AI answers.",
                                },
                                {
                                    "text": "Trust the chatbot",
                                    "next": "",
                                    "ending_score": 0.2,
                                    "feedback": "The textbook is right here.",
                                },
                            ],
                        },
                    ],
                },
                {
                    "type": "task",
                    "title": "Try a chatbot",
                    "prompt": "Ask a chatbot to explain AI to a 10-year-old and paste its answer.",
                    "steps": ["Open a chatbot", "Ask: explain AI to a 10-year-old", "Paste the answer here"],
                    "link": "https://claude.ai",
                    "rubric": ["pasted a real answer", "simple language"],
                    "model_answer": "AI is like a student who learns from lots of examples…",
                },
            ],
        },
        {
            "title": "New: maps, pictures and video",
            "objective": "Find places, label a picture and learn from a video",
            "md": f"Three new kinds of activity.\n\n![Input, model and output]({image_url})\n\nThe picture above is used in the labelling activity.",
            "points": ["Maps, pictures and videos make learning concrete"],
            "acts": [
                {
                    "type": "map",
                    "title": "Find the cities",
                    "prompt": "Tap where each city is on the map of India.",
                    "region": "india",
                    "explanation": "",
                    "places": [
                        {"name": "Chennai", "lat": 13.0827, "lon": 80.2707, "hint": "capital of Tamil Nadu"},
                        {"name": "Bengaluru", "lat": 12.9716, "lon": 77.5946, "hint": "India's tech city"},
                        {"name": "New Delhi", "lat": 28.6139, "lon": 77.209, "hint": "national capital"},
                    ],
                },
                {
                    "type": "hotspot",
                    "title": "Label the picture",
                    "prompt": "Place each label on the right box.",
                    "image": image_url,
                    "explanation": "Data goes in, the model works, a prediction comes out.",
                    "targets": [
                        {"label": "Input (data)", "x": 17.8, "y": 50, "r": 10},
                        {"label": "Model", "x": 50, "y": 50, "r": 10},
                        {"label": "Output (prediction)", "x": 82.2, "y": 50, "r": 10},
                    ],
                },
                {
                    "type": "video",
                    "title": "Watch: what is a neural network?",
                    "prompt": "Watch the start of this video and answer the questions as they pop up.",
                    "video_id": "aircAruvnKk",
                    "start": 0,
                    "end": 240,
                    "explanation": "",
                    "checkpoints": [
                        {
                            "at": 60,
                            "question": "What is the video about?",
                            "options": ["Neural networks", "Cooking"],
                            "correct": [0],
                        },
                        {
                            "at": 180,
                            "question": "Neural networks are inspired by…",
                            "options": ["The brain", "Volcanoes"],
                            "correct": [0],
                        },
                    ],
                },
            ],
        },
        {
            "title": "New: real-world practice",
            "objective": "Use AI for a real task and practise talking about it",
            "md": "Do a real task in your browser, then practise a conversation.",
            "points": ["Show your work with a screenshot", "Practise explaining out loud"],
            "acts": [
                {
                    "type": "browser_task",
                    "title": "Do it and show me",
                    "prompt": "Ask a chatbot for a 3-day study plan for your next exam.",
                    "steps": [
                        "Open a chatbot",
                        "Ask for a 3-day study plan",
                        "Take a screenshot of the answer",
                    ],
                    "link": "https://chatgpt.com",
                    "proof": "the chatbot's 3-day study plan",
                    "rubric": ["screenshot shows a study plan", "it covers 3 days"],
                    "model_answer": "A plan with Day 1, Day 2 and Day 3 topics.",
                },
                {
                    "type": "roleplay",
                    "title": "Explain AI to Paati",
                    "prompt": "Your grandmother asks what this 'AI' is that you keep studying.",
                    "character_name": "Paati",
                    "character_persona": "a curious, kind grandmother in Madurai who loves stories and asks simple questions",
                    "learner_role": "her grandchild",
                    "setting": "the family verandah in the evening",
                    "goal": "explain AI simply with an everyday example",
                    "opening_line": "Kanna, what is this AI you keep talking about? Is it a robot?",
                    "objectives": [
                        "Explain AI with an everyday example",
                        "Answer her follow-up question kindly",
                    ],
                },
                {
                    "type": "artifact_check",
                    "title": "Publish your AI page",
                    "prompt": "Make a one-page Google Site or GitHub Pages site about one AI tool and paste its https:// link.",
                    "steps": [
                        "Create a free one-page site",
                        "Add a heading 'My AI tool' and one picture",
                        "Publish it and copy the public link",
                    ],
                    "checks": [
                        {"kind": "heading", "value": "My AI tool", "min_count": 1},
                        {"kind": "images", "value": "", "min_count": 1},
                    ],
                    "explanation": "Your page is live — share it with a friend!",
                },
            ],
        },
    ]


@transaction.atomic
def build_showcase(owner) -> Curriculum:
    Curriculum.objects.filter(owner=owner, title=TITLE).delete()
    cur = Curriculum.objects.create(
        owner=owner,
        kind=Curriculum.Kind.AUTHORED,
        goal=TITLE,
        title=TITLE,
        status=Curriculum.Status.READY,
        description="One lesson per family of activities — walk through all of them in a few minutes.",
        level="beginner",
        language="en",
        skills=["AI basics"],
        visibility="link",
        published_at=timezone.now(),
    )
    sec = Section.objects.create(curriculum=cur, order=0, title="Every activity type", summary="")
    adapter = TypeAdapter(ActivitySchema)
    img = _diagram_image(owner)
    for i, les in enumerate(lessons(img)):
        sub = Subsection.objects.create(
            section=sec,
            order=i,
            title=les["title"],
            objective=les["objective"],
            skills=["AI basics"],
            lesson_status=Subsection.LessonStatus.READY,
            explanation_md=les["md"],
            key_points=les["points"],
        )
        for j, raw in enumerate(les["acts"]):
            typed = adapter.validate_python(raw).model_dump()
            assert _valid(typed), raw["type"]
            payload, key = acts.build(typed, seed=sub.id * 100 + j)
            Activity.objects.create(
                subsection=sub,
                order=j,
                type=typed["type"],
                title=typed["title"],
                payload=payload,
                key=key,
                source=typed,
            )
    return cur
