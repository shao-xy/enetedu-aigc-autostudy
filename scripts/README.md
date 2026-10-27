# 自动刷课脚本

针对 `aigc.enetedu.com`（2026年人工智能赋能高等教育系列师资培训平台）的学习进度上报脚本。
协议逆向自浏览器 HAR，并经服务端行为实测验证。

## 目录结构

```
scripts/
├── .gitignore
└── autostudy/
    ├── client.py             # 平台接口封装
    ├── study.py              # 刷课核心逻辑
    ├── main.py               # 命令行入口
    ├── config.example.json   # 配置模板
    └── config.json           # 实际配置（含 token，已 gitignore）
```

## 环境要求

- Python 3.10+
- `requests`

```bash
pip install requests
```

不改动全局 Python 环境即可运行。

## 配置

```bash
cd scripts/autostudy
cp config.example.json config.json
```

编辑 `config.json`：

| 字段 | 说明 |
| --- | --- |
| `access_token` | 登录后的 access token，见下方「获取 token」 |
| `topic_id` | 研修班（专题）id，如 `180200` |
| `course_id` | 要刷的课程 id |
| `speed` | 倍速。位置与累计时长推进的快慢 |
| `report_interval` | 心跳间隔（秒） |
| `chunk_seconds` | 单次上报的观看增量上限（秒），默认 100 |
| `settle_wait` | 上报后等多久读状态（秒），默认 35 |

### 获取 token

**只需复制一个值**：登录平台后，浏览器 DevTools → Application → Cookies，
复制 `futureTeachersToken` 的值，填入 `config.json` 的 `access_token`。

实测认证最小依赖集：

| 项 | 必需性 |
| --- | --- |
| `Authorization: Bearer <access_token>` | **唯一必需** |
| Cookie `futureTeachersToken` | 非必需（带上更贴近真实浏览器） |
| `tenant-id` / `visit-tenant-id` 头 | 非必需 |
| Cookie `p_h5_u` / `acw_tc` / `selectedCC` / `tenantId` | 无关，CDN 与播放器埋点用 |
| User-Agent | 非必需 |

Token 过期时接口返回 HTTP 200 + `code=401` + `msg=访问令牌不存在`，脚本会提示。
过期后重新登录、复制新值即可。

## 使用

```bash
cd scripts/autostudy

python main.py --status    # 查看所有课程的学习状态
python main.py --list      # 列出专题下全部课程
python main.py             # 刷 config.json 里指定的那门课
python main.py --all       # 刷专题下所有未完成课程
python main.py --course <courseId>   # 刷指定课程
python main.py --dry-run   # 只打印上报内容，不真正提交
```

## 协议说明

进度上报接口：

```
POST /admin-api/course/learning-detail/create
{
  "videoId":     "15072001",
  "courseId":    "2110260665179574273",
  "chapterId":   "",
  "fileName":    "15072001",
  "pid":         "",
  "duration":    "71:33",   // 当前播放位置
  "totalDuration": "0:13",  // 本次心跳新增的观看秒数
  "maxPlayedTime": "71:33", // 历史最远播放位置
  "topicId":     "180200"
}
```

字段语义（实测结论）：

- `duration` / `maxPlayedTime` —— 播放位置。服务端对 `maxPlayedTime` 取单调最大值，回退无效。
- `totalDuration` —— **本次心跳新增的观看秒数**，不是视频总长。服务端把它累加成累计观看时长。
- **课程「已完成」的判定依据是累计观看时长是否达到课程要求学时**
  （`topic-detail` 里的 `durationTime`，单位小时），与播放位置无关。
- 服务端**不校验墙钟时间**，但要求单次上报的「位置推进量」与「观看增量」一致
  （位置前进多少，增量就是多少），否则该笔会被整笔丢弃。
- 单笔观看增量不宜超过 100 秒，超出时丢弃率上升。
- 服务端**落库是异步的**，实测约 27~30 秒延迟后 `treeList` 才能读到新值。
  脚本刷完一门课后会等 35 秒再校验状态，等待期间每 5 秒输出一次倒计时提示。

其它接口：

| 接口 | 用途 |
| --- | --- |
| `GET /admin-api/system/auth/queryUserInfo` | 校验登录态 |
| `GET /app-api/home/api/future-teacher/course-table/topic-detail` | 专题详情、课程清单与完成数 |
| `GET /admin-api/course/learning-detail/treeList` | 课程下的视频列表与当前进度 |
| `GET /admin-api/media/meet/get` | 视频真实时长（`transcription.Transcription.AudioInfo.Duration`，毫秒） |
| `GET /admin-api/media/online-course/getSimpleCourseInfo` | 单门课程信息 |

## 实现要点

1. **真实时长**取自 `media/meet/get` 的转写音频时长，比平台登记的 `duration` 准确。
2. **增量与位置同步**：每笔上报让 `duration` 前进 N 秒，`totalDuration` 也报 N 秒，
   避免服务端因位置跳变过大而丢弃。
3. **累计时长读回**：从 `treeList` 的 `totalDuration` 读服务端已累计的值，
   断点续刷时不会重复计数。
4. **幂等**：已完成的课程会被跳过；重复运行只会补齐剩余时长。

## 已验证结果

「AI赋能项目式教学创新设计：从理论到实践」（视频真实时长 72:05，要求 1.2 小时）
实跑后服务端状态由「学习中」变为「已完成」，进度 100%，专题已完成数 1 → 2。

## 说明

- 脚本只做进度上报，不下载视频、不拉取转写内容。
- `config.json` 含登录凭据，已在 `.gitignore` 中排除，不要提交。
- 完整技术档案（接口清单、字段语义、实测证据、反模式清单）见
  [`../docs/aigc-enetedu-autostudy.md`](../docs/aigc-enetedu-autostudy.md)。
