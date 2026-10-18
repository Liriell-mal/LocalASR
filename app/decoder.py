"""Bounded direct PyAV decoding of a read-only media handle, no subprocess."""
import wave

SAMPLE_RATE = 16000


def decode_media(source, destination, limit_seconds=None):
    import av
    import numpy as np

    limit = None if limit_seconds is None else int(limit_seconds * SAMPLE_RATE)
    count = 0
    resampler = av.audio.resampler.AudioResampler(format="s16", layout="mono", rate=SAMPLE_RATE)
    # Pass an already-open local handle, and restrict nested native protocols.
    with destination.open("xb") as output, wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        with av.open(source, mode="r", metadata_errors="ignore", options={"protocol_whitelist": "file,pipe"}) as container:
            if not container.streams.audio:
                raise ValueError("NO_AUDIO_STREAM")

            def consume(frame):
                nonlocal count
                pcm = frame.to_ndarray().reshape(-1)
                if limit is not None:
                    pcm = pcm[:max(0, limit - count)]
                wav.writeframesraw(pcm.astype("<i2", copy=False).tobytes())
                count += pcm.size

            for frame in container.decode(audio=0):
                frame.pts = None
                for chunk in resampler.resample(frame):
                    consume(chunk)
                if limit is not None and count >= limit:
                    break
            else:
                for chunk in resampler.resample(None):
                    consume(chunk)
    if not count:
        raise ValueError("EMPTY_AUDIO")
    with wave.open(str(destination), "rb") as wav:
        samples = np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2").astype(np.float32) / 32768.0
    return samples, count / SAMPLE_RATE
