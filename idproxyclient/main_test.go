package idproxyclient

import (
	"bufio"
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"slices"
	"testing"
)

func TestGetAndAddSockets(t *testing.T) {
	// Create a temporary directory for mock sockets
	tmpDir, err := os.MkdirTemp("", "idproxy_sockets_test")
	if err != nil {
		t.Fatalf("Failed to create temp dir: %v", err)
	}
	defer os.RemoveAll(tmpDir)

	// Create mock socket directories and files
	socket1Dir := filepath.Join(tmpDir, "1")
	os.Mkdir(socket1Dir, 0755)
	socket1Path := filepath.Join(socket1Dir, "idproxy.sock")
	// Create actual Unix domain sockets
	l1, err := net.Listen("unix", socket1Path)
	if err != nil {
		t.Fatalf("Failed to listen on socket %s: %v", socket1Path, err)
	}
	defer l1.Close()

	socket2Dir := filepath.Join(tmpDir, "2")
	os.Mkdir(socket2Dir, 0755)
	socket2Path := filepath.Join(socket2Dir, "idproxy.sock")
	l2, err := net.Listen("unix", socket2Path)
	if err != nil {
		t.Fatalf("Failed to listen on socket %s: %v", socket2Path, err)
	}
	defer l2.Close()

	client := NewClient(tmpDir, "idproxy.sock")
	err = client.GetAndAddSockets()
	if err != nil {
		t.Fatalf("GetAndAddSockets failed: %v", err)
	}

	if len(client.sockets) != 2 {
		t.Errorf("Expected 2 sockets, got %d", len(client.sockets))
	}

	expectedSockets := []string{socket1Path, socket2Path}
	for _, expected := range expectedSockets {
		found := slices.Contains(client.sockets, expected)
		if !found {
			t.Errorf("Expected socket %s not found in client.sockets", expected)
		}
	}
}

func TestExecuteAuthorizedRequest(t *testing.T) {
	client := NewClientWithDefaults()
	client.sockets = []string{"/tmp/mock_socket_1", "/tmp/mock_socket_2"} // Mock sockets

	// Inject mock Dial function
	client.Dial = func(proto, addr string) (net.Conn, error) {
		clientConn, serverConn := net.Pipe()

		go func() {
			defer serverConn.Close()

			// Simulate server response
			req, err := http.ReadRequest(bufio.NewReader(serverConn))
			if err != nil {
				t.Errorf("Failed to read HTTP request: %v", err)
				return
			}
			defer req.Body.Close()

			reqBytes, err := io.ReadAll(req.Body)
			if err != nil {
				t.Errorf("Failed to read request body: %v", err)
				return
			}
			t.Logf("Mock server received request body: %s", string(reqBytes))

			var reqData map[string]interface{}
			err = json.Unmarshal(reqBytes, &reqData)
			if err != nil {
				t.Errorf("Failed to unmarshal request bytes: %v", err)
				return
			}
			t.Logf("Mock server unmarshaled request data: %+v", reqData)

			url, ok := reqData["url"].(string)
			if !ok {
				t.Errorf("URL not found or not a string in request data: %+v", reqData)
				return
			}
			data, ok := reqData["data"].(map[string]any)
			if !ok {
				t.Errorf("Data not found or not a map in request data: %+v", reqData)
				return
			}

			var respBody string
			var statusCode int = http.StatusOK
			if url == "http://example.com/success" && data["key"] == "value" {
				respBody = "success_response"
			} else {
				respBody = "error_response"
				statusCode = http.StatusInternalServerError // Simulate an error
			}

			resp := &http.Response{
				StatusCode: statusCode,
				Body:       io.NopCloser(bytes.NewBufferString(fmt.Sprintf(`"%s"`, respBody))),
				Header:     make(http.Header),
			}
			resp.Header.Set("Content-Type", "application/json")

			resp.Write(serverConn)
		}()
		return clientConn, nil
	}

	// Test successful request
	data := map[string]string{"key": "value"}
	resp, err := client.ExecuteAuthorizedRequest("http://example.com/success", data)
	if err != nil {
		t.Fatalf("ExecuteAuthorizedRequest failed: %v", err)
	}
	expected := []byte("success_response")
	if !bytes.Equal(resp, expected) {
		t.Errorf("Expected response %s, got %s", expected, resp)
	}

	// Test request with error (simulated by different URL/data)
	resp, err = client.ExecuteAuthorizedRequest("http://example.com/error", data)
	if err == nil {
		t.Fatalf("Expected ExecuteAuthorizedRequest to fail, but it succeeded")
	}
	if err.Error() != `all idproxy instances failed. last error: request to socket /tmp/mock_socket_1 failed with status 500: "error_response"` {
		t.Errorf("Expected error message to contain 'error_response', got %s", err.Error())
	}
}
