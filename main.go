package main

import (
	"flag"
	"fmt"
	"log"
	"net/url"
	"os"
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
		cmd := flag.NewFlagSet("transcribe", flag.ExitOnError)
		videoPath := cmd.String("video", "", "Path to the video file")
		
		cmd.Parse(os.Args[2:])

		if *videoPath == "" {
			fmt.Println("Please specify a video file.")
			return
		}

		// Step 2: Transcribe the audio to get the text
		TranscribeAudio(*videoPath)

		// // Clean up temporary audio and video files
		// if err := CleanUpFiles("./output/audio.wav", "./output/audio.m4a"); err != nil {
		// 	log.Printf("Error cleaning up files: %v", err)
		// }
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
	case "publish-auto":
		publishCmd := flag.NewFlagSet("publish-auto", flag.ExitOnError)
		hashtags := publishCmd.String("hashtags", "", "Comma-separated hashtags")
		platforms := publishCmd.String("platforms", "youtube,instagram,twitter,facebook,linkedin,reddit", "Platforms to publish to (comma-separated)")
		videoPath := publishCmd.String("video", "", "Path to the video file")

		publishCmd.Parse(os.Args[2:])

		if *videoPath == "" {
			fmt.Println("Please specify a video file.")
			return
		}

		err := PublishWithAutoGeneratedMetadata(*videoPath, *hashtags, *platforms)
		if err != nil {
			log.Fatalf("Error publishing video: %v", err)
		}

	default:
		ShowHelp()
	}
}
