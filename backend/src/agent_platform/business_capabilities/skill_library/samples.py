"""Sample Skills shipped as initial data for a fresh Skill library.

These are demo records, not templates: templates live in ``templates.py`` and are
code-owned scaffolds the author copies before anything is stored. A sample is a
real row — it appears in the catalogue, can be opened, tested and re-published —
so the library is never empty on a first login.

Dependencies are deliberately not baked into the definitions below. A model
profile id and a knowledge base id are deployment facts, so ``seed.py`` injects
whichever ones the target installation actually has. ``dependency`` declares what
a given sample needs; ``publish`` says whether it should end up published.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from .models import SkillDefinition

SampleDependency = Literal["model", "knowledge", "none"]


@dataclass(frozen=True)
class SampleSkill:
    key: str
    name: str
    description: str
    category: str
    tags: tuple[str, ...]
    definition: dict[str, Any]
    dependency: SampleDependency = "model"
    publish: bool = True


SAMPLE_SKILLS: tuple[SampleSkill, ...] = (
    SampleSkill(
        key="customer-intent-recognition",
        name="客户意图识别",
        description="识别客户问题意图，分类后转交对应处理流程",
        category="service",
        tags=("NLP", "分类"),
        definition={
            "type": "instruction",
            "instructions": (
                "你是客服一线的意图识别器。阅读客户消息，判断意图类别与置信度。\n\n"
                "类别只有四种：\n"
                "- consult：产品、价格、活动等咨询\n"
                "- complaint：对服务或商品的不满、投诉\n"
                "- return：退换货、退款诉求\n"
                "- repair：售后报修、技术支持\n\n"
                "规则：\n"
                "1. 只依据客户原话判断，不臆测未提及的信息。\n"
                "2. 一句话包含多个诉求时，取最先出现的诉求作为主意图，其余写入 secondary。\n"
                "3. 置信度低于 0.6 时仍给出最可能的类别，并在 reason 中说明歧义来自哪里。\n"
            ),
            "parameters": [
                {
                    "name": "text",
                    "type": "string",
                    "required": True,
                    "description": "客户原话",
                }
            ],
            "output": {
                "format": "json",
                "schema": {
                    "type": "object",
                    "properties": {
                        "intent": {
                            "type": "string",
                            "enum": ["consult", "complaint", "return", "repair"],
                        },
                        "confidence": {"type": "number"},
                        "secondary": {"type": "array", "items": {"type": "string"}},
                        "reason": {"type": "string"},
                    },
                    "required": ["intent", "confidence", "reason"],
                    "additionalProperties": False,
                },
            },
        },
    ),
    SampleSkill(
        key="order-info-query",
        name="订单信息查询",
        description="查询订单状态、物流信息与预计送达时间",
        category="service",
        tags=("订单", "查询"),
        dependency="knowledge",
        definition={
            "type": "knowledge",
            "instructions": (
                "依据检索到的订单与物流知识，回答客户的订单状态问题。\n\n"
                "回答要求：\n"
                "1. 先给结论（当前状态），再给依据（知识库中的条款或记录）。\n"
                "2. 知识库没有对应信息时，明确说明「暂未查询到该订单信息」，不要猜测物流节点。\n"
                "3. 涉及赔付、时效承诺时只复述政策原文，不额外承诺。\n"
            ),
            "parameters": [
                {
                    "name": "order_id",
                    "type": "string",
                    "required": True,
                    "description": "订单号",
                },
                {
                    "name": "question",
                    "type": "string",
                    "required": False,
                    "description": "客户的具体问题，可留空",
                },
            ],
        },
    ),
    SampleSkill(
        key="invoice-extraction",
        name="发票信息提取",
        description="从发票中提取关键信息，输出结构化字段",
        category="finance",
        tags=("OCR", "提取"),
        definition={
            "type": "instruction",
            "instructions": (
                "从发票文本中提取结构化字段。只输出文本中明确出现的值，缺失字段填 null，不得推算。\n\n"
                "字段口径：\n"
                "- invoice_no：发票号码，保留原始位数，不补零\n"
                "- amount：价税合计，仅数字\n"
                "- tax：税额，仅数字\n"
                "- date：开票日期，统一 YYYY-MM-DD\n"
                "- seller：销售方名称，去掉纳税人识别号\n"
            ),
            "parameters": [
                {
                    "name": "text",
                    "type": "string",
                    "required": True,
                    "description": "发票 OCR 文本",
                }
            ],
            "output": {
                "format": "json",
                "schema": {
                    "type": "object",
                    "properties": {
                        "invoice_no": {"type": ["string", "null"]},
                        "amount": {"type": ["number", "null"]},
                        "tax": {"type": ["number", "null"]},
                        "date": {"type": ["string", "null"]},
                        "seller": {"type": ["string", "null"]},
                    },
                    "required": ["invoice_no", "amount", "date", "seller"],
                    "additionalProperties": False,
                },
            },
        },
    ),
    SampleSkill(
        key="sales-data-analysis",
        name="销售数据分析",
        description="分析销售数据，生成可直接汇报的分析报告",
        category="sales",
        tags=("分析", "报表"),
        definition={
            "type": "instruction",
            "instructions": (
                "你是销售分析助手。基于提供的销售数据，输出一份可直接汇报的分析。\n\n"
                "结构：\n"
                "1. 一句话结论\n"
                "2. 关键指标：营收、订单量、客单价、环比\n"
                "3. 异常点与可能原因\n"
                "4. 三条可执行建议\n\n"
                "约束：所有数字必须来自输入数据，缺数据就说明缺什么，不补造。百分比保留一位小数。\n"
            ),
            "parameters": [
                {
                    "name": "data",
                    "type": "string",
                    "required": True,
                    "description": "销售数据，CSV 或表格文本",
                },
                {
                    "name": "period",
                    "type": "string",
                    "required": False,
                    "description": "统计周期，例如 2026-10",
                },
            ],
        },
    ),
    SampleSkill(
        key="refund-policy-answer",
        name="退款政策解答",
        description="提供退款政策和处理指引，引用条款原文",
        category="service",
        tags=("政策", "指引"),
        dependency="knowledge",
        definition={
            "type": "knowledge",
            "instructions": (
                "依据检索到的退款政策回答客户问题。\n\n"
                "规则：\n"
                "1. 先给是否可退的结论，再列适用条款。\n"
                "2. 引用条款时保留原文关键句，不改写时限、比例等关键数字。\n"
                "3. 政策未覆盖的情形，说明「需人工核实」并建议转人工。\n"
                "4. 不承诺政策之外的补偿。\n"
            ),
            "parameters": [
                {
                    "name": "question",
                    "type": "string",
                    "required": True,
                    "description": "客户的退款问题",
                }
            ],
        },
    ),
    SampleSkill(
        key="customer-profile-analysis",
        name="客户画像分析",
        description="分析客户行为与偏好，输出画像标签",
        category="general",
        tags=("客户", "分析"),
        definition={
            "type": "instruction",
            "instructions": (
                "根据客户的历史交互与订单记录，输出画像标签与运营建议。\n\n"
                "要求：\n"
                "1. 标签分三类：价值（高/中/低）、行为（复购/流失风险/价格敏感）、偏好（品类/渠道）。\n"
                "2. 每个标签给出支撑依据，一句话即可。\n"
                "3. 不推断敏感个人信息，涉及健康、宗教、证件号的内容一律不输出。\n"
                "4. 最后给两条运营动作建议，注明优先级。\n"
            ),
            "parameters": [
                {
                    "name": "history",
                    "type": "string",
                    "required": True,
                    "description": "客户历史交互与订单记录",
                }
            ],
        },
    ),
    SampleSkill(
        key="code-generation-assistant",
        name="代码生成助手",
        description="根据需求生成代码示例与实现建议",
        category="general",
        tags=("研发", "编程", "代码"),
        publish=False,
        definition={
            "type": "instruction",
            "instructions": (
                "根据需求描述生成可运行的代码示例。\n\n"
                "要求：\n"
                "1. 先说明实现思路，三步以内，再给代码。\n"
                "2. 代码要能直接运行，包含必要的 import 与最小示例调用。\n"
                "3. 运行环境不确定时（语言版本、框架版本）先问一句，不猜。\n"
                "4. 不生成任何破坏性操作的代码：删库、批量删除、提权、绕过鉴权。\n"
            ),
            "parameters": [
                {
                    "name": "requirement",
                    "type": "string",
                    "required": True,
                    "description": "需求描述",
                },
                {
                    "name": "language",
                    "type": "string",
                    "required": False,
                    "description": "目标语言，留空则根据需求推断",
                },
            ],
        },
    ),
    SampleSkill(
        key="task-flow-suggestion",
        name="任务流程建议",
        description="推荐最佳的任务处理流程与顺序",
        category="general",
        tags=("流程", "建议"),
        definition={
            "type": "instruction",
            "instructions": (
                "根据任务描述，给出推荐的处理流程。\n\n"
                "输出格式：\n"
                "1. 流程步骤：编号，每步一句话，标注负责角色\n"
                "2. 可并行的步骤\n"
                "3. 风险点与检查项\n\n"
                "约束：步骤控制在 7 步以内；无法判断的前置条件单列为「待确认」，不要自行假设。\n"
            ),
            "parameters": [
                {
                    "name": "task",
                    "type": "string",
                    "required": True,
                    "description": "任务描述",
                }
            ],
        },
    ),
)


def validate_samples() -> None:
    """Fail fast at import time if a sample definition is malformed.

    Runs without release checks: samples may legitimately omit a dependency
    until the seed injects one, and ``instruction`` samples require a model
    profile at release time.
    """

    for sample in SAMPLE_SKILLS:
        SkillDefinition.model_validate(sample.definition)


validate_samples()

__all__ = ["SAMPLE_SKILLS", "SampleSkill", "validate_samples"]
