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
	"strconv"
	"strings"
	"time"

	"golang.org/x/oauth2"
	"golang.org/x/oauth2/google"
	"google.golang.org/api/googleapi"
	"google.golang.org/api/youtube/v3"
)

// Struct to hold OpenAI API request
type OpenAIRequest struct {
	Model    string        `json:"model"`
	Messages []GPTMessage  `json:"messages"`
}

// Struct for individual messages in the chat
type GPTMessage struct {
	Role    string `json:"role"`
	Content string `json:"content"`
}

// Struct for OpenAI API response
type OpenAIResponse struct {
	Choices []struct {
		Message struct {
			Content string `json:"content"`
		} `json:"message"`
	} `json:"choices"`
}

// Struct to correctly match the OpenAI response
type GPTTitleDescription struct {
	Title       string `json:"title"`
	Description string `json:"description"`
}

// Struct for GPT API response
type GPTResponse struct {
	Titles      []string `json:"titles"`
	Description string   `json:"description"`
}


func GenerateTitlesAndDescriptions(videoFile string) (*GPTResponse, error) {
	// Extract only the filename
	videoFileName := filepath.Base(videoFile) // Extracts "trump-annex-gaza-short.mp4"
	videoFileName = stripFileExtension(videoFileName) // Removes ".mp4"

	// Read transcription file from correct path
	transcriptionFile := fmt.Sprintf("./output/transcriptions/%s.txt", videoFileName)
	transcriptionText, err := ioutil.ReadFile(transcriptionFile)
	if err != nil {
		return nil, fmt.Errorf("failed to read transcription file: %v", err)
	}

	// Get API key from environment
	apiKey := os.Getenv("OPENAI_API_KEY")
	if apiKey == "" {
		return nil, fmt.Errorf("missing OPENAI_API_KEY environment variable")
	}

	// Construct OpenAI API request
	requestBody := OpenAIRequest{
		Model: "gpt-4",
		Messages: []GPTMessage{
			{Role: "system", Content: "You generate video titles and a single description in JSON format."},
			{Role: "user", Content: fmt.Sprintf(
				"Based on this transcript, generate exactly 5 possible video titles that evoke emotion and curiosity and ONE single detailed description.\n\n"+
					"Return ONLY valid JSON. Example:\n"+
					"```json\n"+
					"{ \"titles\": [\"Title 1\", \"Title 2\", \"Title 3\", \"Title 4\", \"Title 5\"],"+
					" \"description\": \"This is the only detailed description provided.\" }"+
					"\n```"+
					"\n\nStrictly follow this format. DO NOT include anything else."+ 
					"\n\nTranscript:\n%s", string(transcriptionText))},
		},
	}

	// Convert requestBody to JSON
	jsonData, err := json.Marshal(requestBody)
	if err != nil {
		return nil, fmt.Errorf("failed to encode OpenAI request: %v", err)
	}

	// Send request to OpenAI API
	req, err := http.NewRequest("POST", "https://api.openai.com/v1/chat/completions", bytes.NewBuffer(jsonData))
	if err != nil {
		return nil, fmt.Errorf("failed to create OpenAI request: %v", err)
	}
	req.Header.Set("Authorization", "Bearer "+apiKey)
	req.Header.Set("Content-Type", "application/json")

	client := &http.Client{}
	resp, err := client.Do(req)
	if err != nil {
		return nil, fmt.Errorf("failed to send OpenAI request: %v", err)
	}
	defer resp.Body.Close()

	// Read response body
	body, err := ioutil.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("failed to read OpenAI response: %v", err)
	}

	// Extract content from GPT response
	var apiResponse OpenAIResponse
	err = json.Unmarshal(body, &apiResponse)
	if err != nil {
		log.Printf("Error parsing GPT response: %v\nRaw Output: %s", err, string(body))
		return nil, fmt.Errorf("failed to parse GPT response: %v", err)
	}

	// Extract GPT response text
	if len(apiResponse.Choices) == 0 {
		return nil, fmt.Errorf("no choices returned from GPT")
	}
	gptText := apiResponse.Choices[0].Message.Content

	// Debugging: Print raw GPT output
	fmt.Println("🔍 GPT Raw Response:")
	fmt.Println(gptText)

	// Remove possible triple backticks
	gptText = strings.TrimSpace(gptText)
	gptText = strings.TrimPrefix(gptText, "```json")
	gptText = strings.TrimSuffix(gptText, "```")

	// Parse GPT-generated JSON
	var gptResponse GPTResponse
	err = json.Unmarshal([]byte(gptText), &gptResponse)
	if err != nil {
		log.Printf("Error parsing GPT JSON response: %v\nRaw Output: %s", err, gptText)
		return nil, fmt.Errorf("failed to parse GPT JSON response: %v", err)
	}

	return &gptResponse, nil
}


