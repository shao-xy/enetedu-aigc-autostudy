# 项目交接说明

> **这份文档面向两类读者**：
> - **接手的人类开发者**：从「项目是什么」到「怎么跑」到「坑在哪」，5 分钟内能上手。
> - **新接手的大模型智能体**：本文件是**权威的快速上下文**，读完即可动手；
>   需要接口细节、字段语义、实测证据时再查 [`aigc-enetedu-autostudy.md`](aigc-enetedu-autostudy.md)。
>
> 两者冲突时，以 `aigc-enetedu-autostudy.md`（完整技术档案，含实测证据）为准。

---

## 1. 一句话概括

针对 `https://aigc.enetedu.com`（2026 年人工智能赋能高等教育系列师资培训平台）的
**学习进度上报脚本**。逆向自浏览器 HAR，经服务端行为实测验证，可让课程被平台判定为「已完成」。

**项目状态：已完成并验证。** 原作者账号的研修专题 16/16 门课程全部完成，进度 100%，
证书已打印。

---

## 2. 快速上手（3 步）

```bash
cd scripts/autostudy
cp config.example.json config.json     # 复制配置模板
# 编辑 config.json：只填 access_token 一处
python main.py --status                # 验证环境
```

### 唯一必填项：`access_token`

浏览器登录平台 → F12 → **Application** → **Cookies** → `https://aigc.enetedu.com`
→ 复制 `futureTeachersToken` 的 Value，填入 `config.json` 的 `access_token`。

> 实测认证最小依赖集：**只有 `Authorization: Bearer <token>` 必需**。
> Cookie 同名值、`tenant-id` / `visit-tenant-id` 头、User-Agent **均非必需**。
> 详见技术档案 §2（10 组实测矩阵）。
>
> Token 过期表现：HTTP 200 + `code=401` + `msg=访问令牌不存在`（**不是** HTTP 401）。
> 重新登录复制新值即可。

### `topic_id` / `course_id` 留空即可

脚本自动推导，无需手工查 id：

| 参数 | 来源 |
| --- | --- |
| 专题 id | `GET /app-api/home/api/future-teacher/course-table/my-topics` → 只有一个则自动选中；多个用 `--topic <id>` 指定 |
| 课程清单 | `GET /app-api/home/api/future-teacher/course-table/topic-detail` → `courses[]`（本账号被勾选的清单） |

配置里若残留他人账号的旧 id，脚本会校验权限并**自动降级并提示**，不会报错。

### 命令

```bash
python main.py --topics    # 列出本账号可访问的专题
python main.py --status    # 各课程学习状态
python main.py --list      # 列出专题下所有课程
python main.py             # 刷指定课程（未指定则刷全部未完成课程）
python main.py --all       # 刷全部未完成课程
python main.py --course <courseId>   # 刷指定课程
python main.py --topic <topicId>     # 有多个专题时指定
python main.py --dry-run   # 只打印上报体，不提交
```

依赖：Python 3.10+ 与 `requests`。未修改全局 Python 环境。

---

## 3. 核心协议（改代码前必读）

上报接口：

```
POST /admin-api/course/learning-detail/create
```

| 字段 | 语义 | 坑 |
| --- | --- | --- |
| `duration` | 当前播放位置 `mm:ss` | — |
| `maxPlayedTime` | 历史最远位置 | 服务端取**单调最大值**，回退无效 |
| `totalDuration` | **本次心跳新增的观看秒数** | ⚠️ **不是视频总长！** |
| `videoId` / `fileName` | 视频标识（两者同值） | — |
| `courseId` / `topicId` | 课程 / 专题 id | — |
| `chapterId` / `pid` | 本平台为空串 | — |

### 四条最容易踩错的规则

1. **`totalDuration` 必须是增量，不是累计值。**
   服务端会把各笔增量累加成累计观看时长。报累计值 → 严重虚高；报视频总长 → 进度瞬间冲顶。

2. **单笔「位置推进量」必须等于「观看增量」。**
   位置前进多少，增量就报多少。不一致 → **该笔整条被丢弃**，但 HTTP 仍返回 200 + `处理成功`，
   **没有任何报错**。这是最容易误判「服务端拒绝」的地方。

3. **课程「已完成」的判定依据是累计观看时长 ≥ 要求学时**（`durationTime`，单位小时），
   **与播放位置无关**。不要以为把播放位置推到片尾就完成了。

4. **服务端落库是异步的，延迟约 27~30 秒。**
   上报后立刻读状态会读到旧值 → **误判失败**。
   脚本默认 `settle_wait=35`（30s + 余量），等待期间每 5 秒打印倒计时，避免看起来卡死。

> ⚠️ **第 4 点是本项目最大的坑**。早期实验因读得太快而误判为「服务端拒绝」，
> 差点得出完全错误的协议。任何验证写操作后，必须 sleep ≥ 30 秒再读状态。

### 反模式速查

| ✗ 错误 | ✓ 正确 |
| --- | --- |
| `totalDuration` 填视频总长（72:05） | 填本次增量（如 `"1:40"`） |
| 把 `duration` 推到片尾就以为完成 | 累计时长须达到 `durationTime` 要求学时 |
| 位置跳 200 秒而增量报 20 秒 | 两者必须相等 |
| 上报后立刻读状态判断成功/失败 | sleep ≥ 30s 再读 |
| 单笔增量超过 100 秒 | 控制在 100s 以内，丢弃率上升 |
| 用 `getVideoCourseListByTopic` 当课程清单 | 用 `topic-detail` 的 `courses[]`（前者实测少 6 门） |
| 硬编码课程 id | 每次动态读取 |

