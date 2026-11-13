# aigc.enetedu.com 自动刷课 — 完整技术档案

> 面向两类读者：
> - **人类开发者**：第 1、2、4、5、8 节是上手与维护所需。
> - **大模型智能体**：第 2、3、6、7 节是可直接执行的精确契约（接口、字段语义、约束、判定规则），
>   第 7 节含「反模式清单」，直接决定实现是否正确。
>
> 文档中所有结论均来自**实际抓包 + 服务端行为实测**，非推测。实测时间：2026-10-27。

---

## 1. 任务背景与结论摘要

平台：`https://aigc.enetedu.com` —「2026年人工智能赋能高等教育系列师资培训」平台。

用户账号下有 1 个研修专题（专题 = 研修班），该专题包含 **16 门课程**。
课程清单由教师在后台为每个专题**手动勾选**决定，因此数量与内容**因账号、因专题而异**，
本项目的脚本不硬编码任何课程 id，每次运行都从接口动态读取（详见 §3.1.1）。
目标：自动上报学习进度，使课程被服务端判定为「已完成」，从而推进专题完成数与证书发放条件。

**核心结论（一句话）**：

> 只需向 `POST /admin-api/course/learning-detail/create` 周期上报
> `{duration, maxPlayedTime, totalDuration}` 三个时长字段，
> 其中 **`totalDuration` 是「本次新增观看秒数」而非视频总长**，
> 且**服务端要求「位置推进量 == 观看增量」**，否则整笔丢弃。

**已验证成果**：目标课「AI赋能项目式教学创新设计：从理论到实践」
（视频真实时长 72:05，要求 1.2 学时）实跑后，服务端状态由「学习中」→「已完成」，
`learningProgress` = 100%，专题已完成数 1 → 2。

**使用门槛**：使用者**只需复制一个 `futureTeachersToken`**。
专题 id 由 `my-topics` 接口自动推导，课程清单由 `topic-detail` 接口动态读取（详见 §3.1.2）。

---

## 2. 认证（最小依赖集已实测）

### 2.1 唯一必需凭据

| 项 | 值 | 必需性 |
| --- | --- | --- |
| `access_token` | 浏览器 Cookie 中 `futureTeachersToken` 的值 | **唯一必需** |

只需放进请求头：

```
Authorization: Bearer <access_token>
```

### 2.2 实测矩阵（`GET /admin-api/system/auth/queryUserInfo`）

| # | 请求配置 | code | 结论 |
| --- | --- | --- | --- |
| 1 | 无任何认证 | 401 `账号未登录` | 失败 |
| 2 | **仅** `Authorization` 头 | **200** | **成功** |
| 3 | 仅 Cookie `futureTeachersToken`（无 Authorization） | 401 | 失败 |
| 4 | Authorization + 同名 Cookie | 200 | 成功 |
| 5 | Authorization + Cookie + `tenantId=100` | 200 | 成功 |
| 6 | Authorization + Cookie + `tenantId=1` | 200 | 成功（Cookie 值无关） |
| 7 | Authorization + Cookie + `tenant-id` 头 | 200 | 成功 |
| 8 | 仅 Cookie + `tenant-id` 头（**无** Authorization） | 401 | 失败 |
| 9 | Authorization 携带错误 token | 401 `访问令牌不存在` | 失败 |
| 10 | Authorization + Cookie + `visit-tenant-id` 头 | 200 | 成功 |

写入接口 `POST /admin-api/course/learning-detail/create` 结论完全一致：
仅 `Authorization` 即可成功；无 Authorization 必然 401。

### 2.3 结论

- **只有 `futureTeachersToken` 需要复制**，且只需一处。
- Cookie 里的同名值、`tenant-id` 头、`visit-tenant-id` 头、User-Agent **均非必需**。
  脚本仍会带上（更接近真实浏览器，降低被风控识别的概率），但省略也能工作。
