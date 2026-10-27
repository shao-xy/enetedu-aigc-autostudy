"""自动刷课核心。

平台学习进度协议（逆向自 HAR + 服务端行为实测）：

  POST /admin-api/course/learning-detail/create
  {
    "videoId": "...", "courseId": "...", "chapterId": "", "fileName": "...",
    "pid": "", "duration": "mm:ss", "totalDuration": "mm:ss",
    "maxPlayedTime": "mm:ss", "topicId": "..."
  }

  duration        当前播放位置
  maxPlayedTime   历史最远播放位置（服务端取单调最大值）
  totalDuration   本次心跳新增的观看秒数（服务端累加成累计观看时长）

实测结论：
  * 课程「已完成」的判定依据是累计观看时长是否达到课程要求学时
    （topic-detail 里的 durationTime，单位小时），而不是播放位置。
  * 服务端不校验墙钟时间，但要求单次上报的「位置推进量」与「观看增量」
    保持一致（position 前进多少，增量就是多少），否则该笔会被丢弃。
  * 服务端落库是异步的（约 30 秒延迟），读接口要留出延迟再校验。
"""

from __future__ import annotations

import time
from typing import Any

from client import Client


def to_mm_ss(seconds: float) -> str:
    """秒 -> mm:ss。"""
    total = int(round(seconds))
    return f"{total // 60}:{total % 60:02d}"


def to_seconds(text: str | None) -> int:
    """mm:ss / ss -> 秒。"""
    if not text:
        return 0
    parts = str(text).split(":")
    try:
        if len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])
        return int(parts[0])
    except ValueError:
        return 0


def to_hours(text: str | None) -> float:
    """要求学时（字符串小时数）-> 秒。"""
    try:
        return float(text or 0) * 3600
    except ValueError:
        return 0.0


