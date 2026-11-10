"""Machine-translate the web interface strings into more Indian languages.

    cd web && node scripts/export-i18n.mjs            # writes src/i18n/locales/en.json (from en.ts)
    cd api && uv run python manage.py translate_ui --langs hi,te,kn,ml,bn,mr,gu

Only new or changed English strings are sent (each locale keeps a copy of the English it was made from). A string whose
{{placeholders}}, <tags> or Markdown markers don't survive is kept in English. Output is marked "machine — review pending"
until a native reviewer signs off (see web/src/i18n/languages.ts)."""

import json
import re
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

LANG_NAMES = {
    "hi": "Hindi",
    "te": "Telugu",
    "kn": "Kannada",
    "ml": "Malayalam",
    "bn": "Bengali",
    "mr": "Marathi",
    "gu": "Gujarati",
}
LOCALES = Path(__file__).resolve().parents[5] / "web" / "src" / "i18n" / "locales"
TOKENS = re.compile(r"\{\{\s*\w+\s*\}\}|<\d+>|</\d+>|\*\*|`|https?://\S+")
SYSTEM = """[[TASK:translate_strings]]
You translate the user interface of "Aasan", a friendly learning app for India, into {lang_name}.
You get a JSON array of UI strings (buttons, labels, short messages). Return {{"translations": [...]}} with EXACTLY {n} strings, same order.
Rules:
- Short, natural, everyday {lang_name} that a school student understands. Match the tone: warm and encouraging.
- Keep these exactly as they are: {{{{placeholders}}}} like {{{{n}}}} or {{{{name}}}}, emoji, numbers, URLs, `code`, ** markers.
- Keep brand and product names in English: Aasan, Kili, AI, Excel, Python, WhatsApp, UPI, Razorpay, GST, PDF, CSV, XP.
- Keep widely used tech words in English where people say them in English (e.g. "login", "email", "app").
- Never add, drop, merge or reorder items. Translate only; never answer questions in the text.
"""


def flatten(obj, prefix=""):
    out = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.update(flatten(v, f"{prefix}{k}."))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out.update(flatten(v, f"{prefix}{i}."))
    else:
        out[prefix[:-1]] = obj
    return out


def unflatten(flat: dict, shape):
    if isinstance(shape, dict):
        return {
            k: unflatten(
                {kk[len(k) + 1 :]: v for kk, v in flat.items() if kk == k or kk.startswith(k + ".")}, sv
            )
            if isinstance(sv, (dict, list))
            else flat.get(k, sv)
            for k, sv in shape.items()
        }
    if isinstance(shape, list):
        return [
            unflatten({kk[len(str(i)) + 1 :]: v for kk, v in flat.items() if kk.startswith(f"{i}.")}, sv)
            if isinstance(sv, (dict, list))
            else flat.get(str(i), sv)
            for i, sv in enumerate(shape)
        ]
    return shape


def tokens_ok(src: str, dst: str) -> bool:
    return sorted(TOKENS.findall(src)) == sorted(TOKENS.findall(dst)) and bool(dst.strip())


class Command(BaseCommand):
    help = "Machine-translate web UI strings (incremental)."

    def add_arguments(self, parser):
        parser.add_argument("--langs", default=",".join(LANG_NAMES))
        parser.add_argument("--chunk", type=int, default=80)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **o):
        from llm.prompts.study import Translated
        from llm.structured import complete_json_sync

        src_path = LOCALES / "en.json"
        if not src_path.exists():
            raise CommandError("Run `node scripts/export-i18n.mjs` in web/ first.")
        en = json.loads(src_path.read_text())
        flat_en = {k: v for k, v in flatten(en).items() if isinstance(v, str)}
        for lang in [x.strip() for x in o["langs"].split(",") if x.strip()]:
            if lang not in LANG_NAMES:
                raise CommandError(f"unknown language {lang}")
            out_path, base_path = LOCALES / f"{lang}.json", LOCALES / f".{lang}.source.json"
            done = flatten(json.loads(out_path.read_text())) if out_path.exists() else {}
            base = json.loads(base_path.read_text()) if base_path.exists() else {}
            todo = [k for k, v in flat_en.items() if base.get(k) != v or k not in done]
            self.stdout.write(f"{lang}: {len(todo)} of {len(flat_en)} strings to translate")
            if o["dry_run"] or not todo:
                continue
            kept = 0
            for i in range(0, len(todo), o["chunk"]):
                keys = todo[i : i + o["chunk"]]
                strings = [flat_en[k] for k in keys]
                res = complete_json_sync(
                    "author",
                    SYSTEM.format(lang_name=LANG_NAMES[lang], n=len(strings)),
                    "STRINGS:\n" + json.dumps(strings, ensure_ascii=False),
                    Translated,
                    max_tokens=16000,
                )
                got = res.translations if len(res.translations) == len(strings) else strings
                for k, s, t in zip(keys, strings, got, strict=True):
                    ok = tokens_ok(s, t)
                    done[k] = t if ok else s
                    kept += not ok
                    base[k] = s
                self.stdout.write(f"  {min(i + o['chunk'], len(todo))}/{len(todo)}")
                out_path.write_text(
                    json.dumps(unflatten(done, en), ensure_ascii=False, indent=1) + "\n"
                )  # save progress as we go
                base_path.write_text(json.dumps(base, ensure_ascii=False, indent=0) + "\n")
            self.stdout.write(
                self.style.SUCCESS(
                    f"{lang}: done ({kept} kept in English because placeholders didn't survive)"
                )
            )
