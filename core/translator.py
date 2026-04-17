"""
LLM-based translation helpers.
"""

from __future__ import annotations

import re
import time
from typing import Optional

from utils.config import LLMConfig


SYSTEM_PROMPT_TEMPLATE = """\
You are a professional real-time translator specializing in {target_language}.

<guidelines>
- Translate the given text into {target_language} naturally and fluently
- Follow {target_language} expression conventions so the result sounds native
- Keep speaker point of view and subject references consistent
- The input may contain speaker tags like [Speaker 1]; use them only to keep turns separate
- Do not copy speaker tags into the output
- If the source is in first person, use one appropriate first-person form consistently for the same speaker
- Do not mix alternative self-references for the same subject unless the source clearly changes register or speaker
- For proper nouns or technical terms, keep the original or transliterate when appropriate
- Use culturally appropriate expressions to make content relatable to the target audience
- If a sentence is incomplete at the end, translate what you have naturally
- Maintain consistency with previous context provided
- The input may contain transcription errors; use context to infer the intended meaning
- If a line is already in {target_language}, keep its meaning naturally and do not re-translate it unnecessarily
</guidelines>

<output_rules>
- Return ONLY the translated text, nothing else
- Do NOT add explanations, notes, or any extra content
- Do NOT add quotation marks around the translation
- Preserve paragraph breaks if present in the input
- Each sentence should be on its own line for readability
</output_rules>\
"""

REWRITE_SYSTEM_PROMPT_TEMPLATE = """\
You are a professional translator and editor specializing in {target_language}.

<task>
- Translate the full transcript into {target_language}
- Rewrite the translation so it reads naturally, smoothly, and coherently
- Fix likely transcription mistakes when the intended meaning is clear from context
- Preserve meaning, order, and tone
- Keep speaker identity, subject references, and pronouns consistent across the transcript
- Input segments may contain speaker tags like [Speaker 1]; use them only for context
- Do not include speaker tags in the output
- If the source uses first person, do not mix forms such as "t\u00f4i" and "m\u00ecnh" for the same speaker unless the source explicitly shifts register
</task>

<output_rules>
- Return EXACTLY one output line for each input segment
- Keep the segment id at the start of each line using this format: <id>TAB<translation>
- Do NOT merge segments
- Do NOT split one segment into multiple output lines
- Do NOT add explanations, notes, headers, or markdown
- If a segment is unclear, still provide the best natural translation for that segment
</output_rules>\
"""

GLOSSARY_BLOCK_TEMPLATE = """\

<glossary>
Use the following terminology mappings. When these terms appear in the source, \
translate them exactly as specified:
{glossary}
</glossary>\
"""

REFERENCE_BLOCK_TEMPLATE = """\

<reference_manuscript>
The following is the original manuscript or reference text for this content. \
Use it to correct transcription errors and improve translation accuracy:
{reference_text}
</reference_manuscript>\
"""

CORRECTION_BLOCK_TEMPLATE = """\

<correction_instructions>
Apply these specific correction requirements when rewriting:
{correction_instructions}
</correction_instructions>\
"""


class Translator:
    def __init__(self, config: LLMConfig):
        from openai import OpenAI

        self.config = config
        self._client = OpenAI(
            base_url=config.base_url,
            api_key=config.api_key,
        )
        self._system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
            target_language=config.target_language,
        )
        self._rewrite_system_prompt = REWRITE_SYSTEM_PROMPT_TEMPLATE.format(
            target_language=config.target_language,
        )
        if config.custom_prompt:
            custom_block = (
                f"\n\n<custom_instructions>\n{config.custom_prompt}\n</custom_instructions>"
            )
            self._system_prompt += custom_block
            self._rewrite_system_prompt += custom_block

        # Manuscript matching blocks — only added to rewrite prompt
        if config.glossary and config.glossary.strip():
            self._rewrite_system_prompt += GLOSSARY_BLOCK_TEMPLATE.format(
                glossary=config.glossary.strip(),
            )
        if config.reference_text and config.reference_text.strip():
            self._rewrite_system_prompt += REFERENCE_BLOCK_TEMPLATE.format(
                reference_text=config.reference_text.strip(),
            )
        if config.correction_instructions and config.correction_instructions.strip():
            self._rewrite_system_prompt += CORRECTION_BLOCK_TEMPLATE.format(
                correction_instructions=config.correction_instructions.strip(),
            )

    def _request_completion(
        self,
        *,
        system_prompt: str,
        user_message: str,
        max_tokens: int,
    ) -> Optional[str]:
        started_at = time.time()
        response = self._client.chat.completions.create(
            model=self.config.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            temperature=self.config.temperature,
            max_tokens=max_tokens,
        )

        text = None
        if hasattr(response, "choices") and response.choices:
            text = response.choices[0].message.content
        elif isinstance(response, dict) and response.get("choices"):
            text = response["choices"][0].get("message", {}).get("content")

        if text is None:
            print(f"[translator] API error: missing choices in response: {response}")
            return None

        text = text.strip()
        latency_ms = int((time.time() - started_at) * 1000)
        print(
            f"[translator] +{latency_ms}ms | {user_message[:50]}... -> "
            f"{text[:50] if text else 'None'}..."
        )
        return text or None

    def translate(self, text: str, context: Optional[list[str]] = None) -> Optional[str]:
        if not text or not text.strip():
            return None

        context_str = ""
        if context:
            context_lines = "\n".join(f"- {item}" for item in context if item.strip())
            if context_lines:
                context_str = (
                    f"\n<previous_context>\n{context_lines}\n</previous_context>\n"
                )

        user_message = f"{context_str}\n<translate>\n{text}\n</translate>"

        try:
            return self._request_completion(
                system_prompt=self._system_prompt,
                user_message=user_message,
                max_tokens=1000,
            )
        except Exception as exc:
            print(f"[translator] Error: {exc}")
            return None

    def rewrite_transcript(
        self,
        segments: list[str],
        context: Optional[list[str]] = None,
    ) -> Optional[list[str]]:
        clean_segments = [segment.strip() for segment in segments]
        if not clean_segments or not any(clean_segments):
            return None

        context_str = ""
        if context:
            context_lines = "\n".join(f"- {item}" for item in context if item.strip())
            if context_lines:
                context_str = (
                    f"\n<previous_context>\n{context_lines}\n</previous_context>\n"
                )

        indexed_segments = "\n".join(
            f"{idx}\t{text}" for idx, text in enumerate(clean_segments, start=1)
        )
        user_message = f"{context_str}\n<segments>\n{indexed_segments}\n</segments>"

        try:
            response_text = self._request_completion(
                system_prompt=self._rewrite_system_prompt,
                user_message=user_message,
                max_tokens=max(1500, len(clean_segments) * 80),
            )
        except Exception as exc:
            print(f"[translator] Rewrite error: {exc}")
            return None

        if not response_text:
            return None

        parsed: dict[int, str] = {}
        for raw_line in response_text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            match = re.match(r"^(\d+)\t(.+)$", line)
            if not match:
                continue
            parsed[int(match.group(1))] = match.group(2).strip()

        if len(parsed) == len(clean_segments):
            return [parsed[idx] for idx in range(1, len(clean_segments) + 1)]

        fallback_lines = [line.strip() for line in response_text.splitlines() if line.strip()]
        if len(fallback_lines) == len(clean_segments):
            return fallback_lines

        print(
            f"[translator] Rewrite parse mismatch: expected {len(clean_segments)} lines, "
            f"got {len(parsed) or len(fallback_lines)}"
        )
        return None

    def close(self) -> None:
        self._client.close()
