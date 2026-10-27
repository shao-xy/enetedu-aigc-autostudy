"""aigc.enetedu.com 学习平台接口封装。

接口逆向自浏览器 HAR（认证走 Authorization: Bearer <futureTeachersToken>）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import requests

CONFIG_PATH = Path(__file__).with_name("config.json")


def load_config(path: Path | str = CONFIG_PATH) -> dict[str, Any]:
    with open(path, encoding="utf-8") as fp:
        return json.load(fp)


class Client:
    """平台接口客户端。"""

    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.base_url = config["base_url"].rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({
            "accept": "*/*",
            "authorization": f"Bearer {config['access_token']}",
            "content-type": "application/json",
            "origin": self.base_url,
            "referer": f"{self.base_url}/courses/watch/"
                      f"?courseId={config['course_id']}&topicId={config['topic_id']}",
            "user-agent": config["user_agent"],
            "tenant-id": str(config["tenant_id"]),
        })
        self.session.cookies.update({
            "tenantId": str(config["cookie_tenant_id"]),
            "futureTeachersToken": config["access_token"],
        })

    # ---------- 基础请求 ----------

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        resp = self.session.request(method, url, timeout=30, **kwargs)
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 200:
            raise RuntimeError(f"{method} {path} 失败: code={data.get('code')} msg={data.get('msg')}")
        return data.get("data")

    def get(self, path: str, **kwargs: Any) -> dict[str, Any]:
        return self._request("GET", path, **kwargs)

    def post(self, path: str, **kwargs: Any) -> dict[str, Any]:
        return self._request("POST", path, **kwargs)

    # ---------- 业务接口 ----------

    def query_user_info(self) -> dict[str, Any]:
        """当前登录用户信息。"""
        return self.get("/admin-api/system/auth/queryUserInfo")

    def topic_detail(self, topic_id: str) -> dict[str, Any]:
        """专题（研修班）详情，含课程清单与完成数。"""
        return self.get("/app-api/home/api/future-teacher/course-table/topic-detail",
                        params={"topicId": topic_id})

    def topic_courses(self, topic_id: str) -> list[dict[str, Any]]:
        """专题下全部课程及学习状态。"""
        return self.topic_detail(topic_id).get("courses") or []

    def course_detail(self, course_id: str) -> dict[str, Any]:
        """单个课程信息。"""
        return self.get("/admin-api/media/online-course/getSimpleCourseInfo",
                        params={"courseId": course_id})

    def lessons(self, course_id: str) -> list[dict[str, Any]]:
        """课程下的视频（学习单元）列表。"""
        rows = self.get("/admin-api/course/learning-detail/treeList",
                        params={"courseId": course_id, "type": 1}) or []
        return rows

    def media_duration_ms(self, media_id: str) -> int | None:
        """视频真实总时长（毫秒）。"""
        try:
            data = self.get("/admin-api/media/meet/get", params={"mediaId": media_id}) or {}
        except RuntimeError:
            return None
        audio = ((data.get("transcription") or {}).get("Transcription") or {}).get("AudioInfo") or {}
        duration = audio.get("Duration")
        return int(duration) if duration else None

    def report_progress(self, payload: dict[str, Any]) -> bool:
        """上报学习进度。

        字段语义（已实测）：
          videoId / fileName  视频标识
          courseId            课程 id
          topicId             专题 id
          duration            当前播放位置（秒级 mm:ss）
          maxPlayedTime       历史最远播放位置
          totalDuration       本次心跳内新增的观看秒数（服务端累加成累计观看时长）
        """
        self.post("/admin-api/course/learning-detail/create", json=payload)
        return True
