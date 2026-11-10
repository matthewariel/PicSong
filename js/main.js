import { loadPack } from './pack.js';
import {
  BEAT_SEC,
  COLS,
  buildSchedule,
  captionForColumn,
  gridFromImageData,
} from './mapper.js';
import { playSchedule, playbackState, renderSchedule, stopPlayback } from './player.js';

const drop = document.querySelector('#drop');
const fileInput = document.querySelector('#file');
const dropTitle = document.querySelector('#drop-title');
const dropHint = document.querySelector('#drop-hint');
const preview = document.querySelector('#preview');
const playButton = document.querySelector('#play');
const downloadButton = document.querySelector('#download');
const fill = document.querySelector('#fill');
const meter = document.querySelector('#meter');
const caption = document.querySelector('#caption');
const status = document.querySelector('#status');

let pack = null;
let imageData = null;
let schedule = null;
let objectUrl = null;
let imageToken = 0;
let playToken = 0;
let raf = 0;
let endTimer = 0;
let rendering = false;
let playing = false;
let lastColumn = -1;

const packPromise = loadPack();
packPromise.then((loaded) => {
  pack = loaded;
  if (!schedule) setStatus('Drop a picture. Any picture. It will not be improved.');
  syncButtons();
}).catch(() => {
  setStatus('The soundboard did not show up. Reload the page.');
});

paintMeter(0, 1, true);
setCaption('Sixteen beats. Four rows. No song.');

fileInput.addEventListener('change', () => {
  const file = fileInput.files && fileInput.files[0];
  if (file) takeFile(file);
  fileInput.value = '';
});

window.addEventListener('paste', (event) => {
  const file = imageFromClipboard(event.clipboardData);
  if (!file) return;
  event.preventDefault();
  takeFile(file);
});

window.addEventListener('dragover', (event) => {
  event.preventDefault();
  if (hasFiles(event.dataTransfer)) drop.classList.add('hot');
});

window.addEventListener('dragleave', (event) => {
  if (!event.relatedTarget) drop.classList.remove('hot');
});

window.addEventListener('drop', (event) => {
  event.preventDefault();
  drop.classList.remove('hot');
  const file = firstImage(event.dataTransfer && event.dataTransfer.files);
  if (file) takeFile(file);
  else if (event.dataTransfer && event.dataTransfer.files && event.dataTransfer.files.length) {
    setStatus('That is not a picture.');
  }
});

playButton.addEventListener('click', () => {
  onPlay().catch(() => {
    playing = false;
    setPlayLabel(false);
    setStatus('The soundboard would not start.');
    syncButtons();
  });
});

downloadButton.addEventListener('click', () => {
  onDownload().catch(() => {
    rendering = false;
    setStatus('The WAV did not come out.');
    syncButtons();
  });
});

function hasFiles(dataTransfer) {
  if (!dataTransfer || !dataTransfer.types) return false;
  return [...dataTransfer.types].includes('Files');
}

function isImageFile(file) {
  if (!file) return false;
  if (file.type && file.type.startsWith('image/')) return true;
  return /\.(png|jpe?g|gif|webp|bmp|avif)$/i.test(file.name || '');
}

function firstImage(fileList) {
  if (!fileList) return null;
  return [...fileList].find(isImageFile) || null;
}

function imageFromClipboard(data) {
  if (!data) return null;
  const items = data.items ? [...data.items] : [];
  for (const item of items) {
    if (item.kind === 'file' && item.type && item.type.startsWith('image/')) {
      const file = item.getAsFile();
      if (file) return file;
    }
  }
  return firstImage(data.files);
}

function setStatus(text) {
  status.textContent = text;
}

function setCaption(text) {
  caption.textContent = text;
}

function setPlayLabel(active) {
  playButton.textContent = active ? 'Mash it again' : 'Mash the soundboard';
}

function syncButtons() {
  const ready = Boolean(schedule && pack);
  playButton.disabled = !ready;
  downloadButton.disabled = !ready || rendering;
}

function decodeImage(file) {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => resolve({ img, url });
    img.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error('unreadable'));
    };
    img.src = url;
  });
}

function drawToImageData(img) {
  const sourceW = img.naturalWidth || img.width;
  const sourceH = img.naturalHeight || img.height;
  if (!sourceW || !sourceH) throw new Error('empty');
  const maxEdge = 4096;
  let width = sourceW;
  let height = sourceH;
  if (width > maxEdge || height > maxEdge) {
    const scale = maxEdge / Math.max(width, height);
    width = Math.max(1, Math.round(width * scale));
    height = Math.max(1, Math.round(height * scale));
  }
  const canvas = document.createElement('canvas');
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext('2d', { willReadFrequently: true });
  ctx.fillStyle = '#ffffff';
  ctx.fillRect(0, 0, width, height);
  ctx.imageSmoothingEnabled = true;
  ctx.drawImage(img, 0, 0, width, height);
  return ctx.getImageData(0, 0, width, height);
}

