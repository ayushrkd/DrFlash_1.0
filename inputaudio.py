import pyaudio
import wave

class AudioInput:
    def __init__(self, duration=10, filename="recorded_audio.wav"):
        self.duration = duration
        self.filename = filename
        self.audio = pyaudio.PyAudio()

    def record_audio(self):
        FORMAT = pyaudio.paInt16
        CHANNELS = 1
        RATE = 16000
        CHUNK = 1024

        stream = self.audio.open(format=FORMAT, channels=CHANNELS, rate=RATE, input=True, frames_per_buffer=CHUNK)

        frames = []

        for _ in range(0, int(RATE / CHUNK * self.duration)):
            data = stream.read(CHUNK)
            frames.append(data)

        stream.stop_stream()
        stream.close()

        wf = wave.open(self.filename, 'wb')
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(self.audio.get_sample_size(FORMAT))
        wf.setframerate(RATE)
        wf.writeframes(b''.join(frames))
        wf.close()

    def terminate(self):
        self.audio.terminate()
