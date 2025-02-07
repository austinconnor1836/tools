# transcribe.py
import sys
import whisper
import os
import warnings

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=UserWarning)

# Ensure UTF-8 encoding (Fixes UnicodeEncodeError on Windows)
sys.stdout.reconfigure(encoding='utf-8')


def transcribe(audio_file):
    """Transcribes an audio file using Whisper and returns the text."""
    model = whisper.load_model("base")
    result = model.transcribe(audio_file)
    return result["text"]


def save_transcription(text, file_path):
    """Saves the transcription text to a specified file path."""
    with open(file_path, "w", encoding="utf-8") as file:
        file.write(text)
    print(f"✅ Transcription saved to {file_path}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Please provide the audio file path")
        sys.exit(1)

    audio_file = sys.argv[1]

    # Ensure output directory exists
    output_dir = "./output/transcriptions"
    os.makedirs(output_dir, exist_ok=True)

    # Extract filename and determine transcription file path
    file_name = os.path.splitext(os.path.basename(audio_file))[0] + ".txt"
    transcription_file = os.path.join(output_dir, file_name)

    # Check if transcription already exists
    if os.path.exists(transcription_file):
        print(f"📂 Transcription already exists: {transcription_file}")
        print("✅ Using existing transcription.")
    else:
        # Transcribe and save if file doesn't exist
        print("🎤 Transcribing audio...")
        transcription = transcribe(audio_file)
        save_transcription(transcription, transcription_file)
    
    # Print the transcription file path for downstream processes
    print(transcription_file)
