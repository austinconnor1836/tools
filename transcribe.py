# transcribe.py
import sys
import whisper
import warnings
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=UserWarning)


def transcribe(audio_file):
    model = whisper.load_model("base")
    result = model.transcribe(audio_file)
    return result["text"]

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Please provide the audio file path")
        sys.exit(1)
    audio_file = sys.argv[1]
    print(transcribe(audio_file))
