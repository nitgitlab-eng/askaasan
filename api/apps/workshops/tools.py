"""Aasan Tools: the built-in, pure and safe tools a learner's workshop agent may use.

The internal agent loop (agent.py) calls `call()` directly, and our MCP endpoint (mcp_server.py) is a thin adapter over
the same registry, so both paths validate and behave identically. No tool touches the network, the file system or
any data beyond the workshop's own teaching material."""

import ast
import math
import operator
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from functools import lru_cache

CALC_MAX_LEN = 200
CALC_MAX_EXP = 100  # |exponent| allowed in **
CALC_MAX_ABS = 1e100  # every intermediate value stays below this
NOTES_TOP = 3
NOTES_SNIPPET = 600
WORDS_MAX = 10_000
DEFAULT_TZ = "Asia/Kolkata"


class ToolError(Exception):
    """A tool refused its input. `message` is safe to show the learner and the model."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


@dataclass
class Ctx:
    workshop: object | None = None  # the Workshop whose material workshop_notes searches


# ── Argument validation (a small JSON-schema subset) ─────────────────


def check_args(schema: dict, args) -> str:
    """→ "" or a short problem. Objects with typed, bounded properties only; unknown keys are refused."""
    if not isinstance(args, dict):
        return "arguments must be an object"
    props = schema.get("properties", {})
    for k in args:
        if k not in props:
            return f"unknown argument: {str(k)[:40]}"
    for k in schema.get("required", []):
        if k not in args:
            return f"missing argument: {k}"
    for k, v in args.items():
        p = props[k]
        t = p["type"]
        if t == "string":
            if not isinstance(v, str):
                return f"{k} must be a string"
            if len(v) > p.get("maxLength", 1000) or len(v.strip()) < p.get("minLength", 0):
                return f"{k} has the wrong length"
        elif t == "integer":
            if isinstance(v, bool) or not isinstance(v, int):
                return f"{k} must be an integer"
            if not p.get("minimum", v) <= v <= p.get("maximum", v):
                return f"{k} is out of range"
        elif t == "number":
            if isinstance(v, bool) or not isinstance(v, int | float) or not math.isfinite(v):
                return f"{k} must be a number"
            if abs(v) > 1e15:
                return f"{k} is out of range"
        if "enum" in p and v not in p["enum"]:
            return f"{k} must be one of {', '.join(p['enum'])}"
    return ""


# ── calculator ───────────────────────────────────────────────────────

_BINOPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_FUNCS = {
    "sqrt": (math.sqrt, 1, 1),
    "round": (round, 1, 2),
    "abs": (abs, 1, 1),
    "min": (min, 1, 10),
    "max": (max, 1, 10),
    "floor": (math.floor, 1, 1),
    "ceil": (math.ceil, 1, 1),
    "log10": (math.log10, 1, 1),
    "ln": (math.log, 1, 1),
    "sin": (math.sin, 1, 1),
    "cos": (math.cos, 1, 1),
    "tan": (math.tan, 1, 1),
}
_CONSTS = {"pi": math.pi, "e": math.e}


def _num(v):
    if isinstance(v, bool) or not isinstance(v, int | float):
        raise ToolError("Only numbers are allowed.")
    if isinstance(v, float) and not math.isfinite(v):
        raise ToolError("The result is not a finite number.")
    if abs(v) > CALC_MAX_ABS:
        raise ToolError("The number is too large.")
    return v


def _eval(node):
    if isinstance(node, ast.Expression):
        return _eval(node.body)
    if isinstance(node, ast.Constant):
        return _num(node.value)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub | ast.UAdd):
        v = _eval(node.operand)
        return _num(-v if isinstance(node.op, ast.USub) else v)
    if isinstance(node, ast.BinOp) and type(node.op) in _BINOPS:
        left, right = _eval(node.left), _eval(node.right)
        if isinstance(node.op, ast.Pow):
            if abs(right) > CALC_MAX_EXP:
                raise ToolError(f"Exponents are limited to ±{CALC_MAX_EXP}.")
            if left == 0 and right < 0:
                raise ToolError("Division by zero.")
            if abs(left) > 1 and abs(right) * math.log10(abs(left)) > 100:
                raise ToolError("The number is too large.")
        if isinstance(node.op, ast.Div | ast.FloorDiv | ast.Mod) and right == 0:
            raise ToolError("Division by zero.")
        try:
            out = _BINOPS[type(node.op)](left, right)
        except (OverflowError, ValueError, ZeroDivisionError):
            raise ToolError("That calculation isn't possible.") from None
        if isinstance(out, complex):
            raise ToolError("The result is not a real number.")
        return _num(out)
    if isinstance(node, ast.Name) and node.id in _CONSTS:
        return _CONSTS[node.id]
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in _FUNCS
        and not node.keywords
    ):
        fn, lo, hi = _FUNCS[node.func.id]
        if not lo <= len(node.args) <= hi:
            raise ToolError(f"{node.func.id}() takes {lo}-{hi} numbers.")
        args = [_eval(a) for a in node.args]
        if (
            node.func.id == "round"
            and len(args) == 2
            and (not isinstance(args[1], int) or not 0 <= args[1] <= 12)
        ):
            raise ToolError("round() keeps 0-12 decimal places.")
        try:
            return _num(fn(*args))
        except (ValueError, OverflowError):
            raise ToolError(f"{node.func.id}() can't take that value.") from None
    raise ToolError("Only numbers, + - * / // % **, brackets and simple maths functions are allowed.")


def calculate(expression: str):
    expr = (expression or "").strip().replace("×", "*").replace("÷", "/").replace("^", "**")
    if not expr or len(expr) > CALC_MAX_LEN:
        raise ToolError(f"Expressions must be 1-{CALC_MAX_LEN} characters.")
    try:
        tree = ast.parse(expr, mode="eval")
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        raise ToolError("That isn't a valid maths expression.") from None
    if sum(1 for _ in ast.walk(tree)) > 200:
        raise ToolError("That expression is too long.")
    v = _eval(tree)
    if isinstance(v, float):
        v = round(v, 10)
        if v.is_integer() and abs(v) < 1e15:
            v = int(v)
    return v


def _calculator(ctx: Ctx, args: dict) -> dict:
    return {"expression": args["expression"][:CALC_MAX_LEN], "result": calculate(args["expression"])}


# ── workshop_notes ───────────────────────────────────────────────────

_STOP_WORDS = (
    "the and for are was were with that this from what when where which who how why you your our has have had "
    "can could will would should into onto about than then them they their there here also just only very more "
    "most some any all not but its it's is am be been being of to in on at by an a or as if do does did"
)
_STOP = set(_STOP_WORDS.split())


def _words(text: str) -> list[str]:
    return [w for w in re.findall(r"[\w₹%]+", (text or "").lower()) if len(w) > 2 and w not in _STOP]


def notes_chunks(workshop) -> list[tuple[str, str]]:
    """(stage title, text) pieces of the workshop's agenda: material paragraphs, concepts and steps. Never `final`."""
    out = []
    for st in (getattr(workshop, "agenda", None) or []) if workshop else []:
        title = str(st.get("title", ""))
        for para in str(st.get("material_md") or "").split("\n\n"):
            if para.strip():
                out.append((title, para.strip()))
        for key in ("concepts", "steps"):
            for item in st.get(key) or []:
                text = item.get("q", "") if isinstance(item, dict) else str(item)
                if text.strip():
                    out.append((title, text.strip()))
    return out