class StudyRunner:
    """按课程列表逐个上报学习进度。"""

    def __init__(self, client: Client, config: dict[str, Any], verbose: bool = True):
        self.client = client
        self.config = config
        self.verbose = verbose
        self.speed = max(1, int(config.get("speed", 1)))
        self.interval = max(1, int(config.get("report_interval", 10)))
        self.dry_run = bool(config.get("dry_run", False))
        # 单次心跳的观看增量上限（秒）。服务端对位置跳变有容忍度，
        # 但增量过大时容易整笔被丢，控制在 100 秒左右最稳。
        self.chunk = min(int(config.get("chunk_seconds", 100)), self.interval * self.speed)
        # 上报后等服务端落库再读状态。实测落库延迟约 27~30 秒，
        # 取 35 秒留余量，保证读到的状态可靠。
        self.settle_wait = max(0, int(config.get("settle_wait", 35)))

    def log(self, message: str) -> None:
        if self.verbose:
            print(message, flush=True)

    # ---------- 单个视频 ----------

    def study_lesson(self, lesson: dict[str, Any], topic_id: str,
                      required_seconds: float) -> None:
        """刷一个视频，直到累计观看时长达到要求。"""
        video_id = str(lesson.get("videoId") or "")
        file_name = str(lesson.get("fileName") or video_id)
        course_id = str(lesson.get("courseId"))

        total_ms = self.client.media_duration_ms(video_id)
        media_seconds = total_ms / 1000 if total_ms else 0

        position = max(to_seconds(lesson.get("duration")),
                       to_seconds(lesson.get("maxPlayedTime")))
        watched = to_seconds(lesson.get("totalDuration"))
        required = max(required_seconds, media_seconds)

        self.log(f"  视频 {video_id} 真实时长 {to_mm_ss(media_seconds)}，"
                 f"已看 {to_mm_ss(watched)}，需要 {to_mm_ss(required)}")

        pending = int(required - watched)
        total_steps = (pending + self.chunk - 1) // self.chunk if pending > 0 else 0
        if total_steps:
            self.log(f"  需上报 {total_steps} 笔，每笔 {self.chunk} 秒增量，"
                     f"预计约 {total_steps * self.interval // self.speed} 秒完成")

        step_no = 0
        while watched < required:
            increment = min(self.chunk, int(required - watched))
            if media_seconds:
                increment = min(increment, max(0, int(media_seconds - position)))
            if increment <= 0:
                break
            position += increment
            watched += increment
            self._report(lesson, video_id, file_name, course_id, topic_id,
                         position, position, increment)
            step_no += 1
            self.log(f"    [{step_no}/{total_steps}] 已上报 position={to_mm_ss(position)} "
                     f"累计={to_mm_ss(watched)} 还差 {to_mm_ss(required - watched)}")

    def _report(self, lesson, video_id, file_name, course_id, topic_id,
                position, max_played, increment) -> None:
        payload = {
            "videoId": video_id,
            "courseId": course_id,
            "chapterId": lesson.get("chapterId") or "",
            "fileName": file_name,
            "pid": lesson.get("pid") or "",
            "duration": to_mm_ss(position),
            "totalDuration": to_mm_ss(increment),
            "maxPlayedTime": to_mm_ss(max_played),
            "topicId": topic_id,
        }
        if self.dry_run:
            self.log(f"    [dry-run] {payload}")
            return
        self.client.report_progress(payload)

    # ---------- 单门课程 ----------

    def study_course(self, course_id: str, topic_id: str,
                     required_seconds: float) -> None:
        """刷完一门课程的所有视频。"""
        lessons = self.client.lessons(course_id)
        if not lessons:
            self.log(f"  课程 {course_id} 没有可学习的视频")
            return
        self.log(f"  共 {len(lessons)} 个视频，需要累计观看 {to_mm_ss(required_seconds)}")
        for lesson in lessons:
            self.study_lesson(lesson, topic_id, required_seconds)

    # ---------- 专题全部课程 ----------

    def study_topic(self, topic_id: str, only: str | None = None) -> None:
        """刷专题下全部课程；only 指定 courseId 时只刷该门。"""
        detail = self.client.topic_detail(topic_id)
        courses = self.client.topic_courses(topic_id)
        self.log(f"专题 {topic_id}「{detail.get('topicName')}」共 {len(courses)} 门课程，"
                 f"已完成 {detail.get('completedCourseCount')} 门")

        for course in courses:
            cid = str(course.get("courseId"))
            name = course.get("courseName", "")
            if only and cid != only:
                continue
            if course.get("learningStatus") == 2:
                self.log(f"[跳过] {name} 已完成")
                continue

            required = to_hours(course.get("durationTime"))
            self.log(f"[刷课] {name} ({cid}) 要求 {course.get('durationTime')} 小时，"
                     f"当前 {course.get('learningStatusName')}")
            self.study_course(cid, topic_id, required)

            # 服务端落库是异步的（实测约 27~30 秒），这里留出余量再读状态。
            # 等待期间打印进度提示，避免看起来像卡死。
            if not self.dry_run:
                self.log(f"  进度已上报。服务端异步落库需约 30 秒，"
                         f"等待 {self.settle_wait} 秒后校验状态（不是卡死）...")
                self._wait_with_progress(self.settle_wait)
            after = [c for c in self.client.topic_courses(topic_id)
                     if str(c.get("courseId")) == cid]
            state = after[0].get("learningStatusName") if after else "?"
            done = after[0].get("learnDuration") if after else "?"
            self.log(f"[结果] {name} -> {state}（已学 {done} 小时）")
            # 落库慢于等待时间时会读到旧状态，如实提示而不是误报失败
            if state == "学习中":
                self.log("  提示：服务端落库有延迟，当前仍显示「学习中」。"
                         "稍后用 --status 复查即可。")

    def _wait_with_progress(self, seconds: int) -> None:
        """等待落库，期间输出倒计时提示，避免看起来卡死。"""
        step = 5
        remaining = seconds
        while remaining > 0:
            chunk = min(step, remaining)
            time.sleep(chunk)
            remaining -= chunk
            if remaining > 0:
                self.log(f"  ... 等待落库中，剩余 {remaining} 秒")