// Utility function to remove file extension
func stripFileExtension(filename string) string {
	for i := len(filename) - 1; i >= 0; i-- {
		if filename[i] == '.' {
			return filename[:i]
		}
	}
	return filename
}

func PublishWithAutoGeneratedMetadata(videoPath, hashtags, platforms, thumbnailPath string) error {
	// Step 1: Transcribe the audio (No return value)
	TranscribeAudio(videoPath)

	// Step 2: Generate title and description using GPT
	fmt.Println("🤖 Generating possible titles and descriptions using GPT...")
	gptResponse, err := GenerateTitlesAndDescriptions(videoPath)
	if err != nil {
		return fmt.Errorf("failed to generate titles and descriptions: %v", err)
	}
	fmt.Println("✅ Title and description suggestions generated!")

	// Extract titles (multiple) and description (single)
	titles := gptResponse.Titles
	description := gptResponse.Description // Now correctly extracted

	// Step 3: Display choices to user
	fmt.Println("\n🎯 Suggested Titles:")
	for i, title := range titles {
		fmt.Printf("[%d] %s\n", i+1, title)
	}

	fmt.Println("\n📖 Description:")
	fmt.Println(description)

	// Step 4: Let user select a title
	reader := bufio.NewReader(os.Stdin)
	fmt.Print("\nEnter the number of the title you want to use: ")
	titleChoice, _ := reader.ReadString('\n')
	titleChoice = strings.TrimSpace(titleChoice)

	// Convert user input (string) to an integer safely
	titleIndex, err := strconv.Atoi(titleChoice)
	if err != nil || titleIndex < 1 || titleIndex > len(titles) {
		log.Fatalf("Invalid title selection: %s", titleChoice)
	}

	selectedTitle := titles[titleIndex-1]

	fmt.Printf("\n📤 Proceeding with:\nTitle: %s\nDescription: %s\n", selectedTitle, description)

	// Step 5: Publish video using Go-based API calls
	err = PublishVideo(videoPath, selectedTitle, description, hashtags, platforms, thumbnailPath)
	if err != nil {
		return fmt.Errorf("error publishing video: %v", err)
	}

	fmt.Println("✅ Video successfully published!")
	return nil
}


// ParseJSONOutput parses GPT's JSON response into a Go map
func ParseJSONOutput(jsonStr string) map[string]string {
	var result map[string]string
	err := json.Unmarshal([]byte(jsonStr), &result)
	if err != nil {
		log.Fatalf("Error parsing GPT JSON response: %v", err)
	}
	return result
}

// CallGPTForTitlesAndDescriptions makes a request to the GPT API
func CallGPTForTitlesAndDescriptions(transcription string) (map[string]string, error) {
	prompt := fmt.Sprintf("Based on this transcript, suggest 5 possible video titles and 5 detailed descriptions:\n\n%s", transcription)

	cmd := exec.Command("python", "ask_gpt.py", prompt)
	output, err := cmd.CombinedOutput()
	if err != nil {
		return nil, fmt.Errorf("GPT request failed: %v\n%s", err, output)
	}

	// Parse output (expecting JSON format)
	response := ParseJSONOutput(string(output))
	return response, nil
}

// Upload video and optionally upload a thumbnail
func PublishVideo(videoPath, title, description, hashtags, platforms, thumbnailPath string) error {
	platformList := strings.Split(platforms, ",")

	for _, platform := range platformList {
		platform = strings.TrimSpace(strings.ToLower(platform))
		fmt.Printf("\n🚀 Uploading to %s...\n", platform)

		if platform == "youtube" {
			fmt.Println("📺 Uploading to YouTube...")

			ctx := context.Background()
			client, err := getOAuthClient(ctx)
			if err != nil {
				log.Fatalf("Failed to get OAuth client: %v", err)
			}

			service, err := youtube.New(client)
			if err != nil {
				log.Fatalf("Error creating YouTube client: %v", err)
			}

			// Open the video file
			file, err := os.Open(videoPath)
			if err != nil {
				log.Fatalf("Error opening video file: %v", err)
			}
			defer file.Close()

			// Define video metadata
			video := &youtube.Video{
				Snippet: &youtube.VideoSnippet{
					Title:                title,
					Description:          "Support me on Patreon: https://www.patreon.com/c/Polemicyst\n\n" + description + "\n\n" + hashtags,
					CategoryId:           "25", // 25 = News & Politics
					Tags:                 formatTags(hashtags),
					DefaultLanguage:      "en",
					DefaultAudioLanguage: "en",
				},
				Status: &youtube.VideoStatus{
					PrivacyStatus:           "public",
					SelfDeclaredMadeForKids: false,
				},
			}

			// Upload the video
			call := service.Videos.Insert([]string{"snippet", "status"}, video)
			call = call.Media(file)

			response, err := call.Do()
			if err != nil {
				log.Fatalf("Error uploading video: %v", err)
			}

			videoID := response.Id
			fmt.Printf("✅ YouTube upload successful! Video ID: %s\n", videoID)

			// ✅ Upload thumbnail if the flag is provided
			if strings.TrimSpace(thumbnailPath) != "" {
				fmt.Println("📸 Waiting 10 seconds before uploading custom thumbnail...")

				// Delay for 10 seconds to allow YouTube to process the video ID
				time.Sleep(10 * time.Second)

				err := uploadThumbnail(service, videoID, thumbnailPath)
				if err != nil {
					log.Fatalf("Error uploading thumbnail: %v", err)
				}
				fmt.Println("✅ Thumbnail uploaded successfully!")
			}

		} else {
			fmt.Printf("⚠️ Unknown platform: %s\n", platform)
		}
	}
	return nil
}

