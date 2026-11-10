/**
 * Geometry for the course map: lesson cards laid out as a snake (left→right, then right→left on the next row),
 * odd columns dropped a little so the connectors bend, and the SVG paths that join each card to the next.
 */
export interface MapLayout {
  cols: number;
  cardW: number;
  cardH: number;
  height: number;
  cards: { x: number; y: number }[];
  links: string[];
}

const GAP_X = 40;
const GAP_Y = 44;
const STAGGER = 28;
const R = 14;

export function columnsFor(width: number) {
  return width >= 860 ? 3 : width >= 500 ? 2 : 1;
}

/** An elbow from (x1,y1) to (x2,y2) that turns at x = mx, with rounded corners. */
export function elbow(x1: number, y1: number, x2: number, y2: number, mx: number) {
  if (Math.abs(y2 - y1) < 1) return `M ${x1} ${y1} H ${x2}`;
  const dx = Math.sign(x2 - x1) || 1;
  const dy = Math.sign(y2 - y1);
  const r = Math.min(R, Math.abs(y2 - y1) / 2, Math.abs(mx - x1), Math.abs(x2 - mx));
  return [
    `M ${x1} ${y1}`,
    `H ${mx - dx * r}`,
    `Q ${mx} ${y1} ${mx} ${y1 + dy * r}`,
    `V ${y2 - dy * r}`,
    `Q ${mx} ${y2} ${mx + dx * r} ${y2}`,
    `H ${x2}`,
  ].join(" ");
}

export function layoutMap(count: number, width: number): MapLayout {
  const fit = columnsFor(width); // card size follows the screen, so a 1-lesson section isn't one huge card
  const cols = Math.max(1, Math.min(fit, count || 1));
  const cardH = fit === 1 ? 132 : 164;
  const cardW = fit === 1 ? width : (width - GAP_X * (fit - 1)) / fit;
  const cards = Array.from({ length: count }, (_, i) => {
    const row = Math.floor(i / cols);
    const k = i % cols;
    const col = row % 2 === 0 ? k : cols - 1 - k;
    const drop = cols > 1 && col % 2 === 1 ? STAGGER : 0;
    return { x: col * (cardW + GAP_X), y: row * (cardH + GAP_Y) + drop };
  });
  const links: string[] = [];
  for (let i = 0; i + 1 < count; i++) {
    const a = cards[i], b = cards[i + 1];
    if (Math.abs(a.x - b.x) < 1) {
      // next row, same column: straight down
      links.push(`M ${a.x + cardW / 2} ${a.y + cardH} V ${b.y}`);
    } else if (b.x > a.x) {
      links.push(elbow(a.x + cardW, a.y + cardH / 2, b.x, b.y + cardH / 2, a.x + cardW + GAP_X / 2));
    } else {
      links.push(elbow(a.x, a.y + cardH / 2, b.x + cardW, b.y + cardH / 2, a.x - GAP_X / 2));
    }
  }
  const height = count ? Math.max(...cards.map((c) => c.y)) + cardH : 0;
  return { cols, cardW, cardH, height, cards, links };
}
