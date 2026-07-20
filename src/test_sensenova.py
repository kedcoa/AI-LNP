import os

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

api_key = os.getenv("SENSENOVA_API_KEY")

if not api_key:
    raise RuntimeError("SENSENOVA_API_KEY was not found in .env")

client = OpenAI(
    base_url="https://token.sensenova.cn/v1",
    api_key=api_key,
)

response = client.chat.completions.create(
    model="sensenova-6.7-flash-lite",
    messages=[
    	{
        	"role": "system",
        	"content": (
           	 "You are a scientific information extraction assistant. "
            	"Only use information provided by the user. "
            	"Do not invent missing information."
        	),
    	},
    	{
        	"role": "user",
        	"content": (
            	"Identify the payload and target organ in this sentence: "
            	"'The lipid nanoparticles delivered mRNA to the mouse liver.'"
        	),
    	},
],
)

print("SenseNova connection successful.")
print(response.choices[0].message.content)