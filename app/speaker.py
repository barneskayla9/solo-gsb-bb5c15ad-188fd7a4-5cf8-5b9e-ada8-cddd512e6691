"""说话人轮次归属：把逐字时间轴上的每个修订字符按重叠时长归属到说话人轮次。

规则：
- 轮次为毫秒时间上的半开区间 [start, end)，按起始时间排序、互不重叠；
- 每个修订字符归属到与其时间区间重叠时长最大的轮次，并列时取较早轮次；
- 与所有轮次均无重叠时归属为 null；
- 零时长字符按其所在时点归属（半开点包含），落在边界上时归右侧轮次；
- 相邻且 speaker_id 相同（含同为 null）的字符合并为一块。
"""
from __future__ import annotations

from .errors import InvalidTimelineError
from .schemas import (
    RevisedCharTimeline,
    SpeakerBlock,
    SpeakerTurn,
    SpeakerTurnsRequest,
)


def validate_speaker_turns(req: SpeakerTurnsRequest) -> None:
    """校验说话人轮次：非负、起止合法、不越界、按起始时间排序且互不重叠。

    前置条件：请求已通过与 /align 相同的输入校验，total_duration 非负。
    """
    total = req.total_duration
    for idx, turn in enumerate(req.speaker_turns):
        if turn.start < 0 or turn.end < 0:
            raise InvalidTimelineError(
                f"第 {idx} 个说话人轮次 {turn.speaker_id!r} 的起止时间不能为负数："
                f"start={turn.start}, end={turn.end}")
        if turn.end < turn.start:
            raise InvalidTimelineError(
                f"第 {idx} 个说话人轮次 {turn.speaker_id!r} 的结束时间 {turn.end} "
                f"不能早于起始时间 {turn.start}")
        if turn.start > total or turn.end > total:
            raise InvalidTimelineError(
                f"第 {idx} 个说话人轮次 {turn.speaker_id!r} 的时间 "
                f"[{turn.start}, {turn.end}) 超出录音总时长 {total}")
        if idx > 0:
            prev = req.speaker_turns[idx - 1]
            if turn.start < prev.start:
                raise InvalidTimelineError(
                    f"说话人轮次必须按起始时间排序：第 {idx - 1} 个 start={prev.start}，"
                    f"第 {idx} 个 start={turn.start}")
            if turn.start < prev.end:
                raise InvalidTimelineError(
                    f"说话人轮次时间区间不得重叠：第 {idx - 1} 个 "
                    f"[{prev.start},{prev.end}) 与第 {idx} 个 "
                    f"[{turn.start},{turn.end}) 重叠")


def _assign(char: RevisedCharTimeline,
            turns: list[SpeakerTurn],
            cursor: int) -> tuple[str | None, int]:
    """把单个字符归属到重叠时长最大的轮次；返回 (speaker_id, 新游标)。

    字符与轮次均按起始时间单调，故轮次游标只前进不回退。
    """
    # 结束时点不晚于字符起点的轮次与本字及后续字符均无交集，直接跳过。
    while cursor < len(turns) and turns[cursor].end <= char.start:
        cursor += 1

    if char.start == char.end:
        # 零时长字符按所在时点归属（半开点包含），边界点天然归右侧轮次。
        if cursor < len(turns) and turns[cursor].start <= char.start:
            return turns[cursor].speaker_id, cursor
        return None, cursor

    best: str | None = None
    best_overlap = 0
    k = cursor
    while k < len(turns) and turns[k].start < char.end:
        overlap = min(turns[k].end, char.end) - max(turns[k].start, char.start)
        # 轮次有序，并列时保留首个（较早）轮次，故只在严格更大时更新。
        if overlap > best_overlap:
            best_overlap = overlap
            best = turns[k].speaker_id
        k += 1
    return best, cursor


def build_speaker_blocks(
        revised_text: str,
        chars: list[RevisedCharTimeline],
        turns: list[SpeakerTurn]) -> list[SpeakerBlock]:
    """逐字归属说话人，并把相邻归属相同的字符合并为块；无归属字符保留为 null 块。"""
    owners: list[str | None] = []
    cursor = 0
    for char in chars:
        owner, cursor = _assign(char, turns, cursor)
        owners.append(owner)

    blocks: list[SpeakerBlock] = []
    i = 0
    while i < len(owners):
        j = i + 1
        while j < len(owners) and owners[j] == owners[i]:
            j += 1
        blocks.append(SpeakerBlock(
            speaker_id=owners[i],
            start_index=i,
            end_index=j,
            text=revised_text[i:j],
            start=chars[i].start,
            end=chars[j - 1].end,
        ))
        i = j
    return blocks