- 其它 Cookie（`p_h5_u`、`selectedCC`、`acw_tc`）是 CDN/播放器埋点用的，**完全无关**。
- Token 过期表现：HTTP 200 + `code=401` + `msg=访问令牌不存在`（**不是** HTTP 401）。
  脚本据此判定并给出提示。

### 2.4 获取方式

浏览器登录平台后 → DevTools → Application → Cookies → 复制 `futureTeachersToken` 的值。
注意：Cookie 值若带引号需去掉。平台登录本身走短信动态验证码，脚本不涉及登录流程。

### 2.5 前端认证实现（逆向自 chunk `22ox8jx94zwvs.js`）

前端 `createBrowserAuthSessionStore` 的默认键名：

| 用途 | 键名 |
| --- | --- |
| access token Cookie | `futureTeachersToken`（教师端）/ `eneteduToken`（主站端） |
| tenant id Cookie | `futureTeachersTenantId` / `tenantId` |
| refresh token | `futureTeachers.auth.refreshToken`（localStorage） |
| 过期时间 | `futureTeachers.auth.expiresTime`（localStorage） |

Token 通过 `Authorization: Bearer` 头传递；`tenant-id` 固定为 `"1"`，
另有 `visit-tenant-id`（取自 `getVisitTenantId() || getTenantId()`）表示当前租户。

---

## 3. 接口清单（全部实测可用）

基础前缀 `https://aigc.enetedu.com`。两个 API 组，前缀不同：

- `/admin-api/...` —— 平台主体接口
- `/app-api/...` —— 研修专题/证书相关接口

### 3.1 必需接口

| 方法 | 路径 | 用途 | 关键返回 |
| --- | --- | --- | --- |
| GET | `/admin-api/system/auth/queryUserInfo` | 校验登录态 | `data.nickname` / `data.mobile` |
| GET | `/app-api/home/api/future-teacher/course-table/my-topics` | **本账号的专题列表**（自动推导 topicId） | `data.list[]`（见 §3.1.2）、`data.total` |
| GET | `/app-api/home/api/future-teacher/course-table/topic-detail` | **专题详情 + 课程清单** | `data.courses[]`、`data.completedCourseCount`、`data.totalCourseCount` |
| GET | `/admin-api/course/learning-detail/treeList` | 课程下视频列表 + 当前进度 | `data[]`（见 §4.3） |
| GET | `/admin-api/media/meet/get` | 视频真实总时长 | `data.transcription.Transcription.AudioInfo.Duration`（**毫秒**） |
| POST | `/admin-api/course/learning-detail/create` | **上报学习进度** | `data=true` |

### 3.1.1 课程清单的正确来源（易错点）

**`topic-detail` 返回的 `courses[]` 才是「本专题需要学的课程」**，
它由教师/管理员在后台为该专题**手动勾选**构成，因此：

- 课程数量**因专题而异**，不是固定值；
- 同一课程库，不同教师账号看到的清单可能不同；
- 本次实测账号的专题 `180200` 有 16 门（3 门「未来教师」+ 10 门「必修」+ 3 门「实验教学」），
  换账号/换专题数量会变。

脚本每次运行都**动态调用 `topic-detail`**，不做任何硬编码，
因此天然适配不同账号与专题。

> ⚠️ **不要用 `getVideoCourseListByTopic` 当课程清单**。
> 它返回的是另一套口径（按学科归类的全站课程），
> 实测在专题 `180200` 下只给出 **10 门**，恰好等于 `courses[]` 里 `selectionType=1` 的
> 「必修」子集 —— **漏掉了 6 门**。且其记录里 `id` 与 `isLearning` 两个字段值相差 1
> （如 `2110997995586719744` vs `...745`），用于 `treeList` 时必须取 `isLearning`。

`selectionType` 取值与 `selectionTypeName` 的对应关系（实测）：

