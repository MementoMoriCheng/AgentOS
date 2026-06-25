package kclient

import (
	"context"
	"io"
	"sync"

	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"

	pb "agentos/pb"
)

// Client 连 Kernel gRPC。
type Client struct {
	conn   *grpc.ClientConn
	stub   pb.KernelClient
	socket string
	once   sync.Once
	err    error
}

func New(socket string) *Client {
	return &Client{socket: socket}
}

// dialTarget 拼 gRPC unix socket target。
// Go grpc 在所有平台都用 unix: 前缀（与 Python grpc 的 file:// 不同）。
func dialTarget(socket string) string {
	return "unix:" + socket
}

func (c *Client) ensure() error {
	c.once.Do(func() {
		c.conn, c.err = grpc.Dial(dialTarget(c.socket),
			grpc.WithTransportCredentials(insecure.NewCredentials()))
		if c.err == nil {
			c.stub = pb.NewKernelClient(c.conn)
		}
	})
	return c.err
}

func (c *Client) StartSession(ctx context.Context, policy, sanitization string) (string, error) {
	if err := c.ensure(); err != nil {
		return "", err
	}
	resp, err := c.stub.StartSession(ctx, &pb.StartSessionRequest{PolicyPath: policy, SanitizationPath: sanitization})
	if err != nil {
		return "", err
	}
	return resp.SessionId, nil
}

func (c *Client) EndSession(ctx context.Context, sessionID, reason string) error {
	if err := c.ensure(); err != nil {
		return err
	}
	_, err := c.stub.EndSession(ctx, &pb.EndSessionRequest{SessionId: sessionID, Reason: reason})
	return err
}

// Subscribe 订阅事件流；handler 在调用 goroutine 里被调用，直到 ctx 取消或流断。
// 流断时返回 error（调用方可重连）。
func (c *Client) Subscribe(ctx context.Context, sessionID string, handler func(*pb.Event)) error {
	if err := c.ensure(); err != nil {
		return err
	}
	stream, err := c.stub.SubscribeEvents(ctx, &pb.SubscribeEventsRequest{SessionId: sessionID})
	if err != nil {
		return err
	}
	for {
		ev, err := stream.Recv()
		if err == io.EOF {
			return nil
		}
		if err != nil {
			return err
		}
		handler(ev)
	}
}

func (c *Client) Close() {
	if c.conn != nil {
		c.conn.Close()
	}
}
