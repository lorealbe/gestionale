"""Geometry-first layout utilities."""

from __future__ import annotations

from collections import defaultdict
import re

from .models import BBox, Block, BlockType, Token
from .normalizers import normalize_text


def sort_tokens(tokens: list[Token]) -> list[Token]:
    return sorted(tokens, key=lambda t: (t.bbox.page, t.bbox.center_y, t.bbox.x0))


def group_tokens_into_lines(tokens: list[Token], y_tolerance: float) -> list[Block]:
    pages: dict[int, list[Token]] = defaultdict(list)
    for token in sort_tokens(tokens):
        pages[token.bbox.page].append(token)

    lines: list[Block] = []
    for page, page_tokens in pages.items():
        clustered: list[list[Token]] = []

        for token in page_tokens:
            attached = False
            for line_tokens in clustered:
                center = _line_center_y(line_tokens)
                if abs(token.bbox.center_y - center) <= y_tolerance:
                    line_tokens.append(token)
                    attached = True
                    break
            if not attached:
                clustered.append([token])

        clustered.sort(key=lambda row: min(item.bbox.y0 for item in row))
        for idx, line_tokens in enumerate(clustered):
            ordered = sorted(line_tokens, key=lambda t: t.bbox.x0)
            lines.append(
                Block(
                    block_id=f"line_p{page}_{idx}",
                    block_type=BlockType.TEXT_LINE,
                    bbox=union_bbox(ordered),
                    tokens=ordered,
                    confidence=1.0,
                )
            )

    return sorted(lines, key=lambda b: (b.bbox.page, b.bbox.y0, b.bbox.x0))


def group_lines_into_blocks(lines: list[Block], vertical_gap: float) -> list[Block]:
    grouped: list[Block] = []
    pages: dict[int, list[Block]] = defaultdict(list)
    for line in lines:
        pages[line.bbox.page].append(line)

    for page, page_lines in pages.items():
        ordered = sorted(page_lines, key=lambda b: b.bbox.y0)
        chunk: list[Block] = []

        for line in ordered:
            if not chunk:
                chunk = [line]
                continue

            previous = chunk[-1]
            gap = line.bbox.y0 - previous.bbox.y1
            if gap <= vertical_gap:
                chunk.append(line)
            else:
                grouped.append(_build_text_block(page, len(grouped), chunk))
                chunk = [line]

        if chunk:
            grouped.append(_build_text_block(page, len(grouped), chunk))

    return grouped


def line_text(line: Block) -> str:
    return normalize_text(" ".join(token.text for token in line.tokens))


def extract_document_text(lines: list[Block]) -> str:
    return "\n".join(line_text(line) for line in lines if line.tokens)


def find_labeled_value(
    lines: list[Block],
    labels: list[str],
    max_horizontal_distance: float,
    max_vertical_distance: float,
) -> tuple[str | None, float, str | None]:
    if not labels:
        return None, 0.0, None

    normalized_labels = [normalize_text(label.lower()) for label in labels]
    ordered_lines = sorted(lines, key=lambda l: (l.bbox.page, l.bbox.y0, l.bbox.x0))

    for index, line in enumerate(ordered_lines):
        text = line_text(line)
        matching_label = next((label for label in normalized_labels if _label_matches_line(line, label)), None)
        if not matching_label:
            continue

        inline_value = _value_from_same_line(line, matching_label, max_horizontal_distance)
        if inline_value:
            return inline_value, 0.9, line.block_id

        if index + 1 < len(ordered_lines):
            next_line = ordered_lines[index + 1]
            if (
                next_line.bbox.page == line.bbox.page
                and 0 <= next_line.bbox.y0 - line.bbox.y1 <= (max_vertical_distance * 2)
            ):
                value = line_text(next_line)
                if value:
                    return value, 0.78, next_line.block_id

    return None, 0.0, None


def union_bbox(tokens: list[Token]) -> BBox:
    if not tokens:
        raise ValueError("Cannot build bounding box from empty token list")

    page = tokens[0].bbox.page
    return BBox(
        page=page,
        x0=min(token.bbox.x0 for token in tokens),
        y0=min(token.bbox.y0 for token in tokens),
        x1=max(token.bbox.x1 for token in tokens),
        y1=max(token.bbox.y1 for token in tokens),
    )


def _line_center_y(tokens: list[Token]) -> float:
    return sum(token.bbox.center_y for token in tokens) / len(tokens)


def _value_from_same_line(line: Block, label: str, max_horizontal_distance: float) -> str | None:
    text = line_text(line)

    if ":" in text:
        left, right = text.split(":", maxsplit=1)
        if _label_matches_text(left.lower(), label) and right.strip():
            return right.strip()

    label_tokens = set(_tokenize_label(label))
    candidate_tokens: list[Token] = []
    label_right_edge = 0.0

    for token in line.tokens:
        token_norm = normalize_text(token.text.lower()).strip(".:")
        if token_norm in label_tokens:
            label_right_edge = max(label_right_edge, token.bbox.x1)

    if label_right_edge <= 0:
        return None

    for token in line.tokens:
        if token.bbox.x0 <= label_right_edge:
            continue
        if token.bbox.x0 - label_right_edge <= max_horizontal_distance:
            candidate_tokens.append(token)

    if not candidate_tokens:
        return None

    value = normalize_text(" ".join(token.text for token in sorted(candidate_tokens, key=lambda t: t.bbox.x0)))
    return value or None


def _build_text_block(page: int, index: int, lines: list[Block]) -> Block:
    all_tokens: list[Token] = []
    for line in lines:
        all_tokens.extend(line.tokens)

    return Block(
        block_id=f"block_p{page}_{index}",
        block_type=BlockType.TEXT_BLOCK,
        bbox=union_bbox(all_tokens),
        tokens=sorted(all_tokens, key=lambda t: (t.bbox.page, t.bbox.y0, t.bbox.x0)),
        confidence=1.0,
    )


def _label_matches_line(line: Block, label: str) -> bool:
    line_tokens = [_normalize_token(token.text) for token in line.tokens]
    line_tokens = [token for token in line_tokens if token]
    label_tokens = _tokenize_label(label)

    if not label_tokens:
        return False

    if len(label_tokens) == 1 and len(label_tokens[0]) <= 3:
        return label_tokens[0] in line_tokens

    window = len(label_tokens)
    for index in range(len(line_tokens) - window + 1):
        if line_tokens[index : index + window] == label_tokens:
            return True

    return _label_matches_text(line_text(line).lower(), label)


def _label_matches_text(text: str, label: str) -> bool:
    tokens = _tokenize_label(label)
    if not tokens:
        return False

    pattern = r"\b" + r"\s+".join(re.escape(token) for token in tokens) + r"\b"
    return re.search(pattern, _normalize_token_text(text)) is not None


def _tokenize_label(label: str) -> list[str]:
    return [token for token in re.split(r"[^a-z0-9]+", label.lower()) if token]


def _normalize_token(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "", value.lower())
    return cleaned


def _normalize_token_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()
