from inputaudio import AudioInput
from recognizer import AudioRecognition
from model_pipeline import Pipeline
import streamlit as st

# Initialize pipeline
pipeline = Pipeline()

# Streamlit UI
st.title("Smart Virtual Assistant - Dr Flash")

# Record and recognize input
if st.button("Ask anything "):
    st.write("Listening....")

    # Step 1: Record audio
    audio_input = AudioInput(duration=6)
    audio_input.record_audio()

    st.success("Audio captured successfully!")

    # Step 2: Recognize audio
    st.write("Recognizing input...")

    audio_recognition = AudioRecognition()
    question = audio_recognition.recognize_audio()

    if question:
        st.write(f"Your input/question: {question}")

        # Step 3: Process the recognized text to generate an answer
        answer = pipeline.generate_answer(question)
        st.header(f"Answer: {answer}")
        st.balloons()
    else:
        st.error("Sorry, could not recognize the audio. Please try again.")

# Instructions to the user
st.write("Click the 'Ask anything' button to record your voice and ask a question.")