| selectionType | selectionTypeName | 本专题数量 |
| --- | --- | --- |
| 1 | 必修 | 10 |
| 2 | 未来教师 | 3 |
| 2 | 实验教学 | 3 |

> ⚠️ `selectionType` 数值**不唯一**：`2` 同时对应「未来教师」和「实验教学」，
> 需以 `selectionTypeName` 为准。

### 3.1.2 专题 id 可自动推导（只需一个 token）

`my-topics` 接口**仅凭 `access_token` 即可调用**，无需预先知道任何 id，
返回当前账号能访问的全部专题：

```json
{
  "data": {
    "list": [{
      "topicId": 180200,
      "topicName": "理工科专项",
      "courseCount": 16,
      "completedCourseCount": 16,
      "learningProgress": 100.0,
      "certificateEnabled": true,
      "certificatePrintable": false,
      "certificatePrinted": true,
      "registrationStartTime": "2026-10-01 18:29:18",
      "registrationEndTime": "2026-11-30 23:59:59",
      "trainingStartTime": "2026-10-17 18:29:35",
      "trainingEndTime": "2026-11-30 23:59:59",
      "canRegister": true,
      "canStartLearning": true
    }],
    "total": 1
  }
}
```

因此**换人使用时只需填 `access_token` 一个值**：

1. 专题：`my-topics` → 只有一个则自动选中；多个则要求 `--topic` 指定。
2. 课程：`topic-detail` 的 `courses[]` 动态读取，即本账号被勾选的清单。

配置里若残留他人账号的 `topic_id` / `course_id`，脚本会校验权限并自动降级：

- `topic_id` 不在本账号 `my-topics` 列表里 → 提示并改用实际可访问的专题
- `course_id` 不在该专题的 `courses[]` 里 → 提示并改为刷所有未完成课程

### 3.2 辅助接口

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | `/admin-api/media/online-course/getSimpleCourseInfo` | 单门课程信息（`duration` 学时等） |
| GET | `/admin-api/media/online-course/getUserLearingCoursList` | 我的学习课程 |
| GET | `/admin-api/media/online-course/getVideoCourseListByTopic` | ⚠️ 非课程清单，见 §3.1.1 |

### 3.3 无关接口（勿混淆）

- `aliyuncs.com/...*.ts`、`*.m3u8` —— CDN 视频分片，**不需要下载**。
- `videocloud.cn-hangzhou.log.aliyuncs.com/logstores/newplayer/track` —— 播放器埋点日志，**完全无关**。
- `/admin-api/media/admin/getMediaTranscodeInfo` —— 返回加密的 `playUrl`，脚本不需要（不播视频）。

---

## 4. 进度上报协议（核心）

### 4.1 请求

```
POST /admin-api/course/learning-detail/create
Content-Type: application/json
Authorization: Bearer <access_token>
```

```json
{
  "videoId":       "15072001",
  "courseId":      "2110260665179574273",
  "chapterId":     "",
  "fileName":      "15072001",
  "pid":           "",
  "duration":      "71:33",
  "totalDuration": "0:13",
  "maxPlayedTime": "71:33",
  "topicId":       "180200"
}
```

响应：`{"code":200,"data":true,"msg":"处理成功"}`

### 4.2 字段语义（实测确定，最易误解处）

| 字段 | 语义 | 注意 |
| --- | --- | --- |
| `duration` | 当前播放位置 | `mm:ss` |
| `maxPlayedTime` | 历史最远播放位置 | 服务端取**单调最大值**，回退无效 |
| `totalDuration` | **本次心跳新增的观看秒数** | ⚠️ **不是**视频总长！服务端累加成累计观看时长 |
| `videoId` / `fileName` | 视频标识 | 两者同值（如 `"15072001"`） |
| `chapterId` / `pid` | 章节/父节点 id | 本平台为空串 |
| `courseId` / `topicId` | 课程 / 专题 id | 字符串 |