function clipsForSchedule() {
  return pack.manifest.clips.map((clip) => {
    const pcm = pack.pcms.get(clip.id);
    if (!pcm) throw new Error(`Missing ${clip.id}`);
    return {
      id: clip.id,
      tag: clip.tag,
      line: clip.line,
      seconds: pcm.samples.length / pcm.sampleRate,
    };
  });
}

function rebuildSchedule() {
  if (!imageData || !pack) {
    schedule = null;
    return;
  }
  schedule = buildSchedule(gridFromImageData(imageData), clipsForSchedule());
}

async function takeFile(file) {
  if (!isImageFile(file)) {
    setStatus('That is not a picture.');
    return;
  }
  if (file.size > 40 * 1024 * 1024) {
    setStatus('That picture is too heavy to lift.');
    return;
  }
  const token = imageToken + 1;
  imageToken = token;
  setStatus('Looking at the picture…');
  try {
    const decoded = await decodeImage(file);
    if (token !== imageToken) {
      URL.revokeObjectURL(decoded.url);
      return;
    }
    if (objectUrl) URL.revokeObjectURL(objectUrl);
    objectUrl = decoded.url;
    preview.src = objectUrl;
    preview.hidden = false;
    preview.alt = 'The picture PicSong will mash';
    dropTitle.textContent = 'This is the picture.';
    dropHint.textContent = 'Drop, paste, or tap to swap it.';
    imageData = drawToImageData(decoded.img);
    haltPlayback();
    try {
      pack = await packPromise;
    } catch {
      setStatus('The soundboard did not show up. Reload the page.');
      return;
    }
    if (token !== imageToken) return;
    rebuildSchedule();
    lastColumn = -1;
    playing = false;
    setPlayLabel(false);
    paintMeter(0, schedule.duration, true);
    setCaption('Sixteen beats. Four rows. No song.');
    setStatus('Picture received. The soundboard is armed.');
    syncButtons();
  } catch {
    if (token !== imageToken) return;
    setStatus('That file would not become a picture.');
  }
}

function haltPlayback() {
  playToken += 1;
  playing = false;
  cancelAnimationFrame(raf);
  clearTimeout(endTimer);
  stopPlayback();
}

async function onPlay() {
  if (!schedule || !pack) return;
  const token = playToken + 1;
  playToken = token;
  cancelAnimationFrame(raf);
  clearTimeout(endTimer);
  playing = true;
  lastColumn = -1;
  setPlayLabel(true);
  setStatus('Mashing the soundboard.');
  paintMeter(0, schedule.duration, true);
  const handle = await playSchedule(pack.pcms, schedule);
  if (!handle || token !== playToken) return;
  const step = () => {
    if (token !== playToken) return;
    const state = playbackState();
    if (!state) return;
    const elapsed = Math.max(0, state.currentTime - state.startedAt);
    paintMeter(elapsed, schedule.duration, false);
    if (elapsed >= schedule.duration) {
      finishPlayback(token);
      return;
    }
    raf = requestAnimationFrame(step);
  };
  raf = requestAnimationFrame(step);
  clearTimeout(endTimer);
  endTimer = setTimeout(() => finishPlayback(token), schedule.duration * 1000 + 180);
  return handle;
}

function finishPlayback(token) {
  if (token !== playToken) return;
  playing = false;
  cancelAnimationFrame(raf);
  clearTimeout(endTimer);
  if (schedule) paintMeter(schedule.duration, schedule.duration, false);
  setPlayLabel(false);
  setCaption('That was the song. There is no second verse.');
  setStatus('The mash is over.');
}

function paintMeter(elapsed, duration, idle) {
  const amount = idle || !duration ? 0 : Math.min(1, Math.max(0, elapsed / duration));
  fill.style.transform = `scaleX(${amount})`;
  meter.setAttribute('aria-valuenow', String(Math.round(amount * 100)));
  if (idle || !schedule) return;
  const column = Math.floor(elapsed / BEAT_SEC);
  if (elapsed >= duration) return;
  if (column >= COLS) {
    if (lastColumn !== COLS) {
      lastColumn = COLS;
      setCaption('Letting the last bonk finish.');
    }
    return;
  }
  if (column !== lastColumn && column >= 0) {
    lastColumn = column;
    setCaption(captionForColumn(schedule.events, column));
  }
}

async function onDownload() {
  if (!schedule || !pack || rendering) return;
  rendering = true;
  syncButtons();
  setStatus('Writing the WAV. Same mash, now a file.');
  try {
    const blob = await renderSchedule(pack.pcms, schedule);
    if (!blob || blob.size < 44) throw new Error('empty');
    saveBlob(blob, 'picsong.wav');
    setStatus(playing ? 'Mashing the soundboard.' : 'Saved. You can play it for someone you dislike.');
  } catch (err) {
    setStatus('The WAV did not come out.');
    throw err;
  } finally {
    rendering = false;
    syncButtons();
  }
}

function saveBlob(blob, filename) {
  const link = document.createElement('a');
  const url = URL.createObjectURL(blob);
  link.href = url;
  link.download = filename;
  link.rel = 'noopener';
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 4000);
}