// 📸 Uploads a thumbnail to YouTube with retry logic
func uploadThumbnail(service *youtube.Service, videoID, thumbnailPath string) error {
	fmt.Println("📸 Uploading custom thumbnail...")

	thumbnailBytes, err := ioutil.ReadFile(thumbnailPath)
	if err != nil {
		return fmt.Errorf("error reading thumbnail file: %v", err)
	}

	// Implement exponential backoff (max 5 retries)
	for i := 0; i < 5; i++ {
		thumbnailUpload := service.Thumbnails.Set(videoID)
		thumbnailUpload = thumbnailUpload.Media(bytes.NewReader(thumbnailBytes), googleapi.ContentType("image/png"))

		_, err = thumbnailUpload.Do()
		if err == nil {
			return nil // Success
		}

		fmt.Printf("Retrying thumbnail upload... Attempt %d/5\n", i+1)
		time.Sleep(time.Duration(i+1) * 5 * time.Second) // Exponential backoff
	}

	return fmt.Errorf("failed to upload thumbnail after multiple attempts")
}



func getOAuthClient(ctx context.Context) (*http.Client, error) {
    credentialsFile := "./input/client_secret.json"
    tokenFile := "./output/token.json" // Store token in output/

    // Read OAuth 2.0 credentials
    b, err := os.ReadFile(credentialsFile)
    if err != nil {
        return nil, fmt.Errorf("unable to read client secret file: %v", err)
    }

    // Parse OAuth 2.0 config
    config, err := google.ConfigFromJSON(b, youtube.YoutubeUploadScope)
    if err != nil {
        return nil, fmt.Errorf("unable to parse client secret file to config: %v", err)
    }

    // Retrieve token
    token, err := tokenFromFile(tokenFile)
    if err != nil {
        // If token does not exist, get a new one from the web
        token = getTokenFromWeb(config)
        saveToken(tokenFile, token) // Save in output/
    }

    return config.Client(ctx, token), nil
}


func tokenFromFile(filePath string) (*oauth2.Token, error) {
    f, err := os.Open(filePath)
    if err != nil {
        return nil, err
    }
    defer f.Close()
    
    token := &oauth2.Token{}
    err = json.NewDecoder(f).Decode(token)
    return token, err
}


func getTokenFromWeb(config *oauth2.Config) *oauth2.Token {
    authURL := config.AuthCodeURL("state-token", oauth2.AccessTypeOffline)
    fmt.Printf("Go to the following link in your browser and authorize the app:\n%s\n", authURL)

    // Manually input the authorization code
    fmt.Print("Enter the authorization code: ")
    var authCode string
    fmt.Scanln(&authCode) // Use Scanln instead of Scan for long input

    // Exchange authorization code for token
    token, err := config.Exchange(context.Background(), authCode)
    if err != nil {
        log.Fatalf("Unable to retrieve token: %v", err)
    }
    return token
}


func saveToken(filePath string, token *oauth2.Token) {
    // Ensure output directory exists
    outputDir := "./output"
    if _, err := os.Stat(outputDir); os.IsNotExist(err) {
        os.Mkdir(outputDir, os.ModePerm)
    }

    // Save token file
    fmt.Printf("Saving credential file to: %s\n", filePath)
    f, err := os.Create(filePath)
    if err != nil {
        log.Fatalf("Unable to create token file: %v", err)
    }
    defer f.Close()
    
    json.NewEncoder(f).Encode(token)
}

// Remove '#' from hashtags and split into separate words
func formatTags(hashtags string) []string {
    words := strings.Fields(hashtags) // Split by space
    var tags []string
    for _, word := range words {
        if strings.HasPrefix(word, "#") {
            tags = append(tags, strings.TrimPrefix(word, "#")) // Remove the '#'
        } else {
            tags = append(tags, word)
        }
    }
    return tags
}