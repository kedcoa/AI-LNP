import os

from dotenv import load_dotenv

load_dotenv()

api_key = os.getenv("OPENAI_API_KEY")

if api_key:
    print("Success: OPENAI_API_KEY was loaded.")
else:
    print("Error: OPENAI_API_KEY was not found.")