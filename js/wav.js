// 16-bit PCM WAV, the only audio format PicSong ships and downloads.

export function decodeWav(arrayBuffer) {
  const view = new DataView(arrayBuffer);
  const text = (offset, length) => {
    let out = '';
    for (let i = 0; i < length; i += 1) out += String.fromCharCode(view.getUint8(offset + i));
    return out;
  };
  if (arrayBuffer.byteLength < 44 || text(0, 4) !== 'RIFF' || text(8, 4) !== 'WAVE') {
    throw new Error('Not a WAV file');
  }

  let offset = 12;
  let audioFormat = 0;
  let channels = 0;
  let sampleRate = 0;
  let bits = 0;
  let dataOffset = -1;
  let dataSize = 0;

  while (offset + 8 <= view.byteLength) {
    const id = text(offset, 4);
    const size = view.getUint32(offset + 4, true);
    const start = offset + 8;
    if (id === 'fmt ') {
      audioFormat = view.getUint16(start, true);
      channels = view.getUint16(start + 2, true);
      sampleRate = view.getUint32(start + 4, true);
      bits = view.getUint16(start + 14, true);
    } else if (id === 'data') {
      dataOffset = start;
      dataSize = size;
      break;
    }
    offset = start + size + (size % 2);
  }

  if (audioFormat !== 1 || bits !== 16 || channels < 1 || sampleRate < 8000) {
    throw new Error('Need 16-bit PCM');
  }
  if (dataOffset < 0) throw new Error('WAV has no data');

  const frameBytes = channels * 2;
  const available = Math.max(0, view.byteLength - dataOffset);
  const frames = Math.floor(Math.min(dataSize, available) / frameBytes);
  const samples = new Float32Array(frames);
  let cursor = dataOffset;
  for (let i = 0; i < frames; i += 1) {
    let acc = 0;
    for (let channel = 0; channel < channels; channel += 1) {
      acc += view.getInt16(cursor, true);
      cursor += 2;
    }
    samples[i] = acc / channels / 32768;
  }
  return { sampleRate, samples };
}

export function encodeWav(samples, sampleRate) {
  const frames = samples.length;
  const buffer = new ArrayBuffer(44 + frames * 2);
  const view = new DataView(buffer);
  const write = (offset, value) => {
    for (let i = 0; i < value.length; i += 1) view.setUint8(offset + i, value.charCodeAt(i));
  };

  write(0, 'RIFF');
  view.setUint32(4, 36 + frames * 2, true);
  write(8, 'WAVE');
  write(12, 'fmt ');
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  write(36, 'data');
  view.setUint32(40, frames * 2, true);

  let offset = 44;
  for (let i = 0; i < frames; i += 1) {
    const clamped = Math.max(-1, Math.min(1, samples[i]));
    const int = clamped < 0 ? Math.round(clamped * 0x8000) : Math.round(clamped * 0x7fff);
    view.setInt16(offset, int, true);
    offset += 2;
  }
  return new Blob([buffer], { type: 'audio/wav' });
}