原始 HAR 里 `totalDuration` 出现 `"0:10"`、`"0:07"`、`"0:04"` 这类小值，
而视频长 72 分钟 —— 这正是它表示**增量**而非总长的直接证据。

### 4.3 响应侧（`treeList`）字段语义

| 字段 | 语义 |
| --- | --- |
| `duration` | 服务端记录的当前播放位置 |
| `maxPlayedTime` | 历史最远播放位置（单调） |
| `totalDuration` | **累计观看时长**（服务端把各笔增量累加的结果） |
| `progress` | `0`/`1`，`1` = 该视频已完成 |
| `progressEventDuration` | 最近一次落库的增量 |
| `progressEventVersion` | 落库版本号，**每次成功落库 +1** |
| `status` | `0`=未开始 `1`=学习中 `2`=已完成 |

### 4.4 服务端行为实测结论

| # | 结论 | 证据 |
| --- | --- | --- |
| 1 | **不校验墙钟时间** | 墙钟 45 秒内上报位置 +600 秒，服务端照单全收（`duration` 变 10:00） |
| 2 | **要求「位置推进量 == 观看增量」** | 位置跳 +200s 而增量报 20s，该笔被丢弃；位置与增量同时 +200s 则接受 |
| 3 | **`maxPlayedTime` 单调** | 上报更小的值不会回退服务端记录 |
| 4 | **落库异步，延迟约 27~30 秒** | 上报后立即读 `treeList` 读到旧值；实测 t+27s 才看到新值 |
| 5 | **完成判定看累计观看时长** | 见 §5 |

> ⚠️ **第 4 点是本项目最大的坑**。早期实验因读得太快而误判为「服务端拒绝」，
> 差点得出错误协议。**任何验证写操作后，必须 sleep ≥ 30 秒再读状态。**
>
> 实测精确值：上报后 **t+27s** 才在 `treeList` 中可见新值。
> 脚本默认 `settle_wait=35`（30s + 余量）。曾尝试用 15s，实测偏紧，不够稳妥，已回退为 35s。
> 等待期间脚本每 5 秒打印一次倒计时，避免看起来像卡死。

---

## 5. 完成判定规则

### 5.1 判定依据

**课程「已完成」= 累计观看时长 ≥ 课程要求学时**，与播放位置无关。

- 课程要求学时：`topic-detail` → `courses[].durationTime`（**单位：小时**，字符串如 `"1.2"`）
- 累计观看时长：`treeList` → `totalDuration`（秒）

### 5.2 反证实验

| 场景 | 结果 |
| --- | --- |
| 沙盒课「人工智能赋能教育变革」：位置推到 131:40，累计 1:57:30，要求 1.0h | → **已完成**，`progress=1`，`learningProgress=100%` |
| 同课早期：位置 30:00，累计 14:30，要求 1.0h | 学习中 |
| 目标课：位置 71:33，累计 72:05，要求 1.2h（=72 min） | → **已完成** |

### 5.3 相关字段

`topic-detail` → `courses[]` 每门课：

| 字段 | 含义 |
| --- | --- |
| `learningStatus` | `0`=未学习 `1`=学习中 `2`=已完成 |
| `learningStatusName` | 上者的中文名 |
| `learningProgress` | 百分比（`100.0` = 完成） |
| `durationTime` | 要求学时（小时） |
| `learnDuration` | 已学学时（小时） |
| `duration` | 课程标称学时（小时） |

专题级：`completedCourseCount`、`totalCourseCount`。

---

## 6. 视频真实时长

平台登记的 `duration` / `totalDuration` 字段**不可靠**（目标课登记 17:31，真实 72:05）。

可靠来源：

```
GET /admin-api/media/meet/get?mediaId=<videoId>
→ data.transcription.Transcription.AudioInfo.Duration   # 毫秒
```

实测对照：