def _notes(ctx: Ctx, args: dict) -> dict:
    q = _words(args["query"])
    if not q:
        raise ToolError("Give a few keywords to search for.")
    scored = []
    for i, (title, text) in enumerate(notes_chunks(ctx.workshop)):
        words = _words(f"{title} {text}")
        score = sum(words.count(w) for w in set(q)) + 2 * len(set(q) & set(_words(title)))
        if score:
            scored.append((-score, i, title, text))
    scored.sort()
    return {
        "query": args["query"][:200],
        "results": [
            {"stage": title[:120], "snippet": text[:NOTES_SNIPPET]}
            for _, _, title, text in scored[:NOTES_TOP]
        ],
    }


# ── datetime ─────────────────────────────────────────────────────────


@lru_cache(maxsize=1)
def _zones() -> frozenset:
    from zoneinfo import available_timezones

    return frozenset(available_timezones())


def _tz(name: str | None):
    from zoneinfo import ZoneInfo

    name = (name or DEFAULT_TZ).strip()
    if name.upper() == "IST":
        name = DEFAULT_TZ
    if name.upper() == "UTC":
        name = "UTC"
    if name not in _zones():
        raise ToolError("Unknown time zone. Use an IANA name such as Asia/Kolkata or Europe/London.")
    return ZoneInfo(name)


def _parse_dt(raw: str, tz):
    try:
        d = datetime.fromisoformat(raw.strip())
    except ValueError:
        raise ToolError("Dates look like 2026-10-18 or 2026-10-18T14:30.") from None
    return d.replace(tzinfo=tz) if d.tzinfo is None else d.astimezone(tz)


def _parse_date(raw: str) -> date:
    try:
        return date.fromisoformat(raw.strip()[:10])
    except ValueError:
        raise ToolError("Dates look like 2026-10-18.") from None


