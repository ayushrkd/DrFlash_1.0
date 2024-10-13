import speech_recognition as sr

class AudioRecognition:
    def __init__(self, filename="recorded_audio.wav"):
        self.filename = filename
        self.recognizer = sr.Recognizer()

    def recognize_audio(self):
        with sr.AudioFile(self.filename) as source:
            audio = self.recognizer.record(source)

            try:
                text = self.recognizer.recognize_google(audio)
                return text
            except sr.UnknownValueError:
                return "Speech could not be recognized."
            except sr.RequestError as e:
                return f"Request to recognition service failed: {e}"
