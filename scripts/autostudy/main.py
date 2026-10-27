"""自动刷课入口。

用法：
    python main.py            # 刷配置里指定的那门课
    python main.py --status   # 只看当前各门课的学习状态
    python main.py --list     # 列出专题下所有课程
    python main.py --all      # 刷专题下所有未完成课程
"""

from __future__ import annotations

import argparse
import sys

from client import Client, load_config
from study import StudyRunner


def cmd_status(client: Client, topic_id: str) -> None:
    detail = client.topic_detail(topic_id)
    print(f"专题 {detail.get('topicName')}（{topic_id}）")
    print(f"课程数 {detail.get('totalCourseCount')}，已完成 {detail.get('completedCourseCount')}\n")
    for course in client.topic_courses(topic_id):
        print(f"  [{course.get('learningStatusName'):>4}] "
              f"进度 {course.get('learningProgress')}% "
              f"已学 {course.get('learnDuration')}h/{course.get('durationTime')}h "
              f"{course.get('courseName')}")


def cmd_list(client: Client, topic_id: str) -> None:
    for course in client.topic_courses(topic_id):
        print(f"  {course.get('courseId')}  "
              f"{course.get('learningStatusName'):>4}  "
              f"{course.get('courseName')}")


def main() -> int:
    parser = argparse.ArgumentParser(description="aigc.enetedu.com 自动刷课")
    parser.add_argument("--config", default=None, help="配置文件路径")
    parser.add_argument("--status", action="store_true", help="只显示学习状态")
    parser.add_argument("--list", action="store_true", help="列出专题下所有课程")
    parser.add_argument("--all", action="store_true", help="刷全部未完成课程")
    parser.add_argument("--course", default=None, help="指定要刷的 courseId")
    parser.add_argument("--dry-run", action="store_true", help="只打印上报内容，不真正提交")
    parser.add_argument("--speed", type=int, default=None, help="倍速")
    args = parser.parse_args()

    config = load_config(args.config) if args.config else load_config()
    if args.dry_run:
        config["dry_run"] = True
    if args.speed:
        config["speed"] = args.speed

    client = Client(config)

    try:
        info = client.query_user_info()
        print(f"登录用户：{info.get('nickname')}（{info.get('mobile')}）")
    except Exception as exc:  # noqa: BLE001 - 认证失效时给出可读提示
        print(f"认证失败：{exc}")
        print("请在浏览器登录后，把 config.json 里的 access_token 换成最新的 "
              "futureTeachersToken（Cookie 中同名值）。")
        return 1

    topic_id = str(config["topic_id"])

    if args.status:
        cmd_status(client, topic_id)
        return 0
    if args.list:
        cmd_list(client, topic_id)
        return 0

    runner = StudyRunner(client, config)
    only = args.course or (None if args.all else str(config["course_id"]))
    runner.study_topic(topic_id, only=only)
    return 0


if __name__ == "__main__":
    sys.exit(main())
