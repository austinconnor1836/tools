package main

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"os"
	"os/exec"
	"strings"

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

// DownloadVideo uses yt-dlp to download the video from a URL and extract audio with ffmpeg
func DownloadVideo(videoURL string) error {
	// Download the audio-only m4a format
	cmd := exec.Command("yt-dlp", "-f", "140", "-o", "audio.m4a", videoURL)
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
	cmd = exec.Command("ffmpeg", "-i", "audio.m4a", "audio.wav")
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	if err := cmd.Run(); err != nil {
		return fmt.Errorf("error converting audio: %v", err)
	}

	return nil
}

// DownloadVideoAsMP4 uses yt-dlp to download the video as an MP4 file
func DownloadVideoAsMP4(videoURL string) error {
	// Download the best available MP4 format
	cmd := exec.Command("yt-dlp", "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/mp4", "-o", "video.mp4", videoURL)
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	if err := cmd.Run(); err != nil {
		return fmt.Errorf("error downloading video: %v", err)
	}

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
	filename := fmt.Sprintf("%s_transcription.txt", videoID)
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
