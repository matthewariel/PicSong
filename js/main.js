import { loadPack } from './pack.js';
import { buildSchedule, gridFromImageData } from './mapper.js';
import { playSchedule, playbackState, renderSchedule, stopPlayback } from './player.js';

const stage = document.querySelector('#stage');
const drop = document.querySelector('#drop');
const fileInput = document.querySelector('#file');
const empty = document.querySelector('#empty');
const photo = document.querySelector('#photo');
const preview = document.querySelector('#preview');
const song = document.querySelector('#song');
const playButton = document.querySelector('#play');
const progress = document.querySelector('#progress');
const progressFill = document.querySelector('#progress-fill');
const convertButton = document.querySelector('#convert');
const downloadButton = document.querySelector('#download');
const againButton = document.querySelector('#again');
const status = document.querySelector('#status');

let pack = null;
let imageData = null;
let sourcePixels = 0;
let schedule = null;
let objectUrl = null;
let imageToken = 0;
let playToken = 0;
let raf = 0;
let endTimer = 0;
let rendering = false;
let playing = false;
let phase = 'empty';
let photoLive = false;
let fromDisk = false;
let sourceHandle = null;
let sourceHandlePromise = Promise.resolve(null);

const packPromise = loadPack();
packPromise.then((loaded) => {
  pack = loaded;
  syncButtons();
}).catch(() => {
  setStatus('The soundboard did not show up. Reload the page.');
});

fileInput.addEventListener('change', () => {
  const file = fileInput.files && fileInput.files[0];
  fileInput.value = '';
  if (!file) return;
  if (isAudioFile(file)) {
    refuseMusic();
    return;
  }
  takeFile(file, null, true);
});

// A normal file input cannot delete the chosen file. The picker handle can.
let allowNativePicker = false;
if (typeof window.showOpenFilePicker === 'function') {
  fileInput.addEventListener('click', (event) => {
    if (allowNativePicker) return;
    event.preventDefault();
    choosePicture();
  });
}

againButton.addEventListener('click', () => {
  openNativePicker();
});

window.addEventListener('paste', (event) => {
  const file = imageFromClipboard(event.clipboardData);
  if (file) {
    event.preventDefault();
    takeFile(file, null, false);
    return;
  }
  if (audioFromClipboard(event.clipboardData)) {
    event.preventDefault();
    refuseMusic();
  }
});

window.addEventListener('dragover', (event) => {
  event.preventDefault();
  if (hasFiles(event.dataTransfer)) stage.classList.add('hot');
});

window.addEventListener('dragleave', (event) => {
  if (!event.relatedTarget) stage.classList.remove('hot');
});

window.addEventListener('drop', (event) => {
  event.preventDefault();
  stage.classList.remove('hot');
  const list = event.dataTransfer && event.dataTransfer.files;
  const image = firstImage(list);
  if (image) {
    takeFile(image, handleForDroppedFile(event.dataTransfer, image), true);
    return;
  }
  if (firstAudio(list)) {
    refuseMusic();
    return;
  }
  if (list && list.length) setStatus('That is not a picture.');
});

convertButton.addEventListener('click', () => {
  onConvert().catch(() => {
    if (phase === 'converting') phase = imageData ? 'held' : 'empty';
    setStatus('That picture would not become a sound.');
    syncButtons();
  });
});