| 课程 | 登记时长 | 真实时长 | 要求学时 |
| --- | --- | --- | --- |
| AI赋能项目式教学创新设计 | 17:31 | **72:05** | 1.2 h |
| 人工智能赋能教育变革 | — | 59:42 | 1.0 h |
| 从虚拟仿真实验到多智能体协作… | — | 72:35 | 1.2 h |

备选：`getMediaTranscodeInfo` 返回加密 `playUrl`，需 SM2 解密 + OSS 签名，**脚本刻意绕开**。

---

## 7. 实现契约（智能体直接照此实现）

### 7.1 算法

```
for each course in topic.courses where learningStatus != 2:
    required_seconds = float(course.durationTime) * 3600
    for each lesson in treeList(courseId, type=1):
        media_seconds = meet.get(mediaId).transcription...AudioInfo.Duration / 1000
        target = max(required_seconds, media_seconds)      # 取两者较大，覆盖两种判定口径
        position = max(lesson.duration, lesson.maxPlayedTime)   # 秒
        watched  = lesson.totalDuration                          # 秒，服务端已累计值
        while watched < target:
            increment = min(CHUNK, target - watched)
            if media_seconds:
                increment = min(increment, media_seconds - position)
            if increment <= 0: break
            position += increment
            watched  += increment
            POST create {
              duration:      mm_ss(position),
              maxPlayedTime: mm_ss(position),
              totalDuration: mm_ss(increment),     # ← 增量，不是累计！
              videoId, fileName, courseId, chapterId, pid, topicId
            }
    sleep(SETTLE_WAIT)     # 等服务端异步落库，再读状态校验（实测需 >= 30s）
```

### 7.1.1 输出提示约定

落库等待期间**必须**周期性输出进度，否则使用者会误判为卡死：

```
  进度已上报。服务端异步落库需约 30 秒，等待 35 秒后校验状态（不是卡死）...
  ... 等待落库中，剩余 30 秒
  ... 等待落库中，剩余 25 秒
  ...
[结果] <课程名> -> 已完成（已学 0.8 小时）
```

### 7.2 硬性约束

| 约束 | 违反后果 |
| --- | --- |
| `totalDuration` 必须是**增量** | 报累计值 → 服务端累加后严重虚高；报总长 → 进度瞬间冲顶，可能触发异常 |
| 位置推进量 == 观看增量 | 不一致 → **该笔整条被丢弃**（HTTP 仍返回 200 + `处理成功`，无任何报错） |
| `maxPlayedTime` 单调不减 | 回退无效，且可能使该笔被判定异常 |
| 单次增量不宜过大 | 实测 >100s/笔 时丢弃率上升；建议 ≤100s |
| 上报后 sleep ≥30s 再读状态 | 读到旧值，误判失败 |
| 时间格式统一 `mm:ss` | 其它格式解析失败 |

### 7.3 反模式清单（照此实现会失败）

| ✗ 错误做法 | ✓ 正确做法 |
| --- | --- |
| `totalDuration` 填视频总长（72:05） | 填**本次增量**（如 `"1:40"`） |
| 把 `duration` 直接推到片尾就以为完成 | 累计时长须达到 `durationTime` 要求学时 |
| 每笔位置跳 600 秒、增量报 600 秒且无间隔 | 位置与增量一致，但需**有间隔**并分多次上报 |
| 位置跳 200 秒而增量报 20 秒 | 两者必须相等 |
| 上报后立刻读状态判断成功/失败 | sleep ≥30 秒 |
| 依赖 Cookie `futureTeachersToken` 才能认证 | 只需 `Authorization` 头 |
| 依赖 `p_h5_u` / `acw_tc` / `tenantId` | 与鉴权无关 |
| 播放视频或请求 m3u8 来推进进度 | 无需任何视频下载 |

### 7.4 参数取值

