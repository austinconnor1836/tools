package main

import (
	"flag"
	"fmt"
	"log"
	"net/url"
	"os"
	"path/filepath"
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
	case "transcribe":
		getTextFromVideoCommand := flag.NewFlagSet("transcribe", flag.ExitOnError)
		downloadMP4Flag := getTextFromVideoCommand.Bool("download-mp4", false, "Download the video as MP4")
		getTextFromVideoCommand.Parse(os.Args[2:])

		if getTextFromVideoCommand.NArg() < 1 {
			fmt.Println("Please provide a video URL.")
			return
		}
		videoInput := getTextFromVideoCommand.Arg(0)
		var title string

		// Check if input is a local file
		if _, err := os.Stat(videoInput); err == nil {
			log.Printf("Detected local file: %s", videoInput)

			// Extract audio from local video file directly
			if err := ExtractAudio(videoInput, "./output/audio.wav"); err != nil {
				log.Fatalf("Error extracting audio: %v", err)
			}

			// Use the file name as the title
			title = strings.TrimSuffix(filepath.Base(videoInput), filepath.Ext(videoInput))

		} else {
			// Assume it's a URL if the file does not exist locally
			title, err = GetVideoTitle(videoInput)
			if err != nil {
				log.Fatalf("Error fetching video title: %v", err)
			}

			if *downloadMP4Flag {
				if err := DownloadVideoAsMP4(videoInput); err != nil {
					log.Fatalf("Error downloading video: %v", err)
				}
			} else {
				if err := DownloadVideo(videoInput); err != nil {
					log.Fatalf("Error downloading video: %v", err)
				}
			}
		}

		// Step 2: Transcribe the audio to get the text
		text, err := TranscribeAudio("./output/audio.wav")
		if err != nil {
			log.Fatalf("Error transcribing audio: %v", err)
		}

		if err := SaveTranscriptionToFile(title, text); err != nil {
			log.Fatalf("Error saving transcription to file: %v", err)
		}

		// Clean up temporary audio and video files
		if err := CleanUpFiles("./output/audio.wav", "./output/audio.m4a"); err != nil {
			log.Printf("Error cleaning up files: %v", err)
		}
	case "download":
		downloadCommand := flag.NewFlagSet("download", flag.ExitOnError)
		xFlag := downloadCommand.String("x", "", "Download video from X.com (Twitter) post link")

		if err := downloadCommand.Parse(os.Args[2:]); err != nil {
			log.Fatalf("Error parsing download command: %v", err)
		}

		if *xFlag != "" {
			// Download video from X.com post
			if err := DownloadFromX(*xFlag); err != nil {
				log.Fatalf("Error downloading from X.com: %v", err)
			}
			return
		}

		// Default behavior: Expect a generic video URL
		if downloadCommand.NArg() < 1 {
			fmt.Println("Please provide a video URL.")
			return
		}
		videoURL := downloadCommand.Arg(0)
		_, err := url.Parse(videoURL)
		if err != nil {
			log.Fatalf("Error parsing video URL: %v", err)
		}

		if err := DownloadVideoAsMP4(videoURL); err != nil {
			log.Fatalf("Error downloading video: %v", err)
		}

		// Clean up temporary files
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
