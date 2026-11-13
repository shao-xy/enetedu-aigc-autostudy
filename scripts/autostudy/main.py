"""自动刷课入口。

用法：
    python main.py            # 刷配置里指定的那门课
    python main.py --status   # 只看当前各门课的学习状态
    python main.py --list     # 列出专题下所有课程
    python main.py --all      # 刷专题下所有未完成课程
    python main.py --topics   # 列出当前账号可访问的所有专题

认证只需 config.json 里的 access_token。专题（topic_id）与课程（course_id）
都可以留空，脚本会通过 my-topics / topic-detail 接口自动推导。
"""

from __future__ import annotations

import argparse
import sys

from client import Client, load_config
from study import StudyRunner


def cmd_status(client: Client, topic_id: str) -> None:
    detail = client.topic_detail(topic_id)
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


def cmd_topics(client: Client) -> None:
    topics = client.my_topics()
    if not topics:
        print("当前账号没有可访问的专题。")
        return
    print(f"当前账号可访问 {len(topics)} 个专题：\n")
    for t in topics:
        print(f"  topicId={t.get('topicId')}  {t.get('topicName')}")
        print(f"    课程 {t.get('completedCourseCount')}/{t.get('courseCount')} 门已完成"
              f"，总进度 {t.get('learningProgress')}%"
              f"，证书可打印={t.get('certificatePrintable')}")


def resolve_topic_id(client: Client, config: dict, override: str | None) -> str:
    """确定要操作的专题 id。

    优先用命令行 --topic；否则用配置里的 topic_id（但要确认本账号确实有权限访问，
    否则说明是从别人那里拿的示例配置）；再否则从 my-topics 自动推导。
    """
    topics = client.my_topics()
    if not topics:
        raise SystemExit("当前账号没有可访问的专题，请确认登录的是参训教师账号。")

    if override:
        return str(override)

    available = {str(t.get("topicId")) for t in topics}
    configured = str(config.get("topic_id") or "")
    if configured and configured in available:
        return configured
    if configured:
        print(f"提示：配置里的 topic_id={configured} 本账号无权访问，"
              f"已自动改用实际可访问的专题。")

    if len(topics) == 1:
        only = topics[0]
        print(f"专题 {only.get('topicName')}（{only.get('topicId')}）")
        return str(only.get("topicId"))

    print("当前账号有多个专题，请用 --topic <topicId> 指定其一：")
    for t in topics:
        print(f"  {t.get('topicId')}  {t.get('topicName')}  "
              f"({t.get('completedCourseCount')}/{t.get('courseCount')} 门已完成)")
    raise SystemExit("用 --topics 可查看专题列表。")


def main() -> int:
    parser = argparse.ArgumentParser(description="aigc.enetedu.com 自动刷课")
    parser.add_argument("--config", default=None, help="配置文件路径")
    parser.add_argument("--status", action="store_true", help="只显示学习状态")
    parser.add_argument("--list", action="store_true", help="列出专题下所有课程")
    parser.add_argument("--all", action="store_true", help="刷全部未完成课程")
    parser.add_argument("--topics", action="store_true", help="列出账号可访问的所有专题")
    parser.add_argument("--topic", default=None, help="指定专题 topicId（默认自动推导）")
    parser.add_argument("--course", default=None, help="指定要刷的 courseId")
    parser.add_argument("--dry-run", action="store_true", help="只打印上报体，不真正提交")
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

    if args.topics:
        cmd_topics(client)
        return 0

    topic_id = resolve_topic_id(client, config, args.topic)

    if args.status:
        cmd_status(client, topic_id)
        return 0
    if args.list:
        cmd_list(client, topic_id)
        return 0

    runner = StudyRunner(client, config)
    if args.all:
        only = None
    else:
        only = args.course or (str(config.get("course_id") or "") or None)
        if only:
            # 配置里的 course_id 可能来自他人的专题，本账号未必有这门课
            valid = {str(c.get("courseId")) for c in client.topic_courses(topic_id)}
            if only not in valid:
                print(f"提示：课程 {only} 不在本专题的课程清单里"
                      f"（可能是配置里的示例值），改为刷所有未完成课程。")
                only = None
    if only is None and not args.all:
        print("提示：未指定课程，改为刷该专题下所有未完成课程。")
    runner.study_topic(topic_id, only=only)
    return 0


if __name__ == "__main__":
    sys.exit(main())
