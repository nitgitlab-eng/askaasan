"""Run the guardrail red-team set (llm/redteam.py) against the real configured tutor model and print pass/fail.

Run once before shipping and after any prompt change. It makes real AI calls (about 2 per case, plus web searches),
which count toward the AI budget like any other use."""

import json

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from llm.redteam import CASES, run


class Command(BaseCommand):
    help = "Red-team the learner-facing prompts on the real tutor model (safety, privacy, injection, web search)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--surface", help="Only one surface: mentor, voice, documents, live, roleplay, workshop."
        )
        parser.add_argument("--case", action="append", help="Only these case ids (repeatable).")
        parser.add_argument("--json", action="store_true", help="Print the results as JSON.")
        parser.add_argument("--show", action="store_true", help="Print each reply under its row.")
        parser.add_argument("--concurrency", type=int, default=4)

    def handle(self, *args, **opts):
        if settings.LLM_FORCE_PROVIDER:
            raise CommandError(
                f"LLM_FORCE_PROVIDER={settings.LLM_FORCE_PROVIDER} is set: demo replies can't be judged. "
                "Blank it in .env and run again."
            )
        cases = [
            c
            for c in CASES
            if (not opts["surface"] or c.surface == opts["surface"])
            and (not opts["case"] or c.id in opts["case"])
        ]
        if not cases:
            raise CommandError("No cases match.")
        self.stdout.write(f"Running {len(cases)} cases on the tutor model…")
        results = run(cases, concurrency=max(1, opts["concurrency"]))
        failed = [r for r in results if not r.passed]
        if opts["json"]:
            self.stdout.write(
                json.dumps(
                    [
                        {
                            "id": r.case.id,
                            "surface": r.case.surface,
                            "passed": r.passed,
                            "reason": r.reason,
                            "searched": r.searched,
                            "sources": r.sources,
                            "reply": r.reply,
                        }
                        for r in results
                    ],
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            for r in results:
                mark = self.style.SUCCESS("✓") if r.passed else self.style.ERROR("✗")
                web = "web" if r.searched or r.sources else "   "
                self.stdout.write(f"{mark} {r.case.id:<20} {r.case.surface:<9} {web}  {r.reason}")
                if opts["show"] or not r.passed:
                    self.stdout.write("    " + (r.reply or "(no reply)").replace("\n", "\n    ")[:1200])
        summary = f"{len(results) - len(failed)}/{len(results)} passed"
        if failed:
            raise CommandError(summary + ". Fix the prompts (llm/prompts/guardrails.py) and run again.")
        self.stdout.write(self.style.SUCCESS(summary))
