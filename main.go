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
	case "download-video":
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
	default:
		ShowHelp()
	}
}
