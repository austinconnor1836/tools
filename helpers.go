package main

import (
	"bufio"
	"bytes"
	"fmt"
	"io/ioutil"
	"log"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"

	"github.com/google/uuid"
)

func ShowHelp() {
	fmt.Println("Usage: my-cli-tool [command] [options]")
	fmt.Println("\nCommands:")
	fmt.Println("  copy-branch                            Simulate copying current Git branch")
	fmt.Println("  delete-all-branches branch1 branch2    Simulate deleting all local branches except specified")
	fmt.Println("  transcribe <URL|PATH>                  Download video from URL and extract text")
	fmt.Println("  split-video                            Split video into clips based on audio")
}

func CopyBranch() {
	fmt.Println("Simulating copying current Git branch...")
}

func DeleteAllBranches(branchesToKeep []string) {
	fmt.Printf("Simulating deleting all branches except: %s\n", strings.Join(branchesToKeep, ", "))
}

// sanitizeFileName replaces invalid characters in a file name
func sanitizeFileName(name string) string {
	return strings.Map(func(r rune) rune {
		if strings.ContainsRune(`\/:*?"<>|`, r) {
			return '-'
		}
		return r
	}, name)
}

// CleanUpFiles removes the specified files from the filesystem
func CleanUpFiles(files ...string) error {
	for _, file := range files {
		if _, err := os.Stat(file); err == nil {
			if err := os.Remove(file); err != nil {
				return fmt.Errorf("failed to delete %s: %v", file, err)
			}
			fmt.Printf("Deleted %s\n", file)
		}
	}
	return nil
}

// DownloadVideo uses yt-dlp to download the video from a URL and extract audio with ffmpeg
func DownloadVideo(videoURL string) error {
	// Ensure the "output" directory exists
	EnsureOutputDir("output")

	// Download the audio-only m4a format
	cmd := exec.Command("yt-dlp", "-f", "140", "-o", "./output/audio.m4a", videoURL)
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	if err := cmd.Run(); err != nil {
		return fmt.Errorf("error downloading video: %v", err)
	}

	// Remove audio.wav if it exists
	if _, err := os.Stat("./output/audio.wav"); err == nil {
		if err := os.Remove("./output/audio.wav"); err != nil {
			return fmt.Errorf("failed to delete existing audio.wav: %v", err)
		}
	}

	// Convert the m4a audio to wav format
	cmd = exec.Command("ffmpeg", "-i", "./output/audio.m4a", "./output/audio.wav")
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	if err := cmd.Run(); err != nil {
		return fmt.Errorf("error converting audio: %v", err)
	}

	return nil
}

// DownloadVideoAsMP4 downloads and re-encodes a video to H.264 for Premiere Pro compatibility
func DownloadVideoAsMP4(videoURL string) error {
	tempVideoFile := fmt.Sprintf("./output/%s_temp_video.mp4", uuid.New().String())
	outputFile := fmt.Sprintf("./output/%s_video.mp4", uuid.New().String())

	// Download the best video and audio, merged into a single file
	cmd := exec.Command("yt-dlp", "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]", "-o", tempVideoFile, "-N", "16", videoURL)
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	if err := cmd.Run(); err != nil {
		return fmt.Errorf("error downloading video: %v", err)
	}

	// Check if the merged file exists
	if _, err := os.Stat(tempVideoFile); err != nil {
		return fmt.Errorf("merged video file not found: %v", err)
	}

	// Re-encode the video to H.264 for Premiere Pro compatibility
	cmd = exec.Command(
		"ffmpeg",
		"-i", tempVideoFile,
		"-c:v", "libx264",
		"-preset", "slow",
		"-crf", "23",
		"-c:a", "aac",
		"-b:a", "128k",
		outputFile,
	)
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	if err := cmd.Run(); err != nil {
		return fmt.Errorf("error re-encoding video: %v", err)
	}

	// Clean up temporary files
	if err := CleanUpFiles(tempVideoFile); err != nil {
		return fmt.Errorf("error cleaning up temporary files: %v", err)
	}

	fmt.Printf("Video downloaded and saved as %s\n", outputFile)
	return nil
}

// ExtractAudio uses ffmpeg to extract audio from a video file
func ExtractAudio(videoFile, audioFile string) error {
	cmd := exec.Command("ffmpeg", "-i", videoFile, "-q:a", "0", "-map", "a", audioFile)
	if output, err := cmd.CombinedOutput(); err != nil {
		return fmt.Errorf("failed to extract audio: %v\n%s", err, output)
	}
	return nil
}

// GetVideoTitle fetches the title of the video using yt-dlp
func GetVideoTitle(videoURL string) (string, error) {
	cmd := exec.Command("yt-dlp", "--get-title", videoURL)
	output, err := cmd.Output()
	if err != nil {
		return "", fmt.Errorf("error fetching video title: %v", err)
	}
	title := strings.TrimSpace(string(output))
	return title, nil
}

