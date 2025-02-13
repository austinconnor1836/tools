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
	"golang.org/x/text/unicode/norm"

	"github.com/rivo/uniseg" // Import the package for correct grapheme counting
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

func GenerateScript(videoPath, inputScriptPath string) error {
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

func UpdateThumbnail(videoID, thumbnailPath string) error {
    fmt.Println("📸 Updating thumbnail for video:", videoID)

    // Authenticate with YouTube API
    ctx := context.Background()
    client, err := getOAuthClient(ctx)
    if err != nil {
        return fmt.Errorf("failed to get OAuth client: %v", err)
    }

    service, err := youtube.New(client)
    if err != nil {
        return fmt.Errorf("error creating YouTube client: %v", err)
    }

    // Read thumbnail file
    thumbnailBytes, err := ioutil.ReadFile(thumbnailPath)
    if err != nil {
        return fmt.Errorf("error reading thumbnail file: %v", err)
    }

    // Exponential backoff (retrying in case of failure)
    for i := 0; i < 5; i++ {
        fmt.Printf("Attempting to update thumbnail (Attempt %d/5)...\n", i+1)
        
        // Upload thumbnail
        thumbnailUpload := service.Thumbnails.Set(videoID)
        thumbnailUpload = thumbnailUpload.Media(bytes.NewReader(thumbnailBytes), googleapi.ContentType("image/png"))

        _, err = thumbnailUpload.Do()
        if err == nil {
            fmt.Println("✅ Thumbnail updated successfully!")
            return nil
        }

        fmt.Printf("Retrying thumbnail update... Attempt %d/5\n", i+1)
        time.Sleep(time.Duration(i+1) * 5 * time.Second) // Exponential backoff
    }

    return fmt.Errorf("failed to update thumbnail after multiple attempts")
}

// Upload video and optionally upload a thumbnail
func PublishVideo(videoPath, title, description, hashtags, platforms, thumbnailPath string) error {
	// platformList := strings.Split(platforms, ",")

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
	youtubeLink := fmt.Sprintf("https://youtu.be/%s", videoID)
	fmt.Printf("✅ YouTube upload successful! Video Link: %s\n", youtubeLink)
	// fmt.Printf("✅ YouTube upload successful! Video ID: %s\n", videoID)

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

	fmt.Println("📢 Posting to BlueSky...")
	err = PostToBlueSky(title, description, youtubeLink)
	if err != nil {
		log.Printf("❌ Failed to post to BlueSky: %v", err)
	} else {
		fmt.Println("✅ BlueSky post successful!")
	}

	// for _, platform := range platformList {
	// 	platform = strings.TrimSpace(strings.ToLower(platform))
	// 	fmt.Printf("\n🚀 Uploading to %s...\n", platform)

	// 	switch platform {
	// 		case "youtube": 
	// 			fmt.Println("📺 Uploading to YouTube...")

	// 			ctx := context.Background()
	// 			client, err := getOAuthClient(ctx)
	// 			if err != nil {
	// 				log.Fatalf("Failed to get OAuth client: %v", err)
	// 			}

	// 			service, err := youtube.New(client)
	// 			if err != nil {
	// 				log.Fatalf("Error creating YouTube client: %v", err)
	// 			}

	// 			// Open the video file
	// 			file, err := os.Open(videoPath)
	// 			if err != nil {
	// 				log.Fatalf("Error opening video file: %v", err)
	// 			}
	// 			defer file.Close()

	// 			// Define video metadata
	// 			video := &youtube.Video{
	// 				Snippet: &youtube.VideoSnippet{
	// 					Title:                title,
	// 					Description:          "Support me on Patreon: https://www.patreon.com/c/Polemicyst\n\n" + description + "\n\n" + hashtags,
	// 					CategoryId:           "25", // 25 = News & Politics
	// 					Tags:                 formatTags(hashtags),
	// 					DefaultLanguage:      "en",
	// 					DefaultAudioLanguage: "en",
	// 				},
	// 				Status: &youtube.VideoStatus{
	// 					PrivacyStatus:           "public",
	// 					SelfDeclaredMadeForKids: false,
	// 				},
	// 			}

	// 			// Upload the video
	// 			call := service.Videos.Insert([]string{"snippet", "status"}, video)
	// 			call = call.Media(file)

	// 			response, err := call.Do()
	// 			if err != nil {
	// 				log.Fatalf("Error uploading video: %v", err)
	// 			}

	// 			videoID := response.Id
	// 			fmt.Printf("✅ YouTube upload successful! Video ID: %s\n", videoID)

	// 			// ✅ Upload thumbnail if the flag is provided
	// 			if strings.TrimSpace(thumbnailPath) != "" {
	// 				fmt.Println("📸 Waiting 10 seconds before uploading custom thumbnail...")

	// 				// Delay for 10 seconds to allow YouTube to process the video ID
	// 				time.Sleep(10 * time.Second)

	// 				err := uploadThumbnail(service, videoID, thumbnailPath)
	// 				if err != nil {
	// 					log.Fatalf("Error uploading thumbnail: %v", err)
	// 				}
	// 				fmt.Println("✅ Thumbnail uploaded successfully!")
	// 			}
	// 		case "bluesky":
	// 			fmt.Println("📢 Posting to BlueSky...")
	// 			err := PostToBlueSky(title, description)
	// 			if err != nil {
	// 				log.Printf("❌ Failed to post to BlueSky: %v", err)
	// 			} else {
	// 				fmt.Println("✅ BlueSky post successful!")
	// 			}
	// 		default: 
	// 			fmt.Printf("⚠️ Unknown platform: %s\n", platform)
	// 			continue
	// 	}
	// }
	return nil
}



func PostToBlueSky(title, description, youtubeLink string) error {
	// Retrieve BlueSky credentials
	username := os.Getenv("BLUESKY_USERNAME")
	password := os.Getenv("BLUESKY_PASSWORD")

	if username == "" || password == "" {
		return fmt.Errorf("❌ Failed to post to BlueSky: BlueSky credentials missing. Set BLUESKY_USERNAME and BLUESKY_PASSWORD")
	}

	// Authenticate to BlueSky
	accessToken, did, err := authenticateToBlueSky(username, password)
	if err != nil {
		return fmt.Errorf("❌ Failed to authenticate to BlueSky: %v", err)
	}

	// ✅ Create payload for the BlueSky post
	postData := map[string]interface{}{
		"repo": did,
		"collection": "app.bsky.feed.post",
		"record": map[string]interface{}{
			"$type": "app.bsky.feed.post",
			"text":  "",
			"createdAt": time.Now().Format(time.RFC3339),
			"embed": map[string]interface{}{
				"$type": "app.bsky.embed.external",
				"external": map[string]interface{}{
					"uri":   youtubeLink,
					"title": title,
					"description": description,
				},
			},
		},
	}

	// ✅ Convert payload to JSON
	postBody, err := json.Marshal(postData)
	if err != nil {
		return fmt.Errorf("❌ Failed to encode BlueSky post: %v", err)
	}

	// ✅ Send request to BlueSky API
	req, err := http.NewRequest("POST", "https://bsky.social/xrpc/com.atproto.repo.createRecord", bytes.NewBuffer(postBody))
	if err != nil {
		return fmt.Errorf("❌ Failed to create BlueSky post request: %v", err)
	}
	req.Header.Set("Authorization", "Bearer "+accessToken)
	req.Header.Set("Content-Type", "application/json")

	client := &http.Client{}
	resp, err := client.Do(req)
	if err != nil {
		return fmt.Errorf("❌ Failed to post to BlueSky: %v", err)
	}
	defer resp.Body.Close()

	// ✅ Handle response
	if resp.StatusCode != http.StatusOK {
		body, _ := ioutil.ReadAll(resp.Body)
		return fmt.Errorf("❌ BlueSky API error: %d %s\nResponse: %s", resp.StatusCode, http.StatusText(resp.StatusCode), string(body))
	}

	fmt.Println("✅ BlueSky post with embedded YouTube link created successfully!")
	return nil
}


// BlueSky authentication function
func authenticateToBlueSky(username, password string) (string, string, error) {
	// BlueSky API endpoint for authentication
	const blueskyAuthURL = "https://bsky.social/xrpc/com.atproto.server.createSession"
	// Create login payload
	payload := map[string]string{
		"identifier": username,
		"password":   password,
	}
	payloadBytes, _ := json.Marshal(payload)

	// Create POST request to BlueSky login endpoint
	req, err := http.NewRequest("POST", blueskyAuthURL, bytes.NewBuffer(payloadBytes))
	if err != nil {
		return "", "", fmt.Errorf("failed to create request: %v", err)
	}
	req.Header.Set("Content-Type", "application/json")

	// Send request
	client := &http.Client{}
	resp, err := client.Do(req)
	if err != nil {
		return "", "", fmt.Errorf("failed to send authentication request: %v", err)
	}
	defer resp.Body.Close()

	// Read response
	body, err := ioutil.ReadAll(resp.Body)
	if err != nil {
		return "", "", fmt.Errorf("failed to read authentication response: %v", err)
	}

	// Check for API errors
	if resp.StatusCode != http.StatusOK {
		return "", "", fmt.Errorf("BlueSky API authentication failed: %d %s\nResponse: %s", resp.StatusCode, http.StatusText(resp.StatusCode), body)
	}

	// Parse JSON response
	var authResponse struct {
		AccessJwt string `json:"accessJwt"` // ✅ Access token
		Did       string `json:"did"`       // ✅ Decentralized Identifier (DID)
	}
	if err := json.Unmarshal(body, &authResponse); err != nil {
		return "", "", fmt.Errorf("failed to parse authentication response: %v", err)
	}

	// ✅ Successfully retrieved BlueSky credentials
	fmt.Println("🔑 BlueSky authentication successful!")

	return authResponse.AccessJwt, authResponse.Did, nil
}

// truncateText shortens the description while preserving whole words and avoiding broken graphemes.
func truncateText(text string, maxLength int) string {
	if uniseg.GraphemeClusterCount(text) <= maxLength {
		return text
	}

	// Normalize text to prevent cutting in the middle of a grapheme
	normText := norm.NFC.String(text)

	// Split into words
	words := strings.Fields(normText)
	truncated := ""
	count := 0

	for _, word := range words {
		wordLength := uniseg.GraphemeClusterCount(word)
		if count+wordLength+1 > maxLength { // +1 for space
			break
		}
		if count > 0 {
			truncated += " "
		}
		truncated += word
		count += wordLength + 1
	}

	return truncated + "..." // Append ellipsis if truncated
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