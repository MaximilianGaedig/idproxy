package idproxyclient

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"io/fs"
	"net"
	"net/http"
	"os"
	"path"
	"slices"
	"sync"
	"sync/atomic"
)

const DefaultSocketsRootPath = "/tmp/idproxy_sockets"
const DefaultSocketName = "idproxy.sock"

type IDProxyClient struct {
	SocketsRootPath string
	SocketName      string
	sockets         []string
	currentSocket   atomic.Int32
	socketMutex     sync.RWMutex
	Dial            func(proto, addr string) (net.Conn, error) // For testing
}

func NewClient(socketsRootPath string, socketName string) *IDProxyClient {
	return &IDProxyClient{
		SocketsRootPath: socketsRootPath,
		SocketName:      socketName,
		sockets:         []string{},
		currentSocket:   atomic.Int32{},
	}
}

func NewClientWithDefaults() *IDProxyClient {
	return NewClient(DefaultSocketsRootPath, DefaultSocketName)
}

func (c *IDProxyClient) GetAndAddSockets() error {
	sockets, err := c.getSockets()
	if err != nil {
		return fmt.Errorf("get sockets: %w", err)
	}

	c.addSockets(sockets)
	return nil
}

// ExecuteAuthorizedRequest executes an authorized request proxied trough idproxy
// It will try all available sockets until one succeeds.
func (c *IDProxyClient) doRequest(sock string, jsonBody []byte) ([]byte, error) {
	dialFunc := c.Dial
	if dialFunc == nil {
		dialFunc = func(proto, addr string) (net.Conn, error) {
			return net.Dial("unix", sock)
		}
	}

	tr := &http.Transport{
		Dial: dialFunc,
	}
	client := &http.Client{Transport: tr}

	req, err := http.NewRequest("PUT", "http://localhost/", bytes.NewBuffer(jsonBody))
	if err != nil {
		return nil, fmt.Errorf("failed to create request: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")

	resp, err := client.Do(req)
	if err != nil {
		return nil, fmt.Errorf("failed to execute request to socket %s: %w", sock, err)
	}
	defer resp.Body.Close()

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("failed to read response body from socket %s: %w", sock, err)
	}

	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("request to socket %s failed with status %d: %s", sock, resp.StatusCode, string(body))
	}

	var decodedBody string
	if err := json.Unmarshal(body, &decodedBody); err != nil {
		return nil, fmt.Errorf("failed to unmarshal response from idproxy: %w. Body: %s", err, string(body))
	}

	return []byte(decodedBody), nil
}

// ExecuteAuthorizedRequest executes an authorized request proxied trough idproxy
// It will try all available sockets until one succeeds.
func (c *IDProxyClient) ExecuteAuthorizedRequest(url string, data any) ([]byte, error) {
	c.socketMutex.RLock()
	defer c.socketMutex.RUnlock()

	if len(c.sockets) == 0 {
		return nil, fmt.Errorf("no sockets available")
	}

	idproxyReqBody := map[string]any{
		"url":  url,
		"data": data,
	}
	jsonBody, err := json.Marshal(idproxyReqBody)
	if err != nil {
		return nil, fmt.Errorf("failed to marshal idproxy request body: %w", err)
	}

	numSockets := len(c.sockets)
	startOffset := c.currentSocket.Add(1) - 1

	var lastErr error
	for i := range numSockets {
		socketIdx := (startOffset + int32(i)) % int32(numSockets)
		sock := c.sockets[socketIdx]

		respBody, err := c.doRequest(sock, jsonBody)
		if err == nil {
			return respBody, nil
		}
		lastErr = err
	}

	return nil, fmt.Errorf("all idproxy instances failed. last error: %w", lastErr)
}

func (c *IDProxyClient) getSockets() ([]string, error) {
	entries, err := os.ReadDir(c.SocketsRootPath)
	if err != nil {
		return nil, fmt.Errorf("list files in socket root (%s): %w", c.SocketsRootPath, err)
	}

	sockets := []string{}

	for _, entry := range entries {
		if entry.IsDir() {
			subPath := path.Join(c.SocketsRootPath, entry.Name())
			subEntries, err := os.ReadDir(subPath)
			if err != nil {
				return nil, fmt.Errorf("list files in socket root subdirectory (%s): %w", entry.Name(), err)
			}

			for _, subEntry := range subEntries {
				if !subEntry.IsDir() && subEntry.Name() == c.SocketName && (subEntry.Type()&fs.ModeSocket > 0) {
					sockets = append(sockets, path.Join(subPath, subEntry.Name()))
				}
			}
		}
	}

	return sockets, nil
}

func (c *IDProxyClient) addSockets(paths []string) {
	c.socketMutex.Lock()
	defer c.socketMutex.Unlock()

	for _, path := range paths {
		exists := slices.Contains(c.sockets, path)
		if !exists {
			c.sockets = append(c.sockets, path)
		}
	}
}

