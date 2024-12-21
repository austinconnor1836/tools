package main

import (
	"flag"
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
		getTextFromVideoCommand := flag.NewFlagSet("get-text-from-video", flag.ExitOnError)
		downloadMP4Flag := getTextFromVideoCommand.Bool("download-mp4", false, "Download the video as MP4")
		getTextFromVideoCommand.Parse(os.Args[2:])

		if getTextFromVideoCommand.NArg() < 1 {
			fmt.Println("Please provide a video URL.")
			return
		}
		videoURL := getTextFromVideoCommand.Arg(0)
		u, err := url.Parse(videoURL)
		if err != nil {
			log.Fatalf("Error parsing video URL: %v", err)
		}

		videoID := u.Query().Get("v")
		if videoID == "" {
			parts := strings.Split(u.Path, "/")
			videoID = parts[len(parts)-1]
		}

		if *downloadMP4Flag {
			// Step 1: Download the video as MP4
			if err := DownloadVideoAsMP4(videoURL); err != nil {
				log.Fatalf("Error downloading video: %v", err)
			}
		} else {
			// Step 1: Download the audio and extract audio
			if err := DownloadVideo(videoURL); err != nil {
				log.Fatalf("Error downloading video: %v", err)
			}
		}
		// Step 2: Transcribe the audio to get the text
		text, err := TranscribeAudio("./output/audio.wav")
		if err != nil {
			log.Fatalf("Error transcribing audio: %v", err)
		}

		if err := SaveTranscriptionToFile(videoID, text); err != nil {
			log.Fatalf("Error saving transcription to file: %v", err)
		}

		// Clean up temporary audio and video files
		if err := CleanUpFiles("./output/audio.wav", "./output/audio.m4a"); err != nil {
			log.Printf("Error cleaning up files: %v", err)
		}
	case "download":
		downloadVideoCommand := flag.NewFlagSet("download-video", flag.ExitOnError)
		downloadVideoCommand.Parse(os.Args[2:])

		if downloadVideoCommand.NArg() < 1 {
			fmt.Println("Please provide a video URL.")
			return
		}
		videoURL := downloadVideoCommand.Arg(0)
		_, err := url.Parse(videoURL)
		if err != nil {
			log.Fatalf("Error parsing video URL: %v", err)
		}

		if err := DownloadVideoAsMP4(videoURL); err != nil {
			log.Fatalf("Error downloading video: %v", err)
		}

		// Clean up temporary audio and video files
		if err := CleanUpFiles("./output/audio.wav", "./output/audio.m4a"); err != nil {
			log.Printf("Error cleaning up files: %v", err)
		}
	case "convert-to-speech":
		convertToSpeechCommand := flag.NewFlagSet("convert-to-speech", flag.ExitOnError)
		convertToSpeechCommand.Parse(os.Args[2:])

		if convertToSpeechCommand.NArg() < 1 {
			fmt.Println("Please provide a text file path.")
			return
		}
		textFilePath := convertToSpeechCommand.Arg(0)

		// Process the file and convert it to speech
		err := ConvertToSpeech(textFilePath)
		if err != nil {
			log.Fatalf("Error converting text to speech: %v", err)
		}
	case "split-video":
		splitCmd := flag.NewFlagSet("split-video", flag.ExitOnError)
		thresholdFlag := splitCmd.Float64("threshold", -40, "Silence detection threshold in dB (e.g., -40)")
		durationFlag := splitCmd.Float64("duration", 2.0, "Minimum silence duration in seconds")

		// Check if there are enough arguments before parsing
		if len(os.Args) < 3 {
			log.Fatalf("Usage: split-video [-threshold=<value>] [-duration=<value>] <video-file>")
		}

		// Parse the flags for this command
		if err := splitCmd.Parse(os.Args[2:]); err != nil {
			log.Fatalf("Error parsing flags for split-video: %v", err)
		}

		// Validate arguments
		if splitCmd.NArg() < 1 {
			log.Fatalf("Usage: split-video [-threshold=<value>] [-duration=<value>] <video-file>")
		}

		videoFile := splitCmd.Arg(0)
		log.Printf("Splitting video: %s with threshold=%f dB and duration=%f seconds", videoFile, *thresholdFlag, *durationFlag)

		// Call the SplitVideo function
		err := SplitVideo(videoFile, *thresholdFlag, *durationFlag)
		if err != nil {
			log.Fatalf("Error splitting video: %v", err)
		}

	default:
		ShowHelp()
	}
}
