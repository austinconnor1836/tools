package main

import (
	"context"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"

	"google.golang.org/api/youtube/v3"
)

func StartOAuthCallbackServer() (string, error) {
	var authCode string
	server := &http.Server{Addr: ":8081"}

	http.HandleFunc("/callback", func(w http.ResponseWriter, r *http.Request) {
		code := r.URL.Query().Get("code")
		if code == "" {
			fmt.Fprintln(w, "No code in URL")
			return
		}
		authCode = code
		fmt.Fprintln(w, "Authorization successful! You can close this window.")
		go func() {
			server.Shutdown(context.Background()) // Shut down server after receiving code
		}()
	})

	fmt.Println("Listening on http://localhost:8081/callback")
	if err := server.ListenAndServe(); err != http.ErrServerClosed {
		return "", fmt.Errorf("server error: %v", err)
	}

	return authCode, nil
}

func initYouTubeService(client *http.Client) (*youtube.Service, error) {
	service, err := youtube.New(client)
	if err != nil {
		return nil, fmt.Errorf("Error creating YouTube service: %v", err)
	}
	return service, nil
}

func GetVideoTranscript(videoID string) {
	config := getOAuthConfig()
	client := getClient(config)
	service, err := youtube.New(client)
	if err != nil {
		log.Fatalf("Unable to initialize YouTube service: %v", err)
	}

	// Fetch available captions for the video
	captions, err := service.Captions.List([]string{"snippet"}, videoID).Do()
	if err != nil {
		log.Fatalf("Error fetching captions: %v", err)
	}

	if len(captions.Items) == 0 {
		fmt.Println("No captions available for this video.")
		return
	}

	fmt.Println("Downloading available captions:")
	for _, item := range captions.Items {
		// Define the filename using the video ID, caption ID, and language
		filename := fmt.Sprintf("%s_%s_%s.srt", videoID, item.Id, item.Snippet.Language)
		filepath := filepath.Join(".", filename)

		// Download the caption by ID using DownloadMedia
		response, err := service.Captions.Download(item.Id).Tfmt("srt").Download()
		if err != nil {
			log.Printf("Error downloading caption %s: %v\n", item.Id, err)
			continue
		}
		defer response.Body.Close()

		// Create a new file to save the caption content
		file, err := os.Create(filepath)
		if err != nil {
			log.Printf("Error creating file %s: %v\n", filename, err)
			continue
		}
		defer file.Close()

		// Write the caption content to the file
		_, err = io.Copy(file, response.Body)
		if err != nil {
			log.Printf("Error writing to file %s: %v\n", filename, err)
			continue
		}

		fmt.Printf("Caption saved to %s\n", filename)
	}
}

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