def _datetime(ctx: Ctx, args: dict) -> dict:
    from . import services

    action = args["action"]
    if action == "now":
        tz = _tz(args.get("tz"))
        at = services.now().astimezone(tz)
        return {"tz": str(tz), "datetime": at.isoformat(timespec="minutes"), "weekday": at.strftime("%A")}
    if action == "convert":
        src, dst = _tz(args.get("from_tz")), _tz(args.get("to_tz"))
        if not args.get("datetime"):
            raise ToolError("Give the datetime to convert.")
        d = _parse_dt(args["datetime"], src)
        out = d.astimezone(dst)
        return {
            "from": d.isoformat(timespec="minutes"),
            "to": out.isoformat(timespec="minutes"),
            "tz": str(dst),
        }
    if action == "add_days":
        if not args.get("date") or "days" not in args:
            raise ToolError("Give a date and a number of days.")
        try:
            out = _parse_date(args["date"]) + timedelta(days=args["days"])
        except OverflowError:
            raise ToolError("That date is out of range.") from None
        return {"date": out.isoformat(), "weekday": out.strftime("%A")}
    if not args.get("date"):
        raise ToolError("Give a date.")
    d = _parse_date(args["date"])
    return {"date": d.isoformat(), "weekday": d.strftime("%A")}


# ── units ────────────────────────────────────────────────────────────

# unit → (category, factor to the category's base unit)
_UNITS: dict[str, tuple[str, float]] = {}


def _add(category: str, factor: float, *names: str):
    for n in names:
        _UNITS[n] = (category, factor)


_add("length", 1, "m", "metre", "metres", "meter", "meters")
_add("length", 1000, "km", "kilometre", "kilometres", "kilometer", "kilometers")
_add("length", 0.01, "cm", "centimetre", "centimetres", "centimeter", "centimeters")
_add("length", 0.001, "mm", "millimetre", "millimetres", "millimeter", "millimeters")
_add("length", 1609.344, "mi", "mile", "miles")
_add("length", 0.9144, "yd", "yard", "yards")
_add("length", 0.3048, "ft", "foot", "feet")
_add("length", 0.0254, "in", "inch", "inches")
_add("mass", 1, "kg", "kilogram", "kilograms", "kilo", "kilos")
_add("mass", 0.001, "g", "gram", "grams")
_add("mass", 1e-6, "mg", "milligram", "milligrams")
_add("mass", 1000, "t", "tonne", "tonnes")
_add("mass", 0.45359237, "lb", "lbs", "pound", "pounds")
_add("mass", 0.028349523125, "oz", "ounce", "ounces")
_add("volume", 1, "l", "litre", "litres", "liter", "liters")
_add("volume", 0.001, "ml", "millilitre", "millilitres", "milliliter", "milliliters")
_add("volume", 1000, "m3", "cubic metre", "cubic meter")
_add("volume", 3.785411784, "gal", "gallon", "gallons")
_add("volume", 0.2365882365, "cup", "cups")
_add("speed", 1, "m/s", "mps")
_add("speed", 1 / 3.6, "km/h", "kmph", "kph")
_add("speed", 0.44704, "mph")
_add("speed", 0.514444, "knot", "knots", "kn")
_add("data", 1, "b", "byte", "bytes")
_add("data", 1024, "kb", "kilobyte", "kilobytes")
_add("data", 1024**2, "mb", "megabyte", "megabytes")
_add("data", 1024**3, "gb", "gigabyte", "gigabytes")
_add("data", 1024**4, "tb", "terabyte", "terabytes")
_add("area", 1, "m2", "sq m", "square metre", "square meter", "square metres", "square meters")
_add("area", 1e6, "km2", "sq km", "square kilometre", "square kilometer")
_add("area", 0.09290304, "ft2", "sq ft", "square foot", "square feet")
_add("area", 10_000, "ha", "hectare", "hectares")
_add("area", 4046.8564224, "acre", "acres")
_add("area", 1e-4, "cm2", "sq cm", "square centimetre", "square centimeter")
_TEMPS = {
    "c": "c",
    "celsius": "c",
    "°c": "c",
    "f": "f",
    "fahrenheit": "f",
    "°f": "f",
    "k": "k",
    "kelvin": "k",
}


def _unit(name: str) -> str:
    return " ".join(name.strip().lower().replace("²", "2").replace("³", "3").split())


