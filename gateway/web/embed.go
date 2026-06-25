package web

import "embed"

// Dist 嵌入前端构建产物（gateway/web/dist）。
// 需先在 web-src/ 跑 `npm run build` 生成。
//
//go:embed all:dist
var Dist embed.FS
