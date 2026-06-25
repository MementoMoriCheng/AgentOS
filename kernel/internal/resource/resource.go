package resource

// Resource 是权限判定的泛化对象。
// Type 决定匹配哪类规则（path/db_table/http_url...），ID 是具体标识。
type Resource struct {
	Type string
	ID   string
}
