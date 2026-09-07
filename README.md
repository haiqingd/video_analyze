# Video2Guide

把 B 站长视频（游戏攻略、教程等）一键压缩成**带时间戳跳转和关键画面截图的短文字攻略**。

```
B站视频 URL → 获取字幕(AI/CC) → GLM 分段总结 → 按攻略时间点截取关键画面 → Markdown/HTML 攻略文档
```

## 快速开始

```bash
# 1. 安装依赖（国内网络建议使用镜像源）
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 2.（可选）配置 .env
copy .env.example .env   # 填入 ZHIPU_API_KEY；也可启动后在前端「设置」里填写

# 3. 启动（会自动打开浏览器）
python run.py            # 默认 http://127.0.0.1:8300
```

使用：**粘贴视频链接 → 点「生成攻略」**，两步完成。其余选项（风格/截图数量）有默认值。

## 两个配置（按需）

| 配置 | 说明 | 获取方式 |
|---|---|---|
| **GLM API Key** | 调用大模型总结（默认模型 `glm-5.3-flash`，总结时自动关闭 thinking） | [open.bigmodel.cn](https://open.bigmodel.cn) 控制台 |
| **B 站 SESSDATA** | AI 智能字幕接口需要登录态 | 电脑浏览器登录 B 站 → F12 → 应用/存储 → Cookie → 复制 `SESSDATA` 的值 |

两者都可以写在 `.env` 或前端「设置」弹窗里（保存在本机浏览器 localStorage）。
不填 SESSDATA 时只有 UP 主上传了 CC 字幕的少数视频能直接成功；**没有可用字幕会自动降级为本地语音识别**（见下）。

## 功能说明

- **字幕三级策略**：本地缓存 → B 站字幕（CC 优先于 AI，逐轨下载并做健康度校验：条数≥30 且覆盖过半，防错配/残缺）→ **本地语音识别兜底**
- **本地 ASR 兜底**（`faster-whisper` medium，GPU 优先/CPU 回退）：音频下载 → CUDA 转写 → 与字幕同构的 cues；约 5 分钟处理 45 分钟视频（RTX 4070）
- **长视频 map-reduce**：字幕超过 9000 字自动分段提炼再汇总，3 小时视频也能处理
- **关键画面截图**：视频流走全局缓存（`output/cache/videos/`，跨任务复用），OpenCV 按攻略时间点截帧，失败自动降级为无图文档
- **时间戳跳转**：正文所有 `mm:ss` 自动转为 B 站带进度跳转链接
- **覆盖率体检**：字幕时长明显短于视频时，日志与结果页都会警告
- **产物**：`output/{任务ID}/` 下保留 `guide.md` / `guide.html` / `subtitle_raw.json` / 截图
- 支持完整链接 / BV 号 / av 号 / `b23.tv` 短链 / 多分P（`?p=n`）

## 抗风控与限流

- 下载全局互斥 + 指数退避重试（B 站 412）
- GLM 调用串行化 + 空内容/429/5xx 重试（编码套餐并发额度低）
- B 站接口请求带 Cookie 预热（buvid）

## ASR 模型

默认 `medium`（`ASR_MODEL` 可改）。模型文件放在 `models/faster-whisper-{size}/`
（config.json / model.bin / tokenizer.json / vocabulary.txt），
HF 不可达时可从 ModelScope 镜像下载，例如：
`https://modelscope.cn/models/Pengzhendong/faster-whisper-medium/resolve/master/model.bin`

## 项目结构

```
├── run.py              # 启动入口
├── app/
│   ├── main.py         # FastAPI 路由与静态服务
│   ├── jobs.py         # 任务管理与流水线编排（字幕缓存/ASR兜底/视频缓存）
│   ├── bilibili.py     # 视频元信息 / WBI 签名 / 字幕获取与校验
│   ├── asr.py          # faster-whisper 语音识别（GPU 优先，CUDA DLL 预加载）
│   ├── llm.py          # GLM 客户端 / map-reduce / 关键时刻提取
│   ├── frames.py       # yt-dlp 下载（互斥+退避）+ OpenCV 截帧
│   ├── docgen.py       # Markdown 组装与 HTML 渲染
│   └── transcript.py   # 字幕 cue → 分块文稿
├── prompts/            # 分段提炼 / 最终攻略 两套提示词
├── static/             # 前端单页（无构建依赖）
├── models/             # faster-whisper 模型文件（需自备）
└── output/             # 生成产物 + cache/（字幕与视频缓存）
```

## 已知限制

- B 站 AI 字幕存在**整轨错配**现象（字幕内容属于完全无关的其他视频，如股票/游戏解说话音），目前用覆盖率校验拦截，无法 100% 识别内容错配——遇到可疑总结请核对时间戳
- B 站风控（412）在短时间高频下载后可能持续数分钟，已做互斥与退避，仍偶发失败可稍后重试（字幕/视频缓存会复用，不浪费）
- 匿名下载只有 360p，截图清晰度受限（可后续支持带 Cookie 的更高清晰度下载）
- 仅供个人学习使用，请尊重视频版权，勿大规模抓取
