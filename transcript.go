package main

import (
	"fmt"
	"os/exec"
)

// TranscribeAudio transcribes audio from a .wav file to text using an external Python script
func TranscribeAudio(audioFile string) (string, error) {
	// Call the transcribe.py Python script to transcribe the audio file
	cmd := exec.Command("python", "transcribe.py", audioFile)
	output, err := cmd.CombinedOutput()
	if err != nil {
		return "", fmt.Errorf("failed to transcribe audio: %v\n%s", err, output)
	}
	return string(output), nil
}
