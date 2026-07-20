from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

client = OpenAI()

response = client.responses.create(
    model="gpt-4.1-mini",
    input=(
        "In one sentence, explain what a lipid nanoparticle does "
        "in an mRNA delivery system."
    ),
)

print("OpenAI connection successful.")
print(response.output_text)
