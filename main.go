package main

import (
	"fmt"
	"log"
	"net/url"
	"os"
	"strings"
)

func main() {
	if len(os.Args) < 2 {
		ShowHelp()
		return
	}

	command := os.Args[1]

	switch command {
	case "copy-branch":
		CopyBranch()
	case "delete-all-branches":
		if len(os.Args) < 3 {
			fmt.Println("Please specify branches to keep.")
			return
		}
		DeleteAllBranches(os.Args[2:])
	case "get-text-from-video":
		if len(os.Args) < 3 {
			fmt.Println("Please provide a video URL.")
			return
		}
		videoURL := os.Args[2]
		u, err := url.Parse(videoURL)
		if err != nil {
			log.Fatalf("Error parsing video URL: %v", err)
		}

		videoID := u.Query().Get("v")
		if videoID == "" {
			parts := strings.Split(u.Path, "/")
			videoID = parts[len(parts)-1]
		}

		// GetVideoTranscript(videoID)
		// Step 1: Download the video and extract audio
		if err := DownloadVideo(videoURL); err != nil {
			log.Fatalf("Error downloading video: %v", err)
		}

		// Step 2: Transcribe the audio to get the text
		text, err := TranscribeAudio("audio.wav")
		if err != nil {
			log.Fatalf("Error transcribing audio: %v", err)
		}

		if err := SaveTranscriptionToFile(videoID, text); err != nil {
			log.Fatalf("Error saving transcription to file: %v", err)
		}

	default:
		ShowHelp()
	}
}
