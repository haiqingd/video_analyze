# Video2Guide 部署指南（Docker）

## 一、前置条件

| 依赖 | 说明 |
|---|---|
| Docker 20+ | Windows 装 [Docker Desktop](https://www.docker.com/products/docker-desktop/)；Linux 装 Docker Engine + Compose 插件 |
| 磁盘 | ≥ 10GB（镜像 ~2GB + ASR 模型 ~3.2GB + 视频缓存会随使用增长） |
| 网络 | 需访问 B 站 / 智谱 API / ModelScope（国内直连即可） |

> GPU 不是必须的：没有显卡时语音识别自动回退 CPU（约慢 5-10 倍，其余功能不受影响）。

## 二、快速部署（5 步）

```bash
# 1. 准备配置（必填两项：GLM Key、访问密钥）
cp .env.example .env
#    编辑 .env：
#    ZHIPU_API_KEY=你的智谱Key（open.bigmodel.cn 获取）
#    ACCESS_KEY=分发给使用者的访问密钥（默认 va2026，务必修改）
#    GLM_MODEL / GLM_FINAL_MODEL / GLM_BASE_URL 按需调整

# 2. 下载 ASR 模型（一次性，约 3.2GB，走国内镜像）
python scripts/download_models.py
#    没有本地 Python？也可以起容器后进容器下载（见附录 A）

# 3. 构建并启动
#    国内网络（Docker Hub 被墙）用镜像源构建：
docker compose build --build-arg BASE_IMG=docker.m.daocloud.io/library/python:3.12-slim
docker compose up -d
#    海外网络直接：docker compose up -d --build

# 4. 查看状态
docker compose logs -f          # Ctrl+C 退出日志
docker compose ps               # 应显示 running

# 5. 打开页面
#    http://127.0.0.1:8300      （本机）
#    http://<局域网IP>:8300     （同网段其他人；.env 里 HOST 已由 compose 设为 0.0.0.0）
```

## 三、目录与数据说明

| 挂载卷 | 内容 | 备份策略 |
|---|---|---|
| `./output` | 全部攻略产物、字幕/视频缓存、评论 | **备份这个目录 = 备份全部数据** |
| `./models` | ASR 模型文件 | 可随时用脚本重新下载 |
| `./prompts` | 提示词 | 改提示词**无需重建镜像**，改完重启容器即生效 |

迁移到另一台机器：拷贝整个项目目录（含 output/models/.env）→ `docker compose up -d --build`。

## 四、常用运维

```bash
docker compose restart          # 重启（改 .env / 提示词后执行）
docker compose down             # 停止
docker compose up -d --build    # 改代码后重建启动
docker compose logs -f --tail=100
```

**批量补新集**（UP 主更新合集后）：进入容器跑批量脚本——

```bash
docker compose exec video2guide python batch_series.py
```

注意：`batch_series.py` 顶部的 `REFERENCE_URL`（参考文档链接）与 `CURRENT_GEN_SINCE`（断点时间）按需修改。

## 五、GPU 加速（可选，强烈建议有显卡的机器开启）

1. 宿主机安装 [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html)（Windows 装 NVIDIA 驱动 + Docker Desktop WSL2 后端即可）
2. 编辑 `docker-compose.yml`，取消 `deploy.resources` 段的注释
3. `docker compose up -d --build`

验证 GPU 生效：日志或任务日志里 ASR 速度明显变快（45 分钟视频约 1 分钟内识别完）。

## 六、功能速查

- **访问密钥**：首次点「生成攻略」会要求输入密钥（即 .env 的 `ACCESS_KEY`），输入正确后浏览器记住；页面提示联系邮箱可在 `app/main.py` 与 `static/index.html` 中修改
- **分享攻略**：文章页「导出 .v2g」→ 对方在首页「导入」选择该文件，即获得完整文章（含截图、评论、时间戳跳转）
- **B 站字幕**：在页面「设置」里填 SESSDATA 可直接用 B 站 AI 字幕；不填则自动走本地语音识别（更准但更慢）
- **参考文档**：首页的「参考文档链接」填腾讯文档分享链接，每次解析实时拉取最新内容注入总结

## 七、常见问题

| 现象 | 原因与处理 |
|---|---|
| 音频/视频下载失败（412/5xx） | B 站风控，通常几分钟后自动重试通过；持续失败等半小时再跑 |
| `Invalid token ID` 日志后任务仍成功 | turbo 模型个别音频的已知问题，已内置自动回退 medium，无需处理 |
| 容器内 ASR 很慢 | 没启用 GPU（见第五节），或 CPU 较弱；属正常，可耐心等待 |
| GLM 401 | `.env` 的 Key 过期/错误；容器内改 `.env` 后 `docker compose restart` |
| 页面 403 | 访问密钥不对；确认 `ACCESS_KEY` 与使用者输入一致 |
| 端口冲突 | 改 `docker-compose.yml` 的 `ports: "8301:8300"` 换宿主端口 |

## 附录 A：没有本地 Python 时，在容器里下载模型

```bash
docker compose up -d --build           # 先用 CPU 模式把容器跑起来（此时尚无模型，ASR 功能不可用）
docker compose exec video2guide python scripts/download_models.py turbo
docker compose restart
```

## 附录 B：局域网分享给朋友

1. 部署机防火墙放行 8300 端口（Windows：防火墙 → 入站规则 → 新建 TCP 8300）
2. 朋友访问 `http://<你的IP>:8300`，输入你分发的访问密钥即可使用
3. **不要直接暴露到公网**；如需公网访问，建议套一层带鉴权的反向代理（如 nginx + basic auth 或 frp 隧道）