playButton.addEventListener('click', () => {
  if (playing) {
    stopNow();
    return;
  }
  onPlay().catch(() => {
    playing = false;
    setPlaying(false);
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
  if (file.type && file.type.startsWith('audio/')) return false;
  if (file.type && file.type.startsWith('image/')) return true;
  return /\.(png|jpe?g|gif|webp|bmp|avif)$/i.test(file.name || '');
}

function isAudioFile(file) {
  if (!file) return false;
  if (file.type && file.type.startsWith('audio/')) return true;
  if (file.type && file.type.startsWith('image/')) return false;
  return /\.(mp3|wav|flac|ogg|oga|opus|m4a|aac|aiff?|wma|mid|midi|caf)$/i.test(file.name || '');
}

function firstAudio(fileList) {
  if (!fileList) return null;
  return [...fileList].find(isAudioFile) || null;
}

function refuseMusic() {
  setStatus("Can it turn your music into photos? No, it can't.");
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

function audioFromClipboard(data) {
  if (!data) return null;
  const items = data.items ? [...data.items] : [];
  for (const item of items) {
    if (item.kind === 'file' && item.type && item.type.startsWith('audio/')) {
      const file = item.getAsFile();
      if (file) return file;
    }
  }
  return firstAudio(data.files);
}

function handleForDroppedFile(dataTransfer, file) {
  if (!dataTransfer || !dataTransfer.items || !file) return null;
  try {
    const items = [...dataTransfer.items].filter((item) => item.kind === 'file');
    const match = items.length === 1
      ? items[0]
      : items.find((item) => {
        const asFile = item.getAsFile && item.getAsFile();
        return asFile && asFile.name === file.name && asFile.size === file.size;
      });
    if (!match || typeof match.getAsFileSystemHandle !== 'function') return null;
    return match.getAsFileSystemHandle();
  } catch {
    return null;
  }
}

function openNativePicker() {
  allowNativePicker = true;
  fileInput.click();
  allowNativePicker = false;
}

function choosePicture() {
  let picker;
  try {
    picker = window.showOpenFilePicker({
      multiple: false,
      id: 'picsong-photo',
      types: [{
        description: 'Pictures',
        accept: {
          'image/*': ['.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp', '.avif'],
        },
      }],
    });
  } catch {
    openNativePicker();
    return;
  }
  picker.then(async (handles) => {
    const handle = handles && handles[0];
    if (!handle || typeof handle.getFile !== 'function') return;
    const file = await handle.getFile();
    if (isAudioFile(file)) {
      refuseMusic();
      return;
    }
    takeFile(file, handle, true);
  }).catch((err) => {
    if (err && err.name === 'AbortError') return;
    openNativePicker();
  });
}

function rememberSource(disk, handleSource) {
  fromDisk = Boolean(disk);
  photoLive = true;
  const token = imageToken;
  sourceHandle = null;
  const pending = Promise.resolve(handleSource || null).then((handle) => {
    if (!handle || handle.kind === 'directory' || typeof handle.remove !== 'function') return null;
    return handle;
  }).catch(() => null);
  sourceHandlePromise = pending;
  pending.then((handle) => {
    if (token === imageToken && photoLive) sourceHandle = handle;
  });
}

// Asks for write access in this click, then deletes the file the user picked.
function removeUserFile(handle) {
  if (!handle || typeof handle.remove !== 'function') return Promise.resolve(false);
  const ask = typeof handle.requestPermission === 'function'
    ? handle.requestPermission({ mode: 'readwrite' })
    : Promise.resolve('granted');
  return ask.then((perm) => {
    if (perm !== 'granted') return false;
    return handle.remove().then(() => true);
  }).catch(() => false);
}

function beginFileRemoval() {
  if (!photoLive) return Promise.resolve({ disk: false, removed: false });
  const disk = fromDisk;
  const handleNow = sourceHandle;
  const pending = sourceHandlePromise;
  photoLive = false;
  fromDisk = false;
  sourceHandle = null;
  sourceHandlePromise = Promise.resolve(null);
  const removal = handleNow
    ? removeUserFile(handleNow)
    : pending.then((handle) => (handle ? removeUserFile(handle) : false));
  return Promise.resolve(removal).catch(() => false).then((removed) => ({
    disk,
    removed: Boolean(removed),
  }));
}

function clearDissolve() {
  const canvas = photo.querySelector('.dissolve');
  if (canvas && canvas._cancel) canvas._cancel();
  if (canvas) canvas.remove();
}

function clearPhotoVisual() {
  clearDissolve();
  preview.classList.remove('fading');
  preview.style.visibility = '';
  if (objectUrl) {
    URL.revokeObjectURL(objectUrl);
    objectUrl = null;
  }
  preview.removeAttribute('src');
  preview.alt = '';
}

function motionOK() {
  return !window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

function wait(ms) {
  return new Promise((resolve) => {
    setTimeout(resolve, ms);
  });
}

function removalAmount(elapsed, row) {
  const stagger = 14;
  const fade = 100;
  const t = (elapsed - row * stagger) / fade;
  if (t <= 0) return 0;
  if (t >= 1) return 1;
  return t * t * (3 - 2 * t);
}

function animateDelete(token) {
  if (!preview.src || !photo.isConnected) return wait(0);
  const width = preview.offsetWidth;
  const height = preview.offsetHeight;
  if (!motionOK() || !width || !height) {
    preview.classList.add('fading');
    return wait(240);
  }
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  const canvas = document.createElement('canvas');
  canvas.className = 'dissolve';
  canvas.width = Math.max(1, Math.round(width * dpr));
  canvas.height = Math.max(1, Math.round(height * dpr));
  canvas.style.left = `${preview.offsetLeft}px`;
  canvas.style.top = `${preview.offsetTop}px`;
  canvas.style.width = `${width}px`;
  canvas.style.height = `${height}px`;
  const ctx = canvas.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.drawImage(preview, 0, 0, width, height);
  const snapshot = document.createElement('canvas');
  snapshot.width = canvas.width;
  snapshot.height = canvas.height;
  snapshot.getContext('2d').drawImage(canvas, 0, 0);

  const rows = Math.round(Math.max(32, Math.min(64, height / 4)));
  const rowH = height / rows;
  const total = 14 * (rows - 1) + 100;
  let frame = 0;
  let cancelled = false;
  canvas._cancel = () => {
    cancelled = true;
    cancelAnimationFrame(frame);
  };
  preview.style.visibility = 'hidden';
  photo.appendChild(canvas);

  return new Promise((resolve) => {
    let origin = 0;
    const paint = (now) => {
      if (cancelled || token !== imageToken) {
        canvas.remove();
        resolve();
        return;
      }
      if (!origin) origin = now;
      const elapsed = now - origin;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, width, height);
      ctx.drawImage(snapshot, 0, 0, snapshot.width, snapshot.height, 0, 0, width, height);
      ctx.globalCompositeOperation = 'destination-out';
      for (let i = 0; i < rows; i += 1) {
        const gone = removalAmount(elapsed, i);
        if (gone <= 0) continue;
        const y = i * rowH;
        const gradient = ctx.createLinearGradient(0, y, 0, y + rowH);
        gradient.addColorStop(0, `rgba(0,0,0,${gone})`);
        gradient.addColorStop(1, `rgba(0,0,0,${removalAmount(elapsed, i + 1)})`);
        ctx.fillStyle = gradient;
        ctx.fillRect(0, y, width, rowH + 0.75);
      }
      ctx.globalCompositeOperation = 'source-over';
      if (elapsed < total) frame = requestAnimationFrame(paint);
      else {
        canvas.remove();
        resolve();
      }
    };
    frame = requestAnimationFrame(paint);
  });
}

function setStatus(text) {
  status.textContent = text;
}

function setPlaying(active) {
  playButton.classList.toggle('is-playing', active);
  playButton.setAttribute('aria-label', active ? 'Stop the sound' : 'Play the sound');
}

function paintProgress(amount) {
  const value = Math.min(1, Math.max(0, amount || 0));
  progressFill.style.transform = `scaleX(${value})`;
  progress.setAttribute('aria-valuenow', String(Math.round(value * 100)));
}

function syncButtons() {
  const held = phase === 'held' && Boolean(imageData && pack);
  convertButton.hidden = phase !== 'held' && phase !== 'converting';
  convertButton.disabled = !held;
  convertButton.textContent = phase === 'converting' ? 'Converting…' : 'Convert to sound';
  const ready = phase === 'song' && Boolean(schedule && pack);
  playButton.disabled = !ready;
  downloadButton.hidden = !ready;
  downloadButton.disabled = !ready || rendering;
  againButton.hidden = phase !== 'song';
  song.hidden = phase !== 'song';
  drop.hidden = phase === 'song';
  empty.hidden = phase !== 'empty';
  photo.hidden = phase === 'empty' || phase === 'song';
  stage.classList.toggle('has-photo', phase === 'held' || phase === 'converting');
  stage.classList.toggle('has-song', phase === 'song');
  stage.classList.toggle('converting', phase === 'converting');
  if (phase !== 'held' && phase !== 'converting') stage.classList.remove('hot');
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
  sourcePixels = sourceW * sourceH;
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
  schedule = buildSchedule(gridFromImageData(imageData), clipsForSchedule(), sourcePixels);
}

async function takeFile(file, handleSource = null, disk = false) {
  if (isAudioFile(file)) {
    refuseMusic();
    return;
  }
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
  haltPlayback();
  clearDissolve();
  preview.classList.remove('fading');
  preview.style.visibility = '';
  preview.hidden = true;
  schedule = null;
  imageData = null;
  phase = 'held';
  paintProgress(0);
  syncButtons();
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
    preview.alt = 'The picture to convert';
    imageData = drawToImageData(decoded.img);
    schedule = null;
    phase = 'held';
    rememberSource(disk, handleSource);
    syncButtons();
    try {
      pack = await packPromise;
    } catch {
      pack = null;
    }
    if (token !== imageToken) return;
    syncButtons();
    setStatus(pack ? 'Picture received.' : 'The soundboard did not show up. Reload the page.');
  } catch {
    if (token !== imageToken) return;
    phase = 'empty';
    syncButtons();
    setStatus('That file would not become a picture.');
  }
}

function haltPlayback() {
  playToken += 1;
  playing = false;
  cancelAnimationFrame(raf);
  clearTimeout(endTimer);
  stopPlayback();
  setPlaying(false);
  paintProgress(0);
}

function stopNow() {
  haltPlayback();
}

async function onConvert() {
  if (phase !== 'held' || !imageData || !pack) return;
  const token = imageToken;
  phase = 'converting';
  syncButtons();
  rebuildSchedule();
  if (!schedule) throw new Error('empty');
  imageData = null;
  const removal = beginFileRemoval();
  await animateDelete(token);
  if (token !== imageToken) return;
  await removal;
  if (token !== imageToken) return;
  phase = 'song';
  clearPhotoVisual();
  syncButtons();
  setStatus('Your image has been (permanently) converted to music.');
}

async function onPlay() {
  if (!schedule || !pack || phase !== 'song') return;
  const token = playToken + 1;
  playToken = token;
  cancelAnimationFrame(raf);
  clearTimeout(endTimer);
  playing = true;
  setPlaying(true);
  paintProgress(0);
  const handle = await playSchedule(pack.pcms, schedule);
  if (!handle || token !== playToken) return;
  const step = () => {
    if (token !== playToken) return;
    const state = playbackState();
    if (!state) return;
    const elapsed = Math.max(0, state.currentTime - state.startedAt);
    paintProgress(elapsed / schedule.duration);
    if (elapsed >= schedule.duration) {
      finishPlayback(token);
      return;
    }
    raf = requestAnimationFrame(step);
  };
  raf = requestAnimationFrame(step);
  clearTimeout(endTimer);
  endTimer = setTimeout(() => finishPlayback(token), schedule.duration * 1000 + 180);
}

function finishPlayback(token) {
  if (token !== playToken) return;
  playing = false;
  cancelAnimationFrame(raf);
  clearTimeout(endTimer);
  stopPlayback();
  setPlaying(false);
  paintProgress(1);
}

async function onDownload() {
  if (!schedule || !pack || rendering || phase !== 'song') return;
  rendering = true;
  syncButtons();
  setStatus('Writing the WAV.');
  try {
    const blob = await renderSchedule(pack.pcms, schedule);
    if (!blob || blob.size < 44) throw new Error('empty');
    saveBlob(blob, 'picsong.wav');
    setStatus(playing ? 'Playing.' : 'Saved. You can play it for someone you dislike.');
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