| 参数 | 建议值 | 说明 |
| --- | --- | --- |
| `CHUNK`（单次增量） | 100 秒 | 实测稳定 |
| `REPORT_INTERVAL` | 10 秒 | HAR 中心跳间隔 |
| `SPEED` | 10 | 位置与增量同步推进的倍速 |
| `SETTLE_WAIT` | 35 秒 | 落库延迟实测 27~30s，取 30s + 余量。15s 实测偏紧，不够稳妥 |

### 7.5 错误码

| code | msg | 含义 |
| --- | --- | --- |
| 200 | 处理成功 | 成功（注意：写操作即使被丢弃也返回 200） |
| 401 | 账号未登录 | 缺少 `Authorization` 头 |
| 401 | 访问令牌不存在 | token 过期或错误 |
| 1002000010 | 课程未报名 | 课程/专题 id 不匹配 |

---

## 8. 代码结构与运行

### 8.1 目录

```
仓库根
├── .gitignore                # 排除含凭据的 config.json
├── docs/
│   └── aigc-enetedu-autostudy.md
└── scripts/
    ├── README.md             # 快速上手
    └── autostudy/
        ├── client.py         # 接口封装（Client 类）
        ├── study.py          # 刷课核心（StudyRunner）
        ├── main.py           # CLI 入口
        ├── config.example.json
        └── config.json       # 实际配置（未入库）
```

### 8.2 命令

```bash
cd scripts/autostudy
python main.py --topics                # 列出本账号可访问的所有专题
python main.py --status                # 查看全部课程状态
python main.py --list                  # 列出专题下所有课程
python main.py                         # 刷 config.json 指定的课程（未指定则刷全部未完成课程）
python main.py --all                   # 刷全部未完成课程
python main.py --course <courseId>     # 刷指定课程
python main.py --topic <topicId>       # 账号有多个专题时指定其一
python main.py --dry-run               # 只打印上报体，不提交
```

### 8.3 依赖

Python 3.10+ 与 `requests`。未修改全局 Python 环境。
`lxml`（用户已装）本项目实际未用到 —— 平台返回 JSON，无需解析 HTML。

### 8.4 幂等性

- 已完成课程（`learningStatus == 2`）自动跳过。
- 从 `treeList` 读回服务端已累计时长，断点续刷不重复计数。
- 可反复运行，只补齐剩余部分。

---

## 9. 实测记录（可复现）

### 9.1 目标课实跑

```
[刷课] AI赋能项目式教学创新设计：从理论到实践 (2110260665179574273) 要求 1.2 小时，当前 学习中
  共 1 个视频，需要累计观看 72:00
  视频 15072001 真实时长 72:05，已看 28:32，需要 72:05
    已上报 position=29:40 累计=30:12 还差 41:53
    ...（共 26 笔，每笔 100 秒增量）
    已上报 position=71:33 累计=72:05 还差 0:00
[结果] AI赋能项目式教学创新设计：从理论到实践 -> 已完成（已学 1.2 小时）
```

### 9.2 专题状态变化

| 时点 | 已完成数 | 说明 |
| --- | --- | --- |
| 初始 | 1 | 平台原有 1 门已完成 |
| 刷完目标课后 | **2** | 目标课「AI赋能项目式教学创新设计」完成 |
| 后续续跑 | **4** | 又完成「面向未来的课堂变革」「AI时代的案例范式与人才培养范式革新」 |
| 验证提示改动后 | **5** | 再完成「数智时代高校教师核心素养重构与提升路径」 |

目标课详情：`learningStatus=2`、`learningStatusName=已完成`、`learningProgress=100.0`、
`learnDuration=1.2` / `durationTime=1.2`。

第 5 门（「数智时代高校教师核心素养重构与提升路径」，真实时长 49:40，要求 0.8h）的实跑
验证了新增的落库等待提示：