// SaveTranscriptionToFile saves the transcription text to a .txt file
func SaveTranscriptionToFile(title, transcribedText string) error {
	EnsureOutputDir("output")

	// Replace any invalid characters in the title for a file name
	fileName := fmt.Sprintf("./output/%s_transcription.txt", sanitizeFileName(title))
	file, err := os.Create(fileName)
	if err != nil {
		return fmt.Errorf("failed to create file: %v", err)
	}
	defer file.Close()

	_, err = file.WriteString(transcribedText)
	if err != nil {
		return fmt.Errorf("failed to write transcription to file: %v", err)
	}

	return nil
}

func ConvertToSpeech(inputFile string) error {
	const (
		awsPollyCharLimit = 1500 // AWS Polly Neural Engine text limit
	)
	// Ensure the output directory exists
	outputDir := "./output"
	if err := os.MkdirAll(outputDir, 0755); err != nil {
		return fmt.Errorf("failed to create output directory: %v", err)
	}

	// Read the text file
	content, err := ioutil.ReadFile(inputFile)
	if err != nil {
		return fmt.Errorf("failed to read text file: %v", err)
	}

	// Split the content into chunks that comply with AWS Polly limits
	chunks := splitTextIntoChunks(string(content), awsPollyCharLimit)

	tempFiles := []string{}
	for i, chunk := range chunks {
		tempFile := fmt.Sprintf("%s/temp_part_%d.mp3", outputDir, i)
		tempFiles = append(tempFiles, tempFile)

		// Use AWS Polly CLI to process each chunk
		cmd := exec.Command("aws", "polly", "synthesize-speech",
			"--text", chunk,
			"--output-format", "mp3",
			"--voice-id", "Stephen", // Replace with your preferred voice
			"--engine", "neural",
			tempFile)
		cmd.Stdout = os.Stdout
		cmd.Stderr = os.Stderr

		fmt.Printf("Processing chunk %d/%d\n", i+1, len(chunks))
		if err := cmd.Run(); err != nil {
			return fmt.Errorf("error processing chunk %d: %v", i, err)
		}
	}

	// Determine the final output file name based on the input file
	outputFile := fmt.Sprintf("%s/%s.mp3", outputDir, strings.TrimSuffix(filepath.Base(inputFile), filepath.Ext(inputFile)))

	// Remove the output file if it already exists
	if _, err := os.Stat(outputFile); err == nil {
		fmt.Printf("File %s already exists. Overwriting...\n", outputFile)
		if err := os.Remove(outputFile); err != nil {
			return fmt.Errorf("failed to delete existing output file: %v", err)
		}
	}

	// Combine all the temporary MP3 files into a single output file
	if err := combineMP3Files(tempFiles, outputFile); err != nil {
		return fmt.Errorf("failed to combine MP3 files: %v", err)
	}

	// Clean up temporary files
	for _, tempFile := range tempFiles {
		os.Remove(tempFile)
	}

	fmt.Printf("Text successfully converted to speech and saved as %s\n", outputFile)
	return nil
}

func splitTextIntoChunks(text string, limit int) []string {
	scanner := bufio.NewScanner(strings.NewReader(text))
	scanner.Split(bufio.ScanWords)

	var chunks []string
	var buffer bytes.Buffer

	for scanner.Scan() {
		word := scanner.Text()
		if buffer.Len()+len(word)+1 > limit { // +1 for space
			chunks = append(chunks, buffer.String())
			buffer.Reset()
		}
		if buffer.Len() > 0 {
			buffer.WriteString(" ")
		}
		buffer.WriteString(word)
	}

	if buffer.Len() > 0 {
		chunks = append(chunks, buffer.String())
	}

	return chunks
}

func combineMP3Files(inputFiles []string, outputFile string) error {
	args := []string{"-i", "concat:" + strings.Join(inputFiles, "|"), "-c", "copy", outputFile}
	cmd := exec.Command("ffmpeg", args...)
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr

	return cmd.Run()
}

func EnsureOutputDir(dir string) {
	if _, err := os.Stat(dir); os.IsNotExist(err) {
		if err := os.MkdirAll(dir, 0755); err != nil {
			log.Fatalf("Failed to create output directory: %v", err)
		}
	}
}

type SilenceInterval struct {
	Start float64
	End   float64
}

func ParseSilenceOutputToTalkingIntervals(output string, videoDuration float64) ([]SilenceInterval, error) {
	var intervals []SilenceInterval
	var silenceStarts []float64
	var silenceEnds []float64

	lines := strings.Split(output, "\n")
	for _, line := range lines {
		line = strings.TrimSpace(line)

		if strings.Contains(line, "silence_start:") {
			parts := strings.Split(line, "silence_start:")
			if len(parts) < 2 {
				continue
			}
			startStr := strings.Fields(parts[1])[0]
			start, err := strconv.ParseFloat(startStr, 64)
			if err == nil {
				silenceStarts = append(silenceStarts, start)
			}
		}

		if strings.Contains(line, "silence_end:") {
			parts := strings.Split(line, "silence_end:")
			if len(parts) < 2 {
				continue
			}
			endStr := strings.Fields(parts[1])[0]
			end, err := strconv.ParseFloat(endStr, 64)
			if err == nil {
				silenceEnds = append(silenceEnds, end)
			}
		}
	}

	var lastSilenceEnd float64 = 0

	for i := 0; i < len(silenceStarts); i++ {
		start := lastSilenceEnd
		end := silenceStarts[i]

		if end > start {
			intervals = append(intervals, SilenceInterval{Start: start, End: end})
		}
		if i < len(silenceEnds) {
			lastSilenceEnd = silenceEnds[i]
		}
	}

	if lastSilenceEnd < videoDuration {
		intervals = append(intervals, SilenceInterval{Start: lastSilenceEnd, End: videoDuration})
	}

	if len(intervals) == 0 {
		return nil, fmt.Errorf("no talking intervals detected")
	}

	return intervals, nil
}

