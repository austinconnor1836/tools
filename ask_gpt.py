import sys
import json
from openai import OpenAI
import os
import re

# Ensure UTF-8 encoding (fixes 'charmap' codec errors on Windows)
sys.stdout.reconfigure(encoding='utf-8')

# Ensure API key is set
api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    print(json.dumps({"error": "Missing OPENAI_API_KEY. Set it as an environment variable."}))
    sys.exit(1)

# Ensure the output directory exists
output_dir = "./output/transcriptions"
os.makedirs(output_dir, exist_ok=True)

# Ensure the correct transcription file is used
if len(sys.argv) < 2:
    print(json.dumps({"error": "Please provide the video file path."}))
    sys.exit(1)

video_file = sys.argv[1]
transcription_filename = os.path.splitext(os.path.basename(video_file))[0] + ".txt"
transcription_file = os.path.join(output_dir, transcription_filename)

if not os.path.exists(transcription_file):
    print(json.dumps({"error": f"Transcription file not found: {transcription_file}"}))
    sys.exit(1)

# Read transcription content
with open(transcription_file, "r", encoding="utf-8") as file:
    transcription_text = file.read().strip()

# Call OpenAI GPT-4 API
try:
    client = OpenAI()  # Use OpenAI client

    
    completion = client.chat.completions.create(
        model="gpt-4",
        messages=[
            {"role": "system", "content": "You are a helpful assistant."},
            {
                "role": "user",
                "content": "Write a haiku about recursion in programming."
            }
        ]
    )
    print(completion)

    # Extract only the content from the GPT response
    return completion.choices[0].message.content.strip()

    # # Print for debugging
    # print("🔍 **GPT Raw Response:**")
    # print(generated_text)

    # # Try to extract JSON from triple backticks
    # json_match = re.search(r"```json\n(.*?)\n```", generated_text, re.DOTALL)

    # if json_match:
    #     json_string = json_match.group(1).strip()
    # else:
    #     # Fallback: Try extracting JSON without triple backticks
    #     json_match_fallback = re.search(r"({.*})", generated_text, re.DOTALL)
    #     if json_match_fallback:
    #         json_string = json_match_fallback.group(1).strip()
    #     else:
    #         print(json.dumps({"error": "GPT did not return valid JSON, even in fallback."}))
    #         sys.exit(1)

    # # Validate and print the extracted JSON
    # try:
    #     generated_json = json.loads(json_string)
    #     print(json.dumps(generated_json, ensure_ascii=False))  # Print clean JSON output
    # except json.JSONDecodeError:
    #     print(json.dumps({"error": "Extracted text is not valid JSON."}))
    #     sys.exit(1)

except Exception as e:
    print(json.dumps({"error": str(e)}))
    sys.exit(1)
