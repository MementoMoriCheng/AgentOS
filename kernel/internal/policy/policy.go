package policy

import (
	"os"

	"gopkg.in/yaml.v3"
)

// Rule 是一条权限规则：某资源类型 + glob 模式 + 允许的动作集合。
type Rule struct {
	ResourceType string   `yaml:"resource_type"`
	Pattern      string   `yaml:"pattern"`
	Actions      []string `yaml:"actions"`
}

// Policy 是授予一个 agent 会话的完整策略。
type Policy struct {
	AgentRole        string `yaml:"agent_role"`
	Permissions      []Rule `yaml:"permissions"`
	SanitizationPath string `yaml:"sanitization_path"`
	MaxSteps         int    `yaml:"max_steps"`
	MaxTokens        int    `yaml:"max_tokens"`
}

// LoadFromFile 从 YAML 文件加载策略。max_steps 为 0 时默认 20。
func LoadFromFile(path string) (*Policy, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	var p Policy
	if err := yaml.Unmarshal(data, &p); err != nil {
		return nil, err
	}
	if p.MaxSteps == 0 {
		p.MaxSteps = 20
	}
	return &p, nil
}
