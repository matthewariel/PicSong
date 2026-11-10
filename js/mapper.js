// A picture becomes a stable soundboard schedule.
// Sixteen columns are beats. Four rows are overlapping hits.
// The same pixels always pick the same clips, times, and gains.

export const COLS = 16;
export const ROWS = 4;
export const BEAT_SEC = 0.75;
export const ROW_STAGGER_SEC = 0.16;
const JITTER_STEPS = 61;
const TAIL_SEC = 0.04;

export function hashInt(...parts) {
  let h = 2166136261;
  for (const part of parts) {
    h ^= part | 0;
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

function hueDeg(r, g, b) {
  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  const d = max - min;
  if (d === 0) return 0;
  let h;
  if (max === r) h = ((g - b) / d) % 6;
  else if (max === g) h = (b - r) / d + 2;
  else h = (r - g) / d + 4;
  h *= 60;
  if (h < 0) h += 360;
  return h;
}

function isGreenHeavy(r, g, b) {
  return g >= 45 && g > r * 1.15 && g > b * 1.15;
}

function weightsFor(cell) {
  const { r, g, b } = cell;
  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  const sat = max === 0 ? 0 : (max - min) / max;
  if (isGreenHeavy(r, g, b)) {
    return [
      ['animal', 0.74],
      ['bonk', 0.1],
      ['plink', 0.06],
      ['boing', 0.05],
      ['brass', 0.05],
    ];
  }
  if (sat < 0.16) {
    return [
      ['bonk', 0.58],
      ['boing', 0.16],
      ['plink', 0.12],
      ['brass', 0.09],
      ['animal', 0.05],
    ];
  }
  const hue = hueDeg(r, g, b);
  if (hue < 35 || hue >= 345) {
    return [
      ['brass', 0.66],
      ['bonk', 0.12],
      ['boing', 0.1],
      ['plink', 0.07],
      ['animal', 0.05],
    ];
  }
  if (hue < 70) {
    return [
      ['plink', 0.34],
      ['brass', 0.28],
      ['boing', 0.18],
      ['bonk', 0.14],
      ['animal', 0.06],
    ];
  }
  if (hue < 160) {
    return [
      ['animal', 0.4],
      ['plink', 0.22],
      ['bonk', 0.16],
      ['boing', 0.14],
      ['brass', 0.08],
    ];
  }
  if (hue < 200) {
    return [
      ['plink', 0.55],
      ['boing', 0.15],
      ['bonk', 0.14],
      ['animal', 0.08],
      ['brass', 0.08],
    ];
  }
  if (hue < 255) {
    return [
      ['plink', 0.62],
      ['bonk', 0.14],
      ['boing', 0.12],
      ['brass', 0.07],
      ['animal', 0.05],
    ];
  }
  if (hue < 310) {
    return [
      ['boing', 0.5],
      ['plink', 0.18],
      ['bonk', 0.14],
      ['brass', 0.12],
      ['animal', 0.06],
    ];
  }
  return [
    ['bonk', 0.4],
    ['boing', 0.24],
    ['brass', 0.2],
    ['plink', 0.1],
    ['animal', 0.06],
  ];
}

function pickWeighted(pairs, hash) {
  let total = 0;
  for (const [, weight] of pairs) total += weight;
  let cursor = (hash % 1000000) / 1000000 * total;
  for (const [tag, weight] of pairs) {
    cursor -= weight;
    if (cursor < 0) return tag;
  }
  return pairs[pairs.length - 1][0];
}

function pickClip(clips, tag, hash) {
  const pool = [];
  for (const clip of clips) {
    if (clip.tag === tag) pool.push(clip);
  }
  const source = pool.length ? pool : clips;
  if (!source.length) throw new Error('The soundboard is empty');
  return source[hash % source.length];
}

export function gridFromImageData(imageData, cols = COLS, rows = ROWS) {
  const { width, height, data } = imageData;
  if (!width || !height) throw new Error('Empty picture');
  const grid = [];
  for (let row = 0; row < rows; row += 1) {
    const y0 = Math.floor((row * height) / rows);
    const y1 = Math.max(y0 + 1, Math.floor(((row + 1) * height) / rows));
    const line = [];
    for (let col = 0; col < cols; col += 1) {
      const x0 = Math.floor((col * width) / cols);
      const x1 = Math.max(x0 + 1, Math.floor(((col + 1) * width) / cols));
      let r = 0;
      let g = 0;
      let b = 0;
      let n = 0;
      const yStop = Math.min(y1, height);
      const xStop = Math.min(x1, width);
      for (let y = y0; y < yStop; y += 1) {
        for (let x = x0; x < xStop; x += 1) {
          const i = (y * width + x) * 4;
          const a = data[i + 3] / 255;
          r += data[i] * a + 255 * (1 - a);
          g += data[i + 1] * a + 255 * (1 - a);
          b += data[i + 2] * a + 255 * (1 - a);
          n += 1;
        }
      }
      if (n === 0) n = 1;
      r = Math.round(r / n);
      g = Math.round(g / n);
      b = Math.round(b / n);
      const brightness = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255;
      line.push({ r, g, b, brightness });
    }
    grid.push(line);
  }
  return grid;
}

export function buildSchedule(grid, clips) {
  const events = [];
  for (let col = 0; col < COLS; col += 1) {
    for (let row = 0; row < ROWS; row += 1) {
      const cell = grid[row][col];
      const tag = pickWeighted(weightsFor(cell), hashInt(cell.r, cell.g, cell.b, col, row, 1));
      const chosen = pickClip(clips, tag, hashInt(cell.r, cell.g, cell.b, col, row, 2));
      const brightness = Math.min(1, Math.max(0, cell.brightness));
      const gain = 0.15 + 0.85 * brightness ** 0.75;
      const jitter = (hashInt(cell.r, cell.g, cell.b, col, row, 3) % JITTER_STEPS) / 1000;
      events.push({
        time: col * BEAT_SEC + row * ROW_STAGGER_SEC + jitter,
        gain,
        clipId: chosen.id,
        tag: chosen.tag,
        col,
        row,
        seconds: chosen.seconds,
        line: chosen.line || '',
      });
    }
  }
  let end = 0;
  for (const event of events) end = Math.max(end, event.time + event.seconds);
  return { events, duration: end + TAIL_SEC, cols: COLS, rows: ROWS };
}

export function captionForColumn(events, col) {
  const inCol = events.filter((event) => event.col === col);
  if (!inCol.length) return '';
  inCol.sort((a, b) => b.gain - a.gain || a.row - b.row);
  return inCol[0].line || '';
}
