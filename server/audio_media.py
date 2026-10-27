"""Normalize media to native PCM, retaining video timeline offsets for ASR."""

import wave


def to_wav(source, target, *, sample_rate, check, preserve_timeline=False):
    import av

    total = 0
    resampler = av.AudioResampler(format="s16", layout="mono", rate=sample_rate)
    with av.open(str(source)) as container, wave.open(str(target), "wb") as output:
        if not container.streams.audio:
            raise ValueError("The uploaded media has no audio track")
        stream = container.streams.audio[0]
        origin = round((container.start_time or 0) / av.time_base * sample_rate)
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)

        def write(pcm):
            nonlocal total
            check()
            start = total
            if preserve_timeline and pcm.pts is not None and pcm.time_base is not None:
                start = round(pcm.pts * pcm.time_base * sample_rate) - origin
            if start + pcm.samples > 7200 * sample_rate:
                raise ValueError("The audio timeline exceeds the two-hour limit")
            # Preserve leading silence/discontinuities so word timestamps match
            # playback in the original video instead of a compacted audio track.
            while start > total:
                check()
                count = min(start - total, 64 * 1024)
                output.writeframesraw(bytes(count * 2))
                total += count
            skip = min(pcm.samples, max(0, total - start))
            if skip < pcm.samples:
                output.writeframesraw(pcm.to_ndarray().tobytes()[skip * 2 :])
                total += pcm.samples - skip

        for frame in container.decode(stream):
            check()
            for pcm in resampler.resample(frame):
                write(pcm)
        for pcm in resampler.resample(None):
            write(pcm)
    if not total:
        raise ValueError("The uploaded media has no decoded audio samples")
    return total / sample_rate


def wav_info(data):
    import io

    with wave.open(io.BytesIO(data)) as audio:
        seconds = audio.getnframes() / audio.getframerate()
        if seconds <= 0:
            raise ValueError("audio.cpp returned an empty waveform")
        return seconds, audio.getframerate()
