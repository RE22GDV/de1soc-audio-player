# -*- coding: utf-8 -*-
"""Читання треку (mp3, wav, flac, ogg) і зміна частоти дискретизації."""
import numpy as np

try:
    import miniaudio
except ImportError:                      # pragma: no cover - підказка для користувача
    miniaudio = None


def _fast_len(n):
    """Найближча зверху довжина з множниками 2, 3, 5 — для швидкого FFT."""
    best = 1 << (n - 1).bit_length()
    p5 = 1
    while p5 < best:
        p35 = p5
        while p35 < best:
            p = p35
            while p < n:
                p *= 2
            best = min(best, p)
            p35 *= 3
        p5 *= 5
    return best


def _info(data):
    """Власні канали й частота файла. Формат визначається за вмістом."""
    head = data[:4]
    if head == b'OggS':
        return miniaudio.vorbis_get_info(data)
    if head == b'fLaC':
        return miniaudio.flac_get_info(data)
    if head == b'RIFF':
        return miniaudio.wav_get_info(data)
    return miniaudio.mp3_get_info(data)


def load(path):
    """Повертає (float32 [канали, відліки] у діапазоні -1..1, частота, тривалість, с).
    Файл читаємо самі: функції бібліотеки, що приймають шлях (decode_file, а для ogg
    і get_file_info), у Windows не відкривають шляхи кирилицею."""
    if miniaudio is None:
        raise RuntimeError('Немає бібліотеки miniaudio: запустіть run.bat, він її встановить.')
    with open(path, 'rb') as f:
        data = f.read()
    try:
        info = _info(data)
        # без явних каналів і частоти бібліотека робить із усього стерео 44,1 кГц
        snd = miniaudio.decode(data, output_format=miniaudio.SampleFormat.FLOAT32,
                               nchannels=info.nchannels, sample_rate=info.sample_rate)
    except miniaudio.DecodeError as e:
        raise ValueError('Не вдалося розкодувати трек. Підтримуються mp3, wav, flac '
                         'і ogg (Vorbis). Подробиці: %s' % (e,)) from e
    x = np.frombuffer(snd.samples, dtype=np.float32).reshape(-1, snd.nchannels).T.copy()
    return x, snd.sample_rate, snd.duration


def resample(x, src, dst):
    """Зміна частоти через FFT: спектр обрізається (або доповнюється нулями)
    до нової довжини — це водночас ідеальний фільтр проти накладання спектра."""
    if src == dst:
        return x.astype(np.float32)
    ch, n = x.shape
    m = int(round(n * dst / src))
    nf = _fast_len(n)
    # доповнення нулями до зручної для FFT довжини
    pad = np.zeros((ch, nf), dtype=np.float64)
    pad[:, :n] = x
    spec = np.fft.rfft(pad, axis=1)
    mf = int(round(nf * dst / src))
    keep = min(spec.shape[1], mf // 2 + 1)
    out_spec = np.zeros((ch, mf // 2 + 1), dtype=np.complex128)
    out_spec[:, :keep] = spec[:, :keep]
    y = np.fft.irfft(out_spec, n=mf, axis=1) * (mf / nf)
    return y[:, :m].astype(np.float32)


def prepare(path, rate, channels, start=0.0, length=None, normalize=True):
    """Трек -> int16 [канали, відліки] на потрібній частоті.
    Повертає (pcm, опис для журналу)."""
    x, sr, duration = load(path)
    a = int(max(0.0, start) * sr)
    b = x.shape[1] if not length else min(x.shape[1], a + int(length * sr))
    x = x[:, a:b]
    if x.shape[1] == 0:
        raise ValueError('Обраний фрагмент порожній')
    source_channels = int(x.shape[0])
    if channels == 1 and x.shape[0] > 1:
        x = x.mean(axis=0, keepdims=True)
    elif channels == 2 and x.shape[0] == 1:
        x = np.repeat(x, 2, axis=0)
    y = resample(x, sr, rate)
    peak = float(np.max(np.abs(y))) if y.size else 0.0
    gain = 1.0
    if normalize and peak > 0:
        gain = 0.891 / peak                     # пік -1 дБ від повної шкали
    elif peak > 1.0:
        gain = 1.0 / peak                       # лише захист від обмеження
    pcm = np.clip(np.round(y * gain * 32767.0), -32768, 32767).astype(np.int16)
    note = {
        'source_rate': sr, 'source_channels': source_channels, 'source_seconds': duration,
        'seconds': pcm.shape[1] / rate, 'gain_db': 20 * np.log10(gain) if gain > 0 else 0.0,
    }
    return pcm, note
