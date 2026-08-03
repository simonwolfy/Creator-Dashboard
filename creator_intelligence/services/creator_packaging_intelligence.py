from __future__ import annotations

from datetime import datetime
import json
import re
from typing import Any


class CreatorPackagingIntelligenceMixin:
    """Local packaging intelligence for titles, captions, hooks, and platforms."""

    def _ensure_clip_intelligence_columns(self) -> None:
        super()._ensure_clip_intelligence_columns()
        existing = {
            str(row["name"])
            for _, row in self.db.frame(
                "PRAGMA table_info(transcript_clip_candidates)"
            ).iterrows()
        }
        columns = {
            "title_alternatives_json": "TEXT",
            "title_score": "REAL",
            "caption_style": "TEXT",
            "hook_line": "TEXT",
            "packaging_reasoning_json": "TEXT",
            "likely_audience": "TEXT",
            "replayability_score": "REAL",
            "shareability_score": "REAL",
            "retention_estimate": "REAL",
            "performance_prediction": "TEXT",
            "platform_packages_json": "TEXT",
        }
        for name, sql_type in columns.items():
            if name not in existing:
                self.db.execute(
                    f"ALTER TABLE transcript_clip_candidates ADD COLUMN {name} {sql_type}"
                )

    def analyze_clip_candidate(self, clip_id: int) -> dict[str, Any]:
        frame = self.db.frame(
            "SELECT * FROM transcript_clip_candidates WHERE id=?", (int(clip_id),)
        )
        if frame.empty:
            raise KeyError(clip_id)
        clip = frame.iloc[0].to_dict()
        transcript_id = int(clip["transcript_id"])
        start = float(clip["start_seconds"])
        end = float(clip["end_seconds"])
        segments = self.segments(transcript_id, start=start, end=end)
        text = " ".join(
            str(value).strip() for value in segments.get("text", []) if str(value).strip()
        ).strip() or str(clip.get("title") or "").strip()

        analysis = self._score_clip_text(text, start, end)
        package = self._build_creator_package(text, analysis)
        analysis.update(package)
        now = datetime.now().isoformat()
        self.db.execute(
            """UPDATE transcript_clip_candidates SET
               hook_score=?,humor_score=?,surprise_score=?,emotion_score=?,
               quote_score=?,viral_score=?,suggested_start_seconds=?,
               suggested_end_seconds=?,suggested_title=?,suggested_caption=?,
               suggested_hashtags_json=?,title_alternatives_json=?,title_score=?,
               caption_style=?,hook_line=?,packaging_reasoning_json=?,likely_audience=?,
               replayability_score=?,shareability_score=?,retention_estimate=?,
               performance_prediction=?,platform_packages_json=?,
               intelligence_version=?,analyzed_at=?,updated_at=? WHERE id=?""",
            (
                analysis["hook_score"], analysis["humor_score"],
                analysis["surprise_score"], analysis["emotion_score"],
                analysis["quote_score"], analysis["viral_score"],
                analysis["suggested_start_seconds"], analysis["suggested_end_seconds"],
                analysis["suggested_title"], analysis["suggested_caption"],
                json.dumps(analysis["suggested_hashtags"]),
                json.dumps(analysis["title_alternatives"]), analysis["title_score"],
                analysis["caption_style"], analysis["hook_line"],
                json.dumps(analysis["packaging_reasoning"]), analysis["likely_audience"],
                analysis["replayability_score"], analysis["shareability_score"],
                analysis["retention_estimate"], analysis["performance_prediction"],
                json.dumps(analysis["platform_packages"]),
                "creator-packaging-v2", now, now, int(clip_id),
            ),
        )
        return {"id": int(clip_id), **analysis}

    @classmethod
    def _build_creator_package(cls, text: str, analysis: dict[str, Any]) -> dict[str, Any]:
        clean = re.sub(r"\s+", " ", text).strip()
        lowered = clean.lower()
        topic = cls._topic_label(lowered)
        moment = cls._moment_type(lowered, analysis)
        titles = cls._title_options(moment, topic, lowered)
        title = titles[0]
        title_score = min(100.0, analysis["hook_score"] * 0.45 + analysis["viral_score"] * 0.55)
        caption, style = cls._social_caption(moment, topic)
        hook = cls._hook_line(moment)
        hashtags = cls._contextual_hashtags(lowered, topic, moment)
        reasoning = cls._packaging_reasoning(clean, analysis, moment)
        replay = min(100.0, analysis["surprise_score"] * 0.45 + analysis["quote_score"] * 0.35 + 15)
        share = min(100.0, analysis["humor_score"] * 0.30 + analysis["emotion_score"] * 0.25 + analysis["viral_score"] * 0.45)
        retention = min(95.0, 38 + analysis["hook_score"] * 0.32 + analysis["quote_score"] * 0.18)
        performance = "High" if analysis["viral_score"] >= 70 else "Moderate" if analysis["viral_score"] >= 45 else "Experimental"
        audience = f"{topic} viewers" if topic != "Gaming" else "Gaming and livestream viewers"
        platform_packages = {
            "youtube_shorts": {
                "title": title,
                "description": caption,
                "hook": hook,
                "hashtags": hashtags[:5],
            },
            "tiktok": {
                "caption": caption,
                "hook": hook,
                "hashtags": hashtags[:6],
            },
            "instagram_reels": {
                "caption": caption,
                "hook": hook,
                "hashtags": hashtags[:8],
            },
        }
        return {
            "suggested_title": title,
            "title_alternatives": titles,
            "title_score": round(title_score, 1),
            "suggested_caption": caption,
            "caption_style": style,
            "hook_line": hook,
            "suggested_hashtags": hashtags,
            "packaging_reasoning": reasoning,
            "likely_audience": audience,
            "replayability_score": round(replay, 1),
            "shareability_score": round(share, 1),
            "retention_estimate": round(retention, 1),
            "performance_prediction": performance,
            "platform_packages": platform_packages,
        }

    @staticmethod
    def _topic_label(lowered: str) -> str:
        topics = (
            ("minecraft", "Minecraft"), ("tarkov", "Escape from Tarkov"),
            ("rimworld", "RimWorld"), ("pokemon", "Pokémon"),
            ("zomboid", "Project Zomboid"),
        )
        for token, label in topics:
            if token in lowered:
                return label
        return "Gaming"

    @staticmethod
    def _moment_type(lowered: str, analysis: dict[str, Any]) -> str:
        if any(term in lowered for term in ("hallucination", "what did i", "brain", "confused")):
            return "confusion"
        if any(term in lowered for term in ("died", "death", "failed", "lost", "mistake")):
            return "fail"
        if any(term in lowered for term in ("secret", "found", "discovered", "hidden")):
            return "discovery"
        if analysis["humor_score"] >= max(analysis["surprise_score"], analysis["emotion_score"]):
            return "funny"
        if analysis["surprise_score"] >= analysis["emotion_score"]:
            return "surprise"
        return "reaction"

    @staticmethod
    def _title_options(moment: str, topic: str, lowered: str) -> list[str]:
        templates = {
            "confusion": [
                "My Brain Completely Broke on Stream",
                "I Have Absolutely No Explanation for This",
                "This Conversation Went Completely Off the Rails",
                "What Did I Just Say?",
                "I Was Not Ready for This Moment",
            ],
            "fail": [
                "This Went Wrong Immediately",
                "The Most Avoidable Fail of the Stream",
                "I Knew This Was a Bad Idea",
                "Everything Fell Apart in Seconds",
                "This Mistake Cost Me Everything",
            ],
            "discovery": [
                "I Was Not Supposed to Find This",
                "The Secret I Almost Missed",
                "This Changed the Entire Run",
                "I Finally Found It",
                "Nobody Warned Me About This",
            ],
            "funny": [
                "This Might Be My Funniest Stream Moment",
                "I Could Not Stop Laughing After This",
                "The Timing Could Not Have Been Better",
                "Chat Completely Lost It Here",
                "This Got Funnier Every Second",
            ],
            "surprise": [
                "I Did Not See That Coming",
                "This Escalated Way Too Fast",
                "Wait Until You See What Happened",
                "The Stream Took a Wild Turn",
                "That Was the Last Thing I Expected",
            ],
            "reaction": [
                "My Honest Reaction Says Everything",
                "I Was Completely Speechless",
                "This Moment Caught Me Off Guard",
                "You Can See the Exact Moment I Realized",
                "I Still Cannot Believe This Happened",
            ],
        }
        options = templates[moment][:]
        if topic != "Gaming":
            options[0] = f"{options[0]} in {topic}"
        return options

    @staticmethod
    def _social_caption(moment: str, topic: str) -> tuple[str, str]:
        captions = {
            "confusion": "I genuinely have no idea what my brain was doing here 😂 What did you hear?",
            "fail": "I knew this was a bad idea and did it anyway. Be honest—would you have made the same mistake?",
            "discovery": "I almost walked right past this. Did you already know it was here?",
            "funny": "The timing on this absolutely destroyed me 😂 Who else would have lost it here?",
            "surprise": "This escalated so much faster than I expected. Did you see that coming?",
            "reaction": "My face says everything. What would your reaction have been?",
        }
        caption = captions[moment]
        if topic != "Gaming":
            caption = f"{caption} #{topic.replace(' ', '').replace('Pokémon', 'Pokemon')}"
        return caption, "conversational-engagement"

    @staticmethod
    def _hook_line(moment: str) -> str:
        return {
            "confusion": "Wait until you hear what I accidentally said…",
            "fail": "This gets worse every second.",
            "discovery": "I nearly missed the best part of the entire run.",
            "funny": "I was not prepared for how funny this got.",
            "surprise": "Nobody in chat saw this coming.",
            "reaction": "Watch the exact moment I realize what happened.",
        }[moment]

    @staticmethod
    def _contextual_hashtags(lowered: str, topic: str, moment: str) -> list[str]:
        tags = ["#TwitchClips", "#StreamerMoments", "#GamingShorts"]
        topic_tags = {
            "Minecraft": ["#Minecraft", "#MinecraftShorts", "#MinecraftFunny"],
            "Escape from Tarkov": ["#EscapeFromTarkov", "#Tarkov", "#TarkovMoments"],
            "RimWorld": ["#RimWorld", "#RimWorldStories", "#ColonySim"],
            "Pokémon": ["#Pokemon", "#PokemonGaming", "#PokemonMoments"],
            "Project Zomboid": ["#ProjectZomboid", "#ZombieSurvival", "#ZomboidMoments"],
        }
        tags.extend(topic_tags.get(topic, ["#Gaming", "#GamingClips"]))
        moment_tags = {
            "confusion": "#FunnyMoments", "fail": "#GamingFails",
            "discovery": "#HiddenDetails", "funny": "#GamingComedy",
            "surprise": "#Unexpected", "reaction": "#StreamerReaction",
        }
        tags.append(moment_tags[moment])
        return list(dict.fromkeys(tags))[:8]

    @staticmethod
    def _packaging_reasoning(text: str, analysis: dict[str, Any], moment: str) -> list[str]:
        reasons = [f"Detected a {moment} moment with a clear emotional angle."]
        if analysis["hook_score"] >= 50:
            reasons.append("The opening creates enough curiosity to stop a scroll.")
        if analysis["quote_score"] >= 65:
            reasons.append("The dialogue contains a short, memorable line that can stand alone.")
        if analysis["surprise_score"] >= 45:
            reasons.append("The payoff is unexpected, which supports replays and comments.")
        if len(text.split()) <= 70:
            reasons.append("The moment is compact enough for short-form pacing.")
        reasons.append("The caption asks a direct question to encourage comments.")
        return reasons
