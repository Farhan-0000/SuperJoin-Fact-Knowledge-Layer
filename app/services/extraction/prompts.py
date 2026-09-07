"""System and user prompts for structured fact extraction."""

from __future__ import annotations

from typing import Optional

EXTRACTION_SYSTEM_PROMPT = """You extract factual claims from supplied document text.
Only extract facts directly supported by the supplied text.
A fact should be meaningful and potentially useful for cross-document comparison.
Prioritize:
numerical claims;
dates and periods;
people and roles;
organizations;
locations;
business metrics;
events;
quantities;
material semantic claims.
For every fact:
preserve the source wording;
identify subject and predicate;
preserve values and units;
preserve temporal context;
preserve scope and qualifiers;
provide an exact source quote;
do not infer unsupported facts;
do not compare this fact with facts from other chunks;
do not invent evidence."""


def build_extraction_messages(
    chunk_text: str,
    heading_path: Optional[list[str]] = None,
) -> list[dict[str, str]]:
    """Construct chat completion messages for a single chunk."""
    context_header = ""
    if heading_path:
        context_header = f"Section Context: {' > '.join(heading_path)}\n\n"

    user_prompt = f"""{context_header}Document Text:
\"\"\"
{chunk_text}
\"\"\"

Extract all meaningful factual claims from the text above following the structured schema.
Every extracted fact MUST provide an exact, verbatim source quote directly from the text above."""

    return [
        {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]