```
  需上报 30 笔，每笔 100 秒增量，预计约 30 秒完成
    [1/30] 已上报 position=1:40 累计=1:40 还差 48:00
    ...
    [30/30] 已上报 position=49:40 累计=49:40 还差 0:00
  进度已上报。服务端异步落库需约 30 秒，等待 35 秒后校验状态（不是卡死）...
  ... 等待落库中，剩余 30 秒
  ... 等待落库中，剩余 25 秒
  ... 等待落库中，剩余 20 秒
  ... 等待落库中，剩余 15 秒
  ... 等待落库中，剩余 10 秒
  ... 等待落库中，剩余 5 秒
[结果] 数智时代高校教师核心素养重构与提升路径 -> 已完成（已学 0.8 小时）
```

### 9.3 幂等性验证

重复运行脚本时，已完成课程被正确跳过：

```
[跳过] 面向未来的课堂变革：北大课堂重构项目的探索与启示 已完成
```

同时已上报部分的累计时长从服务端读回（`treeList.totalDuration`），续跑只补差额。

### 9.4 副作用说明

- 「人工智能赋能教育变革」在沙盒验证中被服务端判为已完成（2.2h/1.0h），
  需在平台上重置才能还原。
- 另有 3 门课程用于排除性实验。实测确认**处于「未学习」状态的课程同样可以直接上报**，
  服务端会建记录并正常累加（§9.2 第 5 门即从「未学习」直接刷到「已完成」）。
  早期曾观察到「未学习」课程上报后 73 秒仍无新值，那是因为该次上报的
  **位置与增量不满足一致性约束**（位置推进 100 秒但增量口径不匹配），
  属于被丢弃而非状态限制。

### 9.5 专题自动推导验证（2026-11-13）

用新 token 实测 `my-topics`，确认**仅凭 token 即可拿到专题列表**：

```
$ python main.py --topics
登录用户：张老师（138****0000）
当前账号可访问 1 个专题：

  topicId=180200  理工科专项
    课程 16/16 门已完成，总进度 100.0%，证书可打印=False
```

把 `config.json` 的 `topic_id` / `course_id` 都清空后：

```
$ python main.py --status
登录用户：张老师（138****0000）
专题 理工科专项（180200）
课程数 16，已完成 16
```

即**只填 `access_token` 即可完整运行**。

配置里填入他人账号的 id 时的降级验证（`topic_id=999999`、`course_id=999999`）：

```
登录用户：张老师（138****0000）
提示：配置里的 topic_id=999999 本账号无权访问，已自动改用实际可访问的专题。
专题 理工科专项（180200）
提示：课程 999999 不在本专题的课程清单里（可能是配置里的示例值），改为刷所有未完成课程。
提示：未指定课程，改为刷该专题下所有未完成课程。
专题 180200「理工科专项」共 16 门课程，已完成 16 门
```

两次降级均给出可读提示且未抛异常。

> 顺带记录：本账号专题已完成 16/16 门，`learningProgress=100%`，
> `certificateEnabled=true`、`certificatePrinted=true`（证书已打印），
> 但 `certificatePrintable=false`（当前不可再次打印）。

---

## 10. 风险与边界

| 项 | 说明 |
| --- | --- |
| 平台风控 | 服务端存在防跳逻辑（位置/增量一致性校验）。当前实测通过，但平台规则可变 |
| 凭据泄露 | `config.json` 已 gitignore；勿把 token 写进代码或提交 |
| 账号风险 | 异常高频上报可能触发人工审核。当前节律与真实播放接近，风险较低 |
| 用途范围 | 仅用于本人账号的学习进度上报，不涉及视频下载、转写抓取或他人账号 |
| 证书条件 | 本专题 `certificateEnabled=true`；需完成该专题**全部课程**（本次实测为 16 门，数量因专题而异）后才可能满足证书条件（未验证） |

### 10.1 仓库对外分享注意事项

仓库不含任何真实凭据（`config.json` 未入库，全部历史提交中亦无 token 与手机号），
但把链接分享给其他参训教师前，仍需注意：

