# import tensorflow
import torch
# from tensorflow import keras
from transformers import pipeline
class Pipeline:
    def __init__(self):
        self.pipe = pipeline("text2text-generation", model="google/flan-t5-base")


    def generate_answer(self, question):
        ans=self.pipe(question)
        # Placeholder for actual processing; replace with your implementation
        # You might want to integrate your model here
        print(f"your question:    {question}")
        answer = f"dr.flash answer for you: {ans[0]["generated_text"]}"
        return ans[0]["generated_text"]


    # Use a pipeline as a high-level helper

