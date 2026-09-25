"""象信 AI 快速开始示例。 / 象信 AI quickstart example.

运行前设置 API 密钥 / Set your API key first::

    export XIANGXIN_API_KEY="sk-xx-..."
    uv run python examples/quickstart.py
"""

from __future__ import annotations

from xiangxin import (
    Choice,
    InsufficientBalanceError,
    Noul,
    RateLimitError,
    Score,
    XiangxinClient,
    XiangxinError,
)

TICKET = "我这个月被重复扣费了两次，客服三天都没回复，请尽快处理！"

QUESTIONS = {
    "is_urgent": Noul(
        instructions="这张工单是否需要当天处理？",
        criteria={"true": "涉及资金损失或服务不可用", "false": "一般咨询或建议"},
    ),
    "department": Choice(
        instructions="应分派到哪个部门？",
        criteria={
            "billing": "扣费、发票、退款",
            "technical": "报错、故障、无法登录",
            "sales": "购买咨询、套餐升级",
        },
    ),
    "frustration": Score(
        instructions="用户的情绪有多激动？",
        criteria=["平静", "不满", "非常愤怒"],
    ),
}


def main() -> None:
    try:
        client = XiangxinClient()
    except XiangxinError as exc:
        raise SystemExit(f"客户端初始化失败：{exc}") from exc

    with client:
        print("可用模型：", ", ".join(m.name for m in client.models.list().models))

        try:
            resp = client.system_one(state=TICKET, questions=QUESTIONS)
        except InsufficientBalanceError:
            raise SystemExit("余额不足，请到 https://console.xiangxinai.cn 充值。") from None
        except RateLimitError as exc:
            raise SystemExit(f"请求过于频繁，请 {exc.retry_after or 1} 秒后重试。") from None

        urgent = resp.nouls["is_urgent"]
        dept = resp.choices["department"]
        mood = resp.scores["frustration"]

        print(f"模型：{resp.model}（模型耗时 {resp.model_ms}ms，请求 ID {resp.request_id}）")
        print(f"是否紧急：{urgent.noul:.0%}")
        print(f"分派部门：{dept.choice}（置信度 {dept.confidence:.2f}）")
        for label, p in sorted(dept.probabilities.items(), key=lambda kv: -kv[1]):
            print(f"    {label:<10} {p:.2f}")
        top = max(mood.probabilities, key=mood.probabilities.__getitem__)
        print(f"情绪分数：{mood.score:.2f} / {len(mood.legend) - 1}（最可能：{mood.legend.get(top)}）")
        print(f"输入 token：{resp.usage.input_tokens}")


if __name__ == "__main__":
    main()