完整反模式清单见技术档案 §7.3。

---

## 4. 代码结构

```
仓库根
├── .gitignore                # 排除含凭据的 config.json
├── docs/
│   ├── handoff.md            # 本文件：快速交接
│   └── aigc-enetedu-autostudy.md   # 完整技术档案（10 节 + 2 附录）
└── scripts/
    ├── README.md             # 快速上手
    └── autostudy/
        ├── client.py         # 接口封装（Client 类）
        ├── study.py          # 刷课核心（StudyRunner）
        ├── main.py           # CLI 入口
        ├── config.example.json
        └── config.json       # 实际配置（含 token，未入库）
```

| 模块 | 职责 |
| --- | --- |
| `client.py` | 平台接口封装。`Client` 类，含 `my_topics()` / `topic_detail()` / `topic_courses()` / `lessons()` / `media_duration_ms()` / `report_progress()` |
| `study.py` | 刷课核心。`StudyRunner` 类，负责「算增量 → 上报 → 等落库 → 校验」的循环 |
| `main.py` | CLI 入口。参数解析 + 专题自动推导 + 权限校验降级 |

### 关键实现决策

| 决策 | 理由 |
| --- | --- |
| 真实时长取自 `media/meet/get` 的 `AudioInfo.Duration` | 平台登记的 `duration` 字段不可靠（目标课登记 17:31，真实 72:05） |
| 目标时长 = `max(要求学时秒数, 视频真实时长)` | 覆盖两种判定口径 |
| 累计时长从 `treeList` 读回 | 断点续刷不重复计数 |
| 单笔增量上限 100 秒 | 实测超过 100s 时丢弃率上升 |
| `maxPlayedTime` 与 `duration` 同值上报 | 避免触发单调性检查异常 |

---

## 5. 幂等性与幂等验证

- 已完成课程（`learningStatus == 2`）自动跳过。
- 累计时长从服务端读回，续跑只补差额。
- **可反复运行，不会重复计数。** 已验证：重复运行时已完成的课程被正确跳过。

---

## 6. 实测验证记录

| 项 | 结果 |
| --- | --- |
| 目标课「AI赋能项目式教学创新设计：从理论到实践」 | 视频真实 72:05，要求 1.2h → 服务端「学习中」→「已完成」，`learningProgress=100%` |
| 专题完成数 | 1 → 2 → 4 → 5 → **16（全部完成）** |
| 落库延迟 | t+27s 可见新值 |
| 认证最小集 | 10 组矩阵，仅 `Authorization` 必需 |
| 专题自动推导 | `--topics` / `--status` 在 `topic_id` 留空时正常工作 |
| 权限降级 | 填他人 id 时提示并降级，不抛异常 |
| 幂等 | 重复运行正确跳过已完成课程 |
| 脱敏 | 姓名/手机号/真 token 均未入库；全部历史提交扫描 0 命中 |

**副作用**：「人工智能赋能教育变革」在沙盒验证中被服务端判为已完成（2.2h/1.0h），
需在平台上重置才能还原。另有 3 门课程用于排除性实验。

---

## 7. 已知限制与风险

| 项 | 说明 |
| --- | --- |
| 平台风控 | 服务端有防跳逻辑（位置/增量一致性校验）。当前实测通过，但平台规则可变 |
| 账号风险 | 异常高频上报可能触发人工审核。当前节律接近真实播放，风险较低 |
| 凭据泄露 | `config.json` 已 gitignore。**不要把填好 token 的 `config.json` 打包发给别人** |
| 用途范围 | 仅用于本人账号的学习进度上报，不涉及视频下载、转写抓取或他人账号 |
| 证书条件 | 需完成专题**全部课程**才可能满足证书条件（本次已达成：`certificateEnabled=true`、`certificatePrinted=true`） |

---

## 8. 归档与迁移说明

本项目已完成开发并归档。迁移目录时注意：

| 项 | 说明 |
| --- | --- |
| 代码本体 | 完整保存在 GitHub `git@github.com:shao-xy/enetedu-aigc-autostudy.git`，任何时候可 `git clone` 恢复 |
| `config.json` | **不在仓库里**（gitignore），跟随本地目录移动。里面是真实 token |
| TRAE 对话历史 | 与路径无关，迁移后仍可访问 |
| TRAE 项目记忆 | 目录名由**路径 + 路径哈希**派生，迁移后会生成新目录名，旧记忆不再自动关联 |
| 新对话恢复方式 | 读本文件 + 技术档案 + `git log`，即可完全恢复上下文 |

---

## 9. 延伸阅读

| 文档 | 内容 |
| --- | --- |
| [`aigc-enetedu-autostudy.md`](aigc-enetedu-autostudy.md) | 完整技术档案：接口清单、字段语义、认证矩阵、实测证据、完成判定规则、反模式清单、错误码 |
| [`../scripts/README.md`](../scripts/README.md) | 使用手册：配置项、命令、协议摘要 |

---

## 附：一句话给 AI 智能体

> 这是 `aigc.enetedu.com` 学习进度上报脚本，已完成并验证。
> 协议要点：**`totalDuration` 报增量不是总长；单笔位置推进量必须等于观看增量，否则整笔静默丢弃；
> 完成判定看累计观看时长而非播放位置；落库延迟 30s，验证写操作后必须等。**
> 改代码前先读本文件 §3 与技术档案 §7，实现契约以 §7 为准。