| 注意项 | 说明 |
| --- | --- |
| 使用者只需填一个 token | `config.example.json` 里 `topic_id` / `course_id` 均为空，脚本自动推导（见 §3.1.2）。使用者复制自己的 `futureTeachersToken` 填入 `access_token` 即可 |
| 不要打包发目录 | 分享者本机的 `scripts/autostudy/config.json` 含**真实 token**，压缩包直发等于泄露凭据。只发仓库链接 |
| 仓库可见性 | GitHub 远程仓库当前为 **public**，任何拿到链接的人都能 clone。若不希望公开，需改为 private |
| 使用性质 | 本脚本用于自动上报学习进度，分发给他人是否合规由使用者自行判断平台研修规定 |

---

## 附录 A：主题 id 与课程 id 速查

> ⚠️ **以下清单是本次实测账号在专题 `180200`「理工科专项」下的快照，不是固定值。**
> 课程清单由教师在后台为每个专题**手动勾选**决定（见 §3.1.1），
> 不同账号、不同专题的课程数与内容都不同。
> **脚本不依赖本表**，每次运行都从 `topic-detail` 动态读取。
> 本表仅供人工核对本次实测结果时参考。

专题 `180200`「理工科专项」实测 16 门课：

| courseId | 课程名 | 类型 | 要求学时 | 真实时长 |
| --- | --- | --- | --- | --- |
| 2110260665179574273 | AI赋能项目式教学创新设计：从理论到实践 | 未来教师 | 1.2 | 72:05 |
| 2110263576102047745 | 面向未来的课堂变革：北大课堂重构项目的探索与启示 | 未来教师 | 0.7 | 43:58 |
| 2110262763518562305 | AI时代的案例范式与人才培养范式革新 | 未来教师 | 0.7 | 39:53 |
| 2110997995586719745 | 人工智能赋能教育变革 | 必修 | 1.0 | 59:42 |
| 2110261357059379201 | 数智时代高校教师核心素养重构与提升路径 | 必修 | 0.8 | 49:40 |
| 2110261587771265025 | 未来工程人才能力生成新范式 | 必修 | 0.9 | 53:27 |
| 2110262181080731649 | 从学会知识到学会探索 | 必修 | 0.6 | 36:19 |
| 2110358386561388544 | "AIM"力学大模型 | 必修 | 0.7 | 39:16 |
| 2110261053790228481 | AI赋能人工智能通识课建设 | 必修 | 0.8 | 46:05 |
| 2110359486219816961 | AI赋能教学创新探索与华师实践 | 必修 | 0.8 | 49:25 |
| 2110679826485612544 | AI赋能工科课程的重构 | 必修 | 0.7 | 44:58 |
| 2110360480433442817 | 加快教材数字化变革 | 必修 | 0.8 | 48:09 |
| 2110360023795372033 | 人机协同的攻防课堂 | 必修 | 0.7 | 43:09 |
| 2110374919920553985 | 面向2035：实验教学高质量发展 | 实验教学 | 1.1 | 63:17 |
| 2110376714591932417 | 从工具辅助到浸润赋能 | 实验教学 | 0.7 | 44:38 |
| 2110961849511055361 | 从虚拟仿真实验到多智能体协作 | 实验教学 | 1.2 | 72:35 |

目标课视频：`videoId=15072001`。

另有 2 个专题相关接口可用于换专题：`my-topics`（我的专题列表）、
`topic-detail`（指定专题的课程清单）。换专题只需改 `config.json` 的 `topic_id`。

## 附录 B：接口前缀速查

| 前缀 | 用途 |
| --- | --- |
| `/admin-api` | 平台主体（进度上报、课程信息、视频元数据、用户信息） |
| `/app-api` | 研修专题（专题详情、我的专题、证书） |

`tenant-id` 固定 `"1"`；`visit-tenant-id` 为当前租户（实测 `"100"`）。
