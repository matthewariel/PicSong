// Live playback and the WAV download share this graph and this schedule.

import { encodeWav } from './wav.js';

const MASTER_GAIN = 0.22;
let context = null;
let liveBuffers = null;
let last = null;
let request = 0;

function buffersFor(ctx, pcms) {
  const map = new Map();
  for (const [id, pcm] of pcms) {
    const buffer = ctx.createBuffer(1, pcm.samples.length, pcm.sampleRate);
    if (typeof buffer.copyToChannel === 'function') buffer.copyToChannel(pcm.samples, 0);
    else buffer.getChannelData(0).set(pcm.samples);
    map.set(id, buffer);
  }
  return map;
}

function buildGraph(ctx, destination, buffers, events, timeOffset) {
  const master = ctx.createGain();
  master.gain.setValueAtTime(MASTER_GAIN, 0);
  master.connect(destination);
  const sources = [];
  for (const event of events) {
    const buffer = buffers.get(event.clipId);
    if (!buffer) continue;
    const source = ctx.createBufferSource();
    source.buffer = buffer;
    const gain = ctx.createGain();
    gain.gain.setValueAtTime(event.gain, 0);
    source.connect(gain);
    gain.connect(master);
    source.start(timeOffset + event.time);
    sources.push(source);
  }
  return { sources, master };
}

export function stopPlayback() {
  if (!last) return;
  try {
    last.master.disconnect();
  } catch {
    // Already disconnected.
  }
  for (const source of last.sources) {
    try {
      source.stop();
    } catch {
      // Already stopped.
    }
  }
  last = null;
}

export async function playSchedule(pcms, schedule) {
  const AudioCtx = window.AudioContext || window.webkitAudioContext;
  if (!AudioCtx) throw new Error('This browser has no Web Audio');
  const mine = request + 1;
  request = mine;
  stopPlayback();
  if (!context) context = new AudioCtx();
  if (context.state === 'suspended') await context.resume();
  if (mine !== request) return null;
  if (!liveBuffers || liveBuffers.ctx !== context) {
    liveBuffers = { ctx: context, buffers: buffersFor(context, pcms) };
  }
  const startedAt = context.currentTime + 0.06;
  const graph = buildGraph(context, context.destination, liveBuffers.buffers, schedule.events, startedAt);
  last = {
    context,
    startedAt,
    sources: graph.sources,
    master: graph.master,
    duration: schedule.duration,
  };
  return last;
}

export function playbackState() {
  if (!last) return null;
  return {
    state: last.context.state,
    currentTime: last.context.currentTime,
    startedAt: last.startedAt,
    sourceCount: last.sources.length,
    duration: last.duration,
  };
}

export async function renderSchedule(pcms, schedule) {
  const Offline = window.OfflineAudioContext || window.webkitOfflineAudioContext;
  if (!Offline) throw new Error('This browser cannot write a WAV');
  const rate = 44100;
  const frames = Math.max(1, Math.ceil(schedule.duration * rate));
  const offline = new Offline(1, frames, rate);
  const buffers = buffersFor(offline, pcms);
  buildGraph(offline, offline.destination, buffers, schedule.events, 0);
  const audio = await offline.startRendering();
  const mix = audio.numberOfChannels === 1
    ? audio.getChannelData(0)
    : mixdown(audio);
  return encodeWav(mix, audio.sampleRate);
}

function mixdown(audio) {
  const frames = audio.length;
  const mixed = new Float32Array(frames);
  const channels = audio.numberOfChannels;
  for (let channel = 0; channel < channels; channel += 1) {
    const data = audio.getChannelData(channel);
    for (let i = 0; i < frames; i += 1) mixed[i] += data[i] / channels;
  }
  return mixed;
}
