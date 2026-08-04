from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from typing import Any

from creator_intelligence.services.creator_packaging_intelligence import (
    CreatorPackagingIntelligenceMixin,
)


@dataclass(frozen=True)
class PackagingContext:
    subject: str
    action: str
    outcome: str
    quote: str
    emotion: str
    clip_type: str
    topic: str
    nouns: list[str]
    verbs: list[str]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


_STOPWORDS = {
    "a", "about", "actually", "after", "again", "all", "am", "an", "and",
    "are", "as", "at", "be", "because", "been", "before", "being", "but",
    "by", "can", "could", "did", "do", "does", "doing", "for", "from",
    "get", "got", "had", "has", "have", "he", "her", "here", "him", "his",
    "how", "i", "if", "in", "into", "is", "it", "its", "just", "like",
    "me", "more", "my", "no", "not", "now", "of", "oh", "on", "one",
    "or", "our", "out", "really", "said", "she", "so", "some", "that",
    "the", "their", "them", "then", "there", "they", "this", "to", "too",
    "up", "us", "was", "we", "were", "what", "when", "where", "which",
    "who", "why", "with", "would", "yeah", "you", "your",
}

_VERBS = {
    "attack", "attacked", "break", "broke", "build", "built", "catch", "caught",
    "destroy", "destroyed", "die", "died", "discover", "discovered", "escape",
    "escaped", "fail", "failed", "fight", "fought", "find", "found", "kill",
    "killed", "lose", "lost", "open", "opened", "save", "saved", "shoot",
    "shot", "steal", "stole", "survive", "survived", "win", "won",
}


class CreatorPackagingContextMixin(CreatorPackagingIntelligenceMixin):
    """Adds transcript metadata and event extraction to packaging analysis."""

    def analyze_clip_candidate(self, clip_id: int) -> dict[str, Any]:
        frame = self.db.frame(
            "SELECT transcript_id FROM transcript_clip_candidates WHERE id=?",
            (int(clip_id),),
        )
        if frame.empty:
            raise KeyError(clip_id)
        transcript = self.transcript(int(frame.iloc[0]["transcript_id"]))
        self._packaging_context_title = str(
            transcript.get("title")
            or transcript.get("display_name")
            or transcript.get("media_asset")
            or ""
        ).strip()
        try:
            return super().analyze_clip_candidate(clip_id)
        finally:
            self._packaging_context_title = ""


def topic_from_text(text: str) -> str:
    lowered = text.lower()
    topics = (
        (("minecraft", "pixelmon", "cobblemon"), "Minecraft"),
        (("tarkov", "escape from tarkov"), "Escape from Tarkov"),
        (("rimworld", "rim world"), "RimWorld"),
        (("pokemon", "pokémon"), "Pokémon"),
        (("zomboid", "project zomboid"), "Project Zomboid"),
    )
    for tokens, label in topics:
        if any(token in lowered for token in tokens):
            return label
    return "Gaming"


def extract_packaging_context(
    text: str,
    metadata: str,
    analysis: dict[str, Any],
) -> PackagingContext:
    clean = re.sub(r"\s+", " ", text).strip()
    lowered = clean.lower()
    topic = topic_from_text(f"{metadata} {clean}")
    words = re.findall(r"[a-zA-Z][a-zA-Z'-]+", lowered)
    nouns = [word for word in words if word not in _STOPWORDS and word not in _VERBS]
    verbs = [word for word in words if word in _VERBS]
    subject = _select_subject(nouns, lowered)
    action = _select_action(verbs, lowered)
    clip_type, emotion = _classify(lowered, analysis, action)
    return PackagingContext(
        subject=subject,
        action=action,
        outcome=_outcome(lowered, clip_type, subject),
        quote=_strongest_quote(clean),
        emotion=emotion,
        clip_type=clip_type,
        topic=topic,
        nouns=list(dict.fromkeys(nouns))[:8],
        verbs=list(dict.fromkeys(verbs))[:6],
    )


def _select_subject(nouns: list[str], lowered: str) -> str:
    preferred = (
        "sheep", "coffee", "tunnel", "colony", "raid", "boss", "wolf", "zombie",
        "pokemon", "pokémon", "village", "base", "cave", "dragon", "enemy", "chat",
    )
    for token in preferred:
        if token in lowered:
            return token
    if nouns:
        counts = {word: nouns.count(word) for word in set(nouns)}
        return max(counts, key=lambda word: (counts[word], len(word)))
    return "moment"


def _select_action(verbs: list[str], lowered: str) -> str:
    action_pairs = (
        (("destroy", "destroyed", "kill", "killed"), "destroy"),
        (("find", "found", "discover", "discovered"), "discover"),
        (("die", "died", "lose", "lost", "fail", "failed"), "fail"),
        (("win", "won", "save", "saved", "survive", "survived"), "win"),
        (("attack", "attacked", "fight", "fought", "shoot", "shot"), "fight"),
        (("build", "built"), "build"),
        (("catch", "caught"), "catch"),
        (("escape", "escaped"), "escape"),
    )
    for tokens, label in action_pairs:
        if any(token in lowered for token in tokens):
            return label
    return verbs[0] if verbs else "react"


def _classify(lowered: str, analysis: dict[str, Any], action: str) -> tuple[str, str]:
    if any(token in lowered for token in ("hallucination", "confused", "what did i", "brain")):
        return "CONFUSION", "confusion"
    if action == "fail":
        return "FAIL", "frustration"
    if action == "win":
        return "VICTORY", "excitement"
    if action == "discover" or any(token in lowered for token in ("secret", "hidden")):
        return "DISCOVERY", "surprise"
    if action in {"destroy", "fight"} and any(token in lowered for token in ("finally", "war", "enemy")):
        return "CHAOS", "anticipation"
    if any(token in lowered for token in ("accident", "accidentally", "mistake")):
        return "ACCIDENT", "surprise"
    if analysis.get("humor_score", 0) >= 45:
        return "FUNNY_QUOTE", "humor"
    if analysis.get("surprise_score", 0) >= analysis.get("emotion_score", 0):
        return "SURPRISE", "surprise"
    return "REACTION", "reaction"


def _outcome(lowered: str, clip_type: str, subject: str) -> str:
    if "finally" in lowered:
        return f"the {subject} problem finally reached a payoff"
    return {
        "FAIL": "the plan fell apart",
        "VICTORY": "the run finally paid off",
        "DISCOVERY": f"the hidden {subject} changed the run",
        "CONFUSION": "the conversation stopped making sense",
        "CHAOS": f"the {subject} became the target",
        "ACCIDENT": "an unintended choice created the payoff",
        "FUNNY_QUOTE": "the dialogue delivered the punchline",
        "SURPRISE": "the outcome was unexpected",
        "REACTION": "the reaction became the payoff",
    }.get(clip_type, "the moment produced a clear payoff")


def _strongest_quote(text: str) -> str:
    sentences = [part.strip(" .") for part in re.split(r"[.!?]+", text) if part.strip()]
    if not sentences:
        return text[:90].strip()
    scored = sorted(
        sentences,
        key=lambda sentence: (
            any(word in sentence.lower() for word in ("finally", "never", "secret", "destroy", "insane", "no way")),
            6 <= len(sentence.split()) <= 16,
            len(sentence),
        ),
        reverse=True,
    )
    return scored[0][:120]
