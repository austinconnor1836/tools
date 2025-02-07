import subprocess
import re
import os

# Silence detection settings
silence_threshold = "-35dB"
silence_duration = "0.35"

# Get a list of all input video files (1.mp4, 2.mp4, ..., 26.mp4)
video_files = [f"{i}.mp4" for i in range(1, 27)]  # Adjust the range if needed

# Process each video
for input_file in video_files:
    output_file = f"clean_{input_file}"  # Save output as clean_1.mp4, clean_2.mp4, etc.

    print(f"Processing {input_file}...")

    # Step 1: Detect Silence
    cmd = f'ffmpeg -i {input_file} -af "silencedetect=noise={silence_threshold}:d={silence_duration}" -f null -'
    output = subprocess.run(cmd, shell=True, capture_output=True, text=True)

    # Extract silence timestamps
    matches = re.findall(r"silence_start: ([0-9]+\.[0-9]+)|silence_end: ([0-9]+\.[0-9]+)", output.stderr)

    # Convert timestamps to a list
    timestamps = []
    for start, end in matches:
        if start:
            timestamps.append(float(start))
        if end:
            timestamps.append(float(end))

    # Prevent IndexError if no silence is detected
    if not timestamps:
        print(f"No silence detected in {input_file}. Skipping...")
        continue

    # Ensure timestamps have pairs
    if len(timestamps) % 2 == 1:
        timestamps.append(None)  # Ensure even number of timestamps

    # Process silence segments
    keep_sections = []
    for i in range(0, len(timestamps)-1, 2):
        keep_sections.append((timestamps[i], timestamps[i+1] if timestamps[i+1] is not None else timestamps[i] + 1))

    # Generate trim filter for FFmpeg
    trim_cmds = []
    for i, (start, end) in enumerate(keep_sections):
        trim_cmds.append(f"[0:v]trim=start={start}:end={end},setpts=PTS-STARTPTS[v{i}]; [0:a]atrim=start={start}:end={end},asetpts=PTS-STARTPTS[a{i}];")

    concat_cmd = f"{' '.join(trim_cmds)} {' '.join([f'[v{i}][a{i}]' for i in range(len(keep_sections))])}concat=n={len(keep_sections)}:v=1:a=1[outv][outa]"

    # Step 2: Trim Video & Audio
    final_cmd = f'ffmpeg -i {input_file} -filter_complex "{concat_cmd}" -map "[outv]" -map "[outa]" {output_file}'
    subprocess.run(final_cmd, shell=True)

    print(f"Processed video saved as {output_file}")

print("All videos processed successfully!")
