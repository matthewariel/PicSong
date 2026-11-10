import { decodeWav } from './wav.js';

const manifestUrl = new URL('../sounds/manifest.json', import.meta.url);

export async function loadPack() {
  const response = await fetch(manifestUrl);
  if (!response.ok) throw new Error('The soundboard list did not load');
  const manifest = await response.json();
  if (!manifest.clips || manifest.clips.length < 40) {
    throw new Error('The soundboard is short a few honks');
  }
  const pcms = new Map();
  await Promise.all(manifest.clips.map(async (clip) => {
    const url = new URL(`../sounds/${clip.file}`, import.meta.url);
    const audio = await fetch(url);
    if (!audio.ok) throw new Error(`Missing ${clip.file}`);
    pcms.set(clip.id, decodeWav(await audio.arrayBuffer()));
  }));
  return { manifest, pcms };
}
