# BiliDM Adapter Plugin

B站（BiliBili）私信适配器插件，允许 KiraAI 通过 B站私信与用户进行交互。

本插件通过 KiraAI 插件系统的 `ctx.register_adapter()` 接口注册适配器，安装到 `data/plugins/` 后即可在 WebUI 中创建 `BiliDM` 类型的适配器实例。

## 功能特性

| 消息类型 | 接收 | 发送 |
|---------|------|------|
| 文本 (TEXT) | ✅ | ✅ |
| 图片 (PICTURE) | ✅ | ✅ |
| 分享视频 (SHARE_VIDEO) | ✅ | — |
| 表情 (EMOJI) | — | ✅ |

### 详细说明

- **接收文本消息**：直接提取文本内容
- **接收图片消息**：通过 Cookie 鉴权下载图片，转为 Base64 Data URL 传递给下游
- **接收分享视频**：调用 `Video.get_info()` 获取视频标题、UP主、播放量、点赞数等信息，拼接为富文本
- **发送文本消息**：通过 `send_msg` 发送纯文本
- **发送图片消息**：支持 URL 和 Base64 两种图片来源
- **发送表情**：通过 `emoji.json` 映射表将 Emoji ID 转为 Unicode 字符发送
- **用户昵称解析**：通过 `User.get_user_info()` API 获取真实昵称，带内存缓存

## 配置项

在 WebUI 中创建 BiliDM 适配器后，可配置以下字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `bot_uid` | string | 机器人账号的 B站 UID |
| `permission_mode` | string | 权限模式：`allow_list`（白名单）或 `deny_list`（黑名单） |
| `user_allow_list` | list | 白名单用户 UID 列表 |
| `user_deny_list` | list | 黑名单用户 UID 列表 |
| `sesdata` | string | B站 Cookie 中的 `SESSDATA` |
| `bili_jct` | string | B站 Cookie 中的 `bili_jct`（CSRF Token） |
| `buvid3` | string | B站 Cookie 中的 `buvid3` |
| `dedeuserid` | string | B站 Cookie 中的 `DedeUserID` |
| `ac_time_value` | string | B站 Cookie/LocalStorage 中的 `ac_time_value` |

## 获取 Cookie

1. 使用浏览器登录 [bilibili.com](https://www.bilibili.com)
2. 打开浏览器开发者工具（F12）→ Application → Cookies
3. 找到并复制以下字段的值：
   - `SESSDATA`
   - `bili_jct`
   - `buvid3`
   - `DedeUserID`
   - `ac_time_value`

> ⚠️ **注意**：Cookie 有效期有限，过期后需重新获取并更新配置。

## 依赖

- `bilibili_api` — B站 API 封装库（KiraAI 核心依赖，>= 17.4.0）
- `httpx` — 异步 HTTP 客户端（用于图片下载）

## 文件结构

```
kira-ai-ada-bilidm/
├── main.py              # 插件入口，通过 ctx.register_adapter("adapter") 注册适配器
├── manifest.json        # 插件元信息
├── icon.svg             # 插件图标
├── README.md            # 本文件
└── adapter/             # 适配器组件目录
    ├── adapter.py       # 适配器主实现（BiliDMAdapter）
    ├── manifest.json    # 适配器元信息（platform 名称：BiliDM）
    ├── schema.json      # 配置字段定义（供 WebUI 渲染）
    ├── emoji.json       # 表情 ID → Unicode 映射表
    └── icon.svg         # 适配器图标
```

## 注意事项

- 图片下载需要携带 B站 Cookie 才能正常访问，适配器内部已自动处理
- `send_group_message` 不被 B站私信支持，会自动降级为私信发送并输出警告日志
- 适配器使用 `Session` 轮询机制，约每 6 秒检查一次新消息
- 禁用或卸载插件时，KiraAI 会自动停止并注销该平台的所有适配器实例
