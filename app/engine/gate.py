"""仲裁器（gate）：主动消息唯一发送出口。阶段 1 只做直通，阶段 2 实现真实策略。"""

from dataclasses import dataclass


@dataclass(frozen=True)
class GateOutcome:
    decision: str  # send | defer | merge | drop
    gate_reasons: dict
    policy_version: str


class PassthroughGate:
    """直通实现：所有候选放行，仍写决策日志。"""

    policy_version = "passthrough-v0"

    def decide(self, candidate: dict) -> GateOutcome:
        return GateOutcome(
            decision="send",
            gate_reasons={"policy": "passthrough", "stage": "p0"},
            policy_version=self.policy_version,
        )
