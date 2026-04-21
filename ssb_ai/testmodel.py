import google.generativeai as genai
import streamlit as st

genai.configure(api_key=st.secrets["GEMINI_API_KEY"])

print("--- Available Models ---")
for m in genai.list_models():
    if 'generateContent' in m.supported_generation_methods:
        print(m.name)