def _units(ctx: Ctx, args: dict) -> dict:
    v, a, b = float(args["value"]), _unit(args["from"]), _unit(args["to"])
    if a in _TEMPS and b in _TEMPS:
        ta, tb = _TEMPS[a], _TEMPS[b]
        c = v if ta == "c" else (v - 32) * 5 / 9 if ta == "f" else v - 273.15
        out = c if tb == "c" else c * 9 / 5 + 32 if tb == "f" else c + 273.15
        cat = "temperature"
    else:
        if a not in _UNITS or b not in _UNITS:
            raise ToolError(
                f"Unknown unit. Supported: {', '.join(sorted({n for n in _UNITS if len(n) <= 5}))}."
            )
        (ca, fa), (cb, fb) = _UNITS[a], _UNITS[b]
        if ca != cb:
            raise ToolError(f"Can't convert {ca} to {cb}.")
        out, cat = v * fa / fb, ca
    return {
        "value": v,
        "from": args["from"][:30],
        "to": args["to"][:30],
        "result": round(out, 6),
        "category": cat,
    }


# ── word_count ───────────────────────────────────────────────────────


def _word_count(ctx: Ctx, args: dict) -> dict:
    text = args["text"]
    words = re.findall(r"\S+", text)
    sentences = [s for s in re.split(r"[.!?।]+", text) if s.strip()]
    return {
        "words": len(words),
        "characters": len(text),
        "characters_no_spaces": len(re.sub(r"\s", "", text)),
        "sentences": len(sentences),
        "reading_time_minutes": round(len(words) / 200, 1),
    }


# ── Registry ─────────────────────────────────────────────────────────

TOOLS: dict[str, dict] = {
    "calculator": {
        "title": "Calculator",
        "description": (
            "Exact arithmetic. Numbers, + - * / // % ** and brackets, plus sqrt, round, abs, min, max, floor, ceil, "
            "log10, ln, sin, cos, tan, pi and e. Example: 2450 * 18 / 100"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"expression": {"type": "string", "maxLength": CALC_MAX_LEN, "minLength": 1}},
            "required": ["expression"],
            "additionalProperties": False,
        },
        "fn": _calculator,
    },
    "workshop_notes": {
        "title": "Workshop notes",
        "description": "Search this workshop's teaching material. Returns up to 3 short snippets.",
        "inputSchema": {
            "type": "object",
            "properties": {"query": {"type": "string", "maxLength": 200, "minLength": 1}},
            "required": ["query"],
            "additionalProperties": False,
        },
        "fn": _notes,
    },
    "datetime": {
        "title": "Date and time",
        "description": (
            "action=now (current time in tz, default Asia/Kolkata); convert (datetime from_tz → to_tz); add_days "
            "(date + days, negative to subtract); weekday (of date). Dates are ISO: 2026-10-18 or 2026-10-18T14:30."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["now", "convert", "add_days", "weekday"]},
                "tz": {"type": "string", "maxLength": 64},
                "from_tz": {"type": "string", "maxLength": 64},
                "to_tz": {"type": "string", "maxLength": 64},
                "datetime": {"type": "string", "maxLength": 40},
                "date": {"type": "string", "maxLength": 40},
                "days": {"type": "integer", "minimum": -36500, "maximum": 36500},
            },
            "required": ["action"],
            "additionalProperties": False,
        },
        "fn": _datetime,
    },
    "units": {
        "title": "Unit converter",
        "description": (
            "Convert length, mass, temperature, volume, speed, data (KB/MB/GB, 1024-based) and area. "
            "Example: value=5, from=km, to=miles"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "value": {"type": "number"},
                "from": {"type": "string", "maxLength": 30, "minLength": 1},
                "to": {"type": "string", "maxLength": 30, "minLength": 1},
            },
            "required": ["value", "from", "to"],
            "additionalProperties": False,
        },
        "fn": _units,
    },
    "word_count": {
        "title": "Word count",
        "description": "Words, characters, sentences and reading time (200 words a minute) for up to 10,000 characters.",
        "inputSchema": {
            "type": "object",
            "properties": {"text": {"type": "string", "maxLength": WORDS_MAX}},
            "required": ["text"],
            "additionalProperties": False,
        },
        "fn": _word_count,
    },
}
NAMES = tuple(TOOLS)


def tool_list(names=None) -> list[dict]:
    """MCP `tools/list` entries (name, title, description, inputSchema)."""
    return [
        {"name": n, "title": t["title"], "description": t["description"], "inputSchema": t["inputSchema"]}
        for n, t in TOOLS.items()
        if names is None or n in names
    ]


def call(name: str, args, ctx: Ctx) -> dict:
    """Validate and run one Aasan tool. Raises ToolError (unknown tool, bad arguments or a refused input)."""
    tool = TOOLS.get(name) if isinstance(name, str) else None
    if not tool:
        raise ToolError(f"Unknown tool: {str(name)[:64]}")
    if problem := check_args(tool["inputSchema"], args):
        raise ToolError(f"Invalid arguments: {problem}")
    return tool["fn"](ctx, args)