const minClipDurationMs = 50   // Minimum allowed duration for clips in milliseconds
const startBufferSeconds = 1.5 // Buffer to adjust talking start time earlier
const endBufferSeconds = 1.5   // Buffer to adjust talking end time later

func SplitVideo(videoFile string, threshold float64, duration float64) error {
	outputDir := fmt.Sprintf("output/%s", strings.TrimSuffix(filepath.Base(videoFile), filepath.Ext(videoFile)))
	os.MkdirAll(outputDir, os.ModePerm)

	cmd := exec.Command("ffmpeg",
		"-i", videoFile,
		"-af", fmt.Sprintf("silencedetect=n=%fdB:d=%f", threshold, duration),
		"-f", "null", "-",
	)
	cmdOutput, err := cmd.CombinedOutput()
	if err != nil {
		log.Printf("Error running FFmpeg silencedetect: %v", err)
		log.Printf("FFmpeg output:\n%s", string(cmdOutput))
		return fmt.Errorf("error detecting silence: %v", err)
	}

	// Parse silence output to get talking intervals
	intervals, err := ParseSilenceOutputToTalkingIntervals(string(cmdOutput), duration)
	if err != nil {
		log.Printf("Error parsing silence output: %v", err)
		return fmt.Errorf("error parsing silence output: %v", err)
	}
	log.Printf("Detected %d raw talking intervals", len(intervals))

	var validIntervals []SilenceInterval
	for _, interval := range intervals {
		startMs := int(interval.Start * 1000)
		endMs := int(interval.End * 1000)
		durationMs := endMs - startMs

		// Apply buffer to both start and end times
		bufferedStart := interval.Start - startBufferSeconds
		if bufferedStart < 0 {
			bufferedStart = 0 // Prevent negative start times
		}
		bufferedEnd := interval.End + endBufferSeconds

		if durationMs > minClipDurationMs && bufferedStart < bufferedEnd {
			validIntervals = append(validIntervals, SilenceInterval{Start: bufferedStart, End: bufferedEnd})
		} else {
			log.Printf("[SKIP] Interval too short or zero-length: Start=%.2f, End=%.2f, Duration=%dms",
				interval.Start, interval.End, durationMs)
		}
	}
	log.Printf("Filtered to %d valid intervals", len(validIntervals))

	for i, interval := range validIntervals {
		start := interval.Start
		end := interval.End

		if start == end {
			log.Printf("[SKIP] Interval with identical start and end: Start=%.2f, End=%.2f", start, end)
			continue
		}

		outputClip := fmt.Sprintf("%s/clip_%d.mp4", outputDir, i+1)

		log.Printf("Creating clip %d: Start=%.2f (Buffered), End=%.2f (Buffered)", i+1, start, end)
		splitCmd := exec.Command("ffmpeg",
			"-y",
			"-i", videoFile,
			"-ss", fmt.Sprintf("%.2f", start),
			"-to", fmt.Sprintf("%.2f", end),
			"-c", "copy",
			outputClip,
		)

		splitOutput, splitErr := splitCmd.CombinedOutput()
		log.Printf("FFmpeg output for clip %d:\n%s", i+1, string(splitOutput))

		if splitErr != nil {
			log.Printf("Error creating clip %d (Start=%.2f, End=%.2f): %v", i+1, start, end, splitErr)
			return fmt.Errorf("error creating clip %d: %v", i+1, splitErr)
		}
	}

	log.Println("Splitting complete.")
	return nil
}

// DownloadFromX downloads a video from an X.com (Twitter) post
func DownloadFromX(postURL string) error {
	// Ensure the "output" directory exists
	EnsureOutputDir("output")

	// Generate a unique filename for the output video
	outputFile := fmt.Sprintf("./output/%s_x_video.mp4", uuid.New().String())

	// Use yt-dlp to fetch the video from the provided X.com post URL
	cmd := exec.Command("yt-dlp", "-f", "best", "-o", outputFile, postURL)
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr

	fmt.Printf("Downloading video from X.com: %s\n", postURL)
	if err := cmd.Run(); err != nil {
		return fmt.Errorf("error downloading video from X.com: %v", err)
	}

	fmt.Printf("Video downloaded and saved as %s\n", outputFile)
	return nil
}
