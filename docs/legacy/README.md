# Legacy 文档（V1 Go 架构，已废弃）

> ⚠️ 本目录的文档描述的是 **AgentOS V1（Go 内核 + 网关 + gRPC 运行时）** 架构。
> 当前实现已迁移到 **Python 控制面（`cp/` 包，V2 架构）**，见 `docs/AgentOS架构设计重点关注V2.md`。
>
> 这些文档仅作**历史参考**保留,其中的:
> - Go 构建命令(`go run`、`go build`、`protoc`)
> - gRPC / Unix socket 三进程协作模型(Kernel / Gateway / Runtime)
> - "当前权威"等状态标注
>
> **均已过时,不反映当前实现。** 不要据此搭建或理解系统。

## 内容

### specs/ — V1 设计规格

| 文件 | 说明 |
|------|------|
| `2026-06-23-agentos-mvp-design.md` | "方案 A" Go 内核 MVP 设计 |
| `2026-06-24-agentos-mvp-design-v2.3.md` | v2.3 设计(标"✅已实现"但指的是 Go 代码) |
| `2026-06-25-agentos-product-vision.md` | 产品愿景(当时把 V2 降为"远期参考";现状已反转) |
| `2026-06-25-agentos-realtime-console-slice-a.md` | 实时控制台 slice(Go Gateway + gRPC) |
| `2026-06-29-console-visual-redesign.md` | 控制台视觉重设计(架构中性,纯 UX) |

### plans/ — V1 实现计划

| 文件 | 说明 |
|------|------|
| `2026-06-23-agentos-mvp.md` | Go 内核 MVP 实现计划 |
| `2026-06-24-agentos-mvp-v2.3.md` | v2.3 实现计划 |
| `2026-06-25-agentos-realtime-console-slice-a.md` | 控制台 slice 实现 |
| `2026-06-29-console-visual-redesign.md` | 视觉重设计实现 |

## 当前权威文档

- **架构 SSOT**: `docs/AgentOS架构设计重点关注V2.md`
- **实现计划**: `docs/superpowers/plans/2026-07-*-python-cp-*.md`(Week 1–6)
