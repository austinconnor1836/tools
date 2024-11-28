import os
import sys
from pydub import AudioSegment
from pydub.silence import split_on_silence


def ensure_dir_exists(directory):
    """
    Ensure that a directory exists. If it doesn't, create it.
    """
    if not os.path.exists(directory):
        os.makedirs(directory)


def extract_audio(video_file, output_dir="output"):
    """
    Extract audio from a video file and save it to the specified directory.
    """
    audio_output_dir = os.path.join(output_dir, "audio")
    ensure_dir_exists(audio_output_dir)

    audio_file = os.path.join(audio_output_dir, "temp_audio.wav")
    os.system(f"ffmpeg -i {video_file} -q:a 0 -map a {audio_file}")
    print(f"Audio extracted to {audio_file}")
    return audio_file


def detect_conversations(audio_file, min_silence_len=1000, silence_thresh=-40):
    """
    Detect conversation segments in the audio.
    """
    print("Analyzing audio for conversation segments...")
    audio = AudioSegment.from_file(audio_file, format="wav")

    # Split on silence
    chunks = split_on_silence(
        audio,
        min_silence_len=min_silence_len,
        silence_thresh=silence_thresh
    )

    # Calculate timestamps for each chunk
    timestamps = []
    current_time = 0
    for chunk in chunks:
        start_time = current_time
        end_time = start_time + len(chunk)
        timestamps.append((start_time / 1000, end_time / 1000))  # Convert to seconds
        current_time = end_time

    print(f"Detected {len(timestamps)} conversation segments.")
    return timestamps


def cut_video_ffmpeg(video_file, timestamps, output_dir="output"):
    """
    Cut the video into clips using FFmpeg based on timestamps.
    """
    clips_output_dir = os.path.join(output_dir, "clips")
    ensure_dir_exists(clips_output_dir)

    print("Cutting video into clips with FFmpeg...")
    for i, (start, end) in enumerate(timestamps):
        output_file = os.path.join(clips_output_dir, f"clip_{i + 1}.mp4")
        # FFmpeg command to cut video
        ffmpeg_command = f"ffmpeg -i {video_file} -ss {start} -to {end} -c copy {output_file}"
        os.system(ffmpeg_command)
        print(f"Saved clip: {output_file}")

    print("Video cutting complete!")


def main():
    # Check for command-line arguments
    if len(sys.argv) < 2:
        print("Usage: python script.py <video_file_path>")
        sys.exit(1)

    # Input video file from command-line argument
    video_file = sys.argv[1]

    # Verify the file exists
    if not os.path.isfile(video_file):
        print(f"Error: File '{video_file}' not found.")
        sys.exit(1)

    # Output directories
    output_dir = "output"

    # Step 1: Extract audio from video
    audio_file = extract_audio(video_file, output_dir)

    # Step 2: Detect conversation segments
    timestamps = detect_conversations(audio_file, min_silence_len=1000, silence_thresh=-40)

    # Step 3: Cut the video into clips using FFmpeg
    cut_video_ffmpeg(video_file, timestamps, output_dir)

    # Clean up temporary files
    if os.path.exists(audio_file):
        os.remove(audio_file)
        print("Temporary files cleaned up.")

    print("All tasks completed!")


if __name__ == "__main__":
    main()
