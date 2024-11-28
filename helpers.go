package main

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io/ioutil"
	"log"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"strings"

	"github.com/google/uuid"
	"golang.org/x/oauth2"
	"golang.org/x/oauth2/google"
	"google.golang.org/api/youtube/v3"
)

func ShowHelp() {
	fmt.Println("Usage: my-cli-tool [command] [options]")
	fmt.Println("\nCommands:")
	fmt.Println("  copy-branch                            Simulate copying current Git branch")
	fmt.Println("  delete-all-branches branch1 branch2    Simulate deleting all local branches except specified")
	fmt.Println("  get-text-from-video URL                Download video from URL and extract text")
}

func CopyBranch() {
	fmt.Println("Simulating copying current Git branch...")
}

func DeleteAllBranches(branchesToKeep []string) {
	fmt.Printf("Simulating deleting all branches except: %s\n", strings.Join(branchesToKeep, ", "))
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

func tokenFromFile(path string) (*oauth2.Token, error) {
	file, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer file.Close()
	token := &oauth2.Token{}
	return token, json.NewDecoder(file).Decode(token)
}

func getOAuthConfig() *oauth2.Config {
	credentialsFile := "./credentials.json"
	b, err := os.ReadFile(credentialsFile)
	if err != nil {
		log.Fatalf("Unable to read client secret file: %v", err)
	}

	config, err := google.ConfigFromJSON(b, youtube.YoutubeForceSslScope)

	if err != nil {
		log.Fatalf("Unable to parse client secret file to config: %v", err)
	}
	config.RedirectURL = "http://localhost:8081/callback"
	return config
}

func getClient(config *oauth2.Config) *http.Client {
	authCodeCh := make(chan string)

	// Start the callback server in a goroutine
	go func() {
		http.HandleFunc("/callback", func(w http.ResponseWriter, r *http.Request) {
			code := r.URL.Query().Get("code")
			if code == "" {
				fmt.Fprintln(w, "No code in URL")
				return
			}
			fmt.Fprintln(w, "Authorization successful! You can close this window.")
			authCodeCh <- code
		})

		if err := http.ListenAndServe(":8081", nil); err != http.ErrServerClosed {
			log.Fatalf("Server error: %v", err)
		}
	}()

	// Generate the authorization URL
	authURL := config.AuthCodeURL("state-token", oauth2.AccessTypeOffline)
	fmt.Printf("Go to the following link in your browser, then authorize the application:\n%v\n", authURL)

	// Wait for the authorization code from the callback
	authCode := <-authCodeCh

	// Exchange the authorization code for a token
	token, err := config.Exchange(context.TODO(), authCode)
	if err != nil {
		log.Fatalf("Unable to retrieve token from web: %v", err)
	}
	saveToken("token.json", token)

	return config.Client(context.Background(), token)
}

func saveToken(path string, token *oauth2.Token) {
	file, err := os.Create(path)
	if err != nil {
		log.Fatalf("Unable to save token: %v", err)
	}
	defer file.Close()
	if err := json.NewEncoder(file).Encode(token); err != nil {
		log.Fatalf("Unable to encode token: %v", err)
	}
}

// EnsureOutputDir ensures the output directory exists
func EnsureOutputDir() error {
	if _, err := os.Stat("./output"); os.IsNotExist(err) {
		if err := os.Mkdir("./output", 0755); err != nil {
			return fmt.Errorf("failed to create output directory: %v", err)
		}
	}
	return nil
}

// DownloadVideo uses yt-dlp to download the video from a URL and extract audio with ffmpeg
func DownloadVideo(videoURL string) error {
	if err := EnsureOutputDir(); err != nil {
		return err
	}

	// Download the audio-only m4a format
	cmd := exec.Command("yt-dlp", "-f", "140", "-o", "./output/audio.m4a", videoURL)
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	if err := cmd.Run(); err != nil {
		return fmt.Errorf("error downloading video: %v", err)
	}

	// Remove audio.wav if it exists
	if _, err := os.Stat("audio.wav"); err == nil {
		if err := os.Remove("audio.wav"); err != nil {
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

// SaveTranscriptionToFile saves the transcription text to a .txt file
func SaveTranscriptionToFile(videoID, transcribedText string) error {
	if err := EnsureOutputDir(); err != nil {
		return err
	}

	filename := fmt.Sprintf("./output/%s_transcription.txt", videoID)
	file, err := os.Create(filename)
	if err != nil {
		return fmt.Errorf("failed to create file: %v", err)
	}
	defer file.Close()

	_, err = file.WriteString(transcribedText)
	if err != nil {
		return fmt.Errorf("failed to write transcription to file: %v", err)
	}

	fmt.Printf("Transcription saved to %s\n", filename)
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
