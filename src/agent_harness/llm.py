import os
import sys
import subprocess
from openai import OpenAI
from dotenv import load_dotenv
from .tools import TOOLS_SCHEMAS
load_dotenv()

client = OpenAI(
    #base_url=os.getenv("OPENAI_API_BASE"),
    api_key=os.getenv("OPENAI_API_KEY")
)

def call_llm(messages):
    response = client.chat.completions.create(
        model=os.getenv("OPENAI_MODEL", "ornith-1.5:9b"),
        messages=messages,
        tools=TOOLS_SCHEMAS,
        reasoning_effort='none'
    )

    output = response.choices[0].message
    completions_details = response.usage.completion_tokens_details
    prompt_details = response.usage.prompt_tokens_details

    usage = {
        "prompt_tokens": response.usage.prompt_tokens,
        "completion_tokens": response.usage.completion_tokens,
        "reasoning_tokens": getattr(completions_details, 'reasoning_tokens', None),
        "cached_tokens": getattr(completions_details, 'cached_tokens', None), 
    }

    return output, usage, prompt_details, completions_details