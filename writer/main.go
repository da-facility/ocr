package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"path/filepath"
	"time"

	"github.com/gorilla/websocket"
)

// OCR result structures
type Message struct {
	Results map[string]RegionResult `json:"results,omitempty"`
	Ping    bool                    `json:"ping,omitempty"`
}

type RegionResult struct {
	Text       string      `json:"text"`
	ScoreValue *int        `json:"score_value,omitempty"`
	Time       *TimeResult `json:"time,omitempty"`
}

type TimeResult struct {
	Formatted string `json:"formatted"`
}

// Session list response
type SessionsResponse struct {
	Sessions []Session `json:"sessions"`
}

type Session struct {
	ID   string `json:"id"`
	Name string `json:"name"`
}

var (
	host        = flag.String("host", "localhost:8000", "Backend server address")
	sessionID   = flag.String("session", "", "Session ID (auto-detects first session if not specified)")
	homeLabel   = flag.String("home", "home", "Home score region label")
	awayLabel   = flag.String("away", "away", "Away score region label")
	timeLabel   = flag.String("time", "time", "Time region label")
)

func main() {
	flag.Parse()

	log.Println("OCR Score Writer starting...")

	for {
		if err := run(); err != nil {
			log.Printf("Error: %v", err)
		}
		log.Println("Reconnecting in 500ms...")
		time.Sleep(500 * time.Millisecond)
	}
}

func run() error {
	session := *sessionID
	if session == "" {
		var err error
		session, err = getFirstSession()
		if err != nil {
			return fmt.Errorf("failed to get session: %w", err)
		}
		log.Printf("Auto-detected session: %s", session)
	}

	wsURL := fmt.Sprintf("ws://%s/ws/%s/ocr", *host, session)
	log.Printf("Connecting to %s", wsURL)

	conn, _, err := websocket.DefaultDialer.Dial(wsURL, nil)
	if err != nil {
		return fmt.Errorf("websocket dial failed: %w", err)
	}
	defer conn.Close()

	log.Println("Connected!")

	var lastScore, lastTime string

	for {
		_, msgBytes, err := conn.ReadMessage()
		if err != nil {
			return fmt.Errorf("read error: %w", err)
		}

		var msg Message
		if err := json.Unmarshal(msgBytes, &msg); err != nil {
			log.Printf("JSON parse error: %v", err)
			continue
		}

		if msg.Ping {
			continue
		}

		if msg.Results == nil {
			continue
		}

		// Extract scores
		homeScore := getScore(msg.Results, *homeLabel)
		awayScore := getScore(msg.Results, *awayLabel)
		scoreStr := fmt.Sprintf("%s:%s", homeScore, awayScore)

		// Extract time
		timeStr := getTime(msg.Results, *timeLabel)

		// Write score.txt if changed
		if scoreStr != lastScore {
			if err := writeFileAtomic("score.txt", scoreStr); err != nil {
				log.Printf("Failed to write score.txt: %v", err)
			} else {
				lastScore = scoreStr
			}
		}

		// Write time.txt if changed
		if timeStr != lastTime {
			if err := writeFileAtomic("time.txt", timeStr); err != nil {
				log.Printf("Failed to write time.txt: %v", err)
			} else {
				lastTime = timeStr
			}
		}
	}
}

func getFirstSession() (string, error) {
	url := fmt.Sprintf("http://%s/api/sessions", *host)
	resp, err := http.Get(url)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(resp.Body)
		return "", fmt.Errorf("API returned %d: %s", resp.StatusCode, string(body))
	}

	var response SessionsResponse
	if err := json.NewDecoder(resp.Body).Decode(&response); err != nil {
		return "", fmt.Errorf("failed to decode sessions: %w", err)
	}

	if len(response.Sessions) == 0 {
		return "", fmt.Errorf("no sessions found")
	}

	return response.Sessions[0].ID, nil
}

func getScore(results map[string]RegionResult, label string) string {
	if region, ok := results[label]; ok {
		if region.ScoreValue != nil {
			return fmt.Sprintf("%d", *region.ScoreValue)
		}
		if region.Text != "" {
			return region.Text
		}
	}
	return ""
}

func getTime(results map[string]RegionResult, label string) string {
	if region, ok := results[label]; ok {
		if region.Time != nil && region.Time.Formatted != "" {
			return region.Time.Formatted
		}
		if region.Text != "" {
			return region.Text
		}
	}
	return ""
}

func writeFileAtomic(filename, content string) error {
	dir := filepath.Dir(filename)
	if dir == "" {
		dir = "."
	}

	tmpFile, err := os.CreateTemp(dir, ".tmp-"+filepath.Base(filename))
	if err != nil {
		return err
	}
	tmpName := tmpFile.Name()

	_, err = tmpFile.WriteString(content)
	if err != nil {
		tmpFile.Close()
		os.Remove(tmpName)
		return err
	}

	if err := tmpFile.Close(); err != nil {
		os.Remove(tmpName)
		return err
	}

	if err := os.Rename(tmpName, filename); err != nil {
		os.Remove(tmpName)
		return err
	}

	return nil
}
