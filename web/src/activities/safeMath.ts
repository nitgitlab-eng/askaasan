/**
 * Tiny recursive-descent evaluator for visualization formulas.
 * Grammar: expr = term (("+"|"-") term)* ; term = power (("*"|"/") power)* ;
 * power = unary ("^" power)? ; unary = "-" unary | atom ; atom = number | name | func "(" expr ")" | "(" expr ")"
 * Only whitelisted functions/variables — never eval().
 */
const FUNCS: Record<string, (x: number) => number> = { sin: Math.sin, cos: Math.cos, exp: Math.exp, log: Math.log, sqrt: Math.sqrt, abs: Math.abs };

export type Compiled = (vars: Record<string, number>) => number;

export function compile(src: string, allowed: string[]): Compiled {
  const tokens = src.match(/\d+\.?\d*|[a-z_]+|[+\-*/^()]/gi) ?? [];
  if (tokens.join("") !== src.replace(/\s+/g, "")) throw new Error("invalid characters");
  let i = 0;
  const peek = () => tokens[i];
  const eat = (t?: string) => {
    const v = tokens[i++];
    if (t && v !== t) throw new Error(`expected ${t}`);
    return v;
  };
  type Node = Compiled;
  const expr = (): Node => {
    let left = term();
    while (peek() === "+" || peek() === "-") {
      const op = eat();
      const l = left, r = term();
      left = op === "+" ? (v) => l(v) + r(v) : (v) => l(v) - r(v);
    }
    return left;
  };
  const term = (): Node => {
    let left = power();
    while (peek() === "*" || peek() === "/") {
      const op = eat();
      const l = left, r = power();
      left = op === "*" ? (v) => l(v) * r(v) : (v) => l(v) / r(v);
    }
    return left;
  };
  const power = (): Node => {
    const base = unary();
    if (peek() === "^") {
      eat();
      const exp = power();
      return (v) => Math.pow(base(v), exp(v));
    }
    return base;
  };
  const unary = (): Node => {
    if (peek() === "-") {
      eat();
      const u = unary();
      return (v) => -u(v);
    }
    if (peek() === "+") {
      eat();
      return unary();
    }
    return atom();
  };
  const atom = (): Node => {
    const t = eat();
    if (t === undefined) throw new Error("unexpected end");
    if (t === "(") {
      const e = expr();
      eat(")");
      return e;
    }
    if (/^\d/.test(t)) {
      const n = Number(t);
      return () => n;
    }
    if (FUNCS[t]) {
      eat("(");
      const arg = expr();
      eat(")");
      const f = FUNCS[t];
      return (v) => f(arg(v));
    }
    if (allowed.includes(t)) return (v) => v[t] ?? 0;
    throw new Error(`unknown name ${t}`);
  };
  const tree = expr();
  if (i !== tokens.length) throw new Error("trailing input");
  return tree;
}
