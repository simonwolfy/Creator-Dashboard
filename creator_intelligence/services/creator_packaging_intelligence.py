from __future__ import annotations

from datetime import datetime
from difflib import SequenceMatcher
import csv
import math
import json
import re
from typing import Any


class CreatorPackagingIntelligenceMixin:
    """Local, clip-specific packaging intelligence with duplicate prevention."""

    def _ensure_clip_intelligence_columns(self) -> None:
        super()._ensure_clip_intelligence_columns()
        existing = {
            str(row["name"])
            for _, row in self.db.frame("PRAGMA table_info(transcript_clip_candidates)").iterrows()
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
            "clip_type": "TEXT",
            "packaging_context_json": "TEXT",
        }
        for name, sql_type in columns.items():
            if name not in existing:
                self.db.execute(
                    f"ALTER TABLE transcript_clip_candidates ADD COLUMN {name} {sql_type}"
                )
        self.db.execute(
            """CREATE TABLE IF NOT EXISTS creator_package_history(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                clip_candidate_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                hook TEXT,
                caption TEXT,
                hashtags_json TEXT NOT NULL DEFAULT '[]',
                clip_type TEXT,
                approved INTEGER NOT NULL DEFAULT 0,
                published INTEGER NOT NULL DEFAULT 0,
                views INTEGER,
                ctr REAL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(clip_candidate_id, title)
            )"""
        )
        self.db.execute(
            """CREATE TABLE IF NOT EXISTS creator_published_titles(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                platform TEXT NOT NULL DEFAULT 'twitch',
                content_type TEXT NOT NULL DEFAULT 'clip',
                title TEXT NOT NULL,
                game TEXT,
                published_at TEXT,
                views INTEGER,
                likes INTEGER,
                comments INTEGER,
                watch_time REAL,
                example_type TEXT NOT NULL DEFAULT 'published',
                source_video_id TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(platform, content_type, title)
            )"""
        )
        self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_creator_titles_example ON creator_published_titles(example_type)"
        )

    def record_published_title(self, title: str, *, platform: str = "twitch",
                               content_type: str = "clip", game: str | None = None,
                               published_at: str | None = None, views: int | None = None,
                               likes: int | None = None, comments: int | None = None,
                               watch_time: float | None = None,
                               example_type: str = "published",
                               source_video_id: str | None = None) -> int:
        clean = re.sub(r"\s+", " ", str(title)).strip()
        if not clean:
            raise ValueError("Title cannot be empty.")
        kind = str(example_type).strip().lower()
        if kind not in {"published", "approved", "rejected"}:
            raise ValueError("example_type must be published, approved, or rejected.")
        now = datetime.now().isoformat()
        self.db.execute(
            """INSERT INTO creator_published_titles(
               platform,content_type,title,game,published_at,views,likes,comments,
               watch_time,example_type,source_video_id,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(platform,content_type,title) DO UPDATE SET
               game=excluded.game,published_at=excluded.published_at,
               views=excluded.views,likes=excluded.likes,comments=excluded.comments,
               watch_time=excluded.watch_time,example_type=excluded.example_type,
               source_video_id=excluded.source_video_id,updated_at=excluded.updated_at""",
            (platform.strip().lower(), content_type.strip().lower(), clean, game,
             published_at, views, likes, comments, watch_time, kind,
             source_video_id, now, now),
        )
        row = self.db.frame(
            "SELECT id FROM creator_published_titles WHERE platform=? AND content_type=? AND title=?",
            (platform.strip().lower(), content_type.strip().lower(), clean),
        )
        return int(row.iloc[0]["id"])

    def import_published_titles(self, path: str) -> dict[str, int]:
        counts = {"imported": 0, "skipped": 0}
        with open(path, "r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames or "title" not in {n.strip().lower() for n in reader.fieldnames}:
                raise ValueError("CSV must include a title column.")
            for raw in reader:
                row = {str(k).strip().lower(): v for k, v in raw.items()}
                if not str(row.get("title") or "").strip():
                    counts["skipped"] += 1
                    continue
                def number(name, cast):
                    value = str(row.get(name) or "").strip()
                    return cast(value) if value else None
                self.record_published_title(
                    row["title"], platform=row.get("platform") or "twitch",
                    content_type=row.get("content_type") or "clip", game=row.get("game") or None,
                    published_at=row.get("published_at") or None, views=number("views", int),
                    likes=number("likes", int), comments=number("comments", int),
                    watch_time=number("watch_time", float),
                    example_type=row.get("example_type") or "published",
                    source_video_id=row.get("source_video_id") or None,
                )
                counts["imported"] += 1
        return counts

    def published_titles(self):
        return self.db.frame("SELECT * FROM creator_published_titles ORDER BY COALESCE(published_at,created_at) DESC,id DESC")

    def title_style_profile(self) -> dict[str, Any]:
        frame = self.published_titles()
        weights = {"published": 3.0, "approved": 1.5, "rejected": -2.5}
        positives = []
        negatives = []
        for _, row in frame.iterrows():
            weight = weights.get(str(row["example_type"]), 0.0)
            if weight > 0 and str(row["example_type"]) == "published":
                views = float(row.get("views") or 0)
                interactions = float(row.get("likes") or 0) + float(row.get("comments") or 0)
                performance = min(2.0, math.log10(views + 1) / 3.0)
                if views:
                    performance += min(1.0, interactions / views * 10.0)
                weight *= 1.0 + performance
            item = (str(row["title"]), weight)
            (positives if item[1] > 0 else negatives).append(item)
        total = sum(weight for _, weight in positives) or 1.0
        def avg(fn): return sum(fn(title) * weight for title, weight in positives) / total
        token_scores: dict[str, float] = {}
        for title, weight in positives + negatives:
            for token in set(re.findall(r"[a-z0-9']+", title.lower())):
                token_scores[token] = token_scores.get(token, 0.0) + weight
        preferred = [k for k, v in sorted(token_scores.items(), key=lambda x: (-x[1], x[0])) if v > 0][:12]
        avoided = [k for k, v in sorted(token_scores.items(), key=lambda x: (x[1], x[0])) if v < 0][:12]
        return {
            "example_count": len(frame), "positive_count": len(positives),
            "negative_count": len(negatives), "average_words": round(avg(lambda t: len(t.split())), 1),
            "question_rate": round(avg(lambda t: t.rstrip().endswith("?")), 2),
            "first_person_rate": round(avg(lambda t: bool(re.search(r"\b(i|we|my|our)\b", t, re.I))), 2),
            "exclamation_rate": round(avg(lambda t: "!" in t), 2),
            "preferred_words": preferred, "avoided_words": avoided,
        }

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
        context_segments = self.segments(
            transcript_id, start=max(0.0, start - 30.0), end=end + 30.0
        )
        context_text = " ".join(
            str(value).strip()
            for value in context_segments.get("text", [])
            if str(value).strip()
        ).strip() or text
        metadata = str(getattr(self, "_packaging_context_title", "") or "").strip()

        analysis = self._score_clip_text(text, start, end)
        context = self._extract_context(
            context_text, metadata, analysis, focus_text=text,
            context_segment_count=len(context_segments),
        )
        package = self._build_creator_package(text, analysis, context, int(clip_id))
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
               performance_prediction=?,platform_packages_json=?,clip_type=?,
               packaging_context_json=?,intelligence_version=?,analyzed_at=?,updated_at=?
               WHERE id=?""",
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
                json.dumps(analysis["platform_packages"]), analysis["clip_type"],
                json.dumps(analysis["packaging_context"]),
                "creator-packaging-v5", now, now, int(clip_id),
            ),
        )
        self.db.execute(
            """INSERT OR REPLACE INTO creator_package_history(
               clip_candidate_id,title,hook,caption,hashtags_json,clip_type,
               approved,published,views,ctr,created_at,updated_at)
               VALUES(?,?,?,?,?,?,COALESCE((SELECT approved FROM creator_package_history
               WHERE clip_candidate_id=? AND title=?),0),
               COALESCE((SELECT published FROM creator_package_history
               WHERE clip_candidate_id=? AND title=?),0),NULL,NULL,?,?)""",
            (
                int(clip_id), analysis["suggested_title"], analysis["hook_line"],
                analysis["suggested_caption"], json.dumps(analysis["suggested_hashtags"]),
                analysis["clip_type"], int(clip_id), analysis["suggested_title"],
                int(clip_id), analysis["suggested_title"], now, now,
            ),
        )
        return {"id": int(clip_id), **analysis}

    def _build_creator_package(
        self,
        text: str,
        analysis: dict[str, Any],
        context: dict[str, Any],
        clip_id: int,
    ) -> dict[str, Any]:
        titles = (
            self._quote_title_options(context)
            if context.get("fallback_mode") == "quote"
            else self._title_options(context)
        )
        titles = self._rank_titles_for_creator(titles, clip_id)
        title = titles[0]
        caption, style = self._social_caption(context)
        hook = self._hook_line(context)
        hashtags = self._contextual_hashtags(context)
        reasoning = self._packaging_reasoning(text, analysis, context)
        replay = min(100.0, analysis["surprise_score"] * 0.45 + analysis["quote_score"] * 0.35 + 15)
        share = min(100.0, analysis["humor_score"] * 0.30 + analysis["emotion_score"] * 0.25 + analysis["viral_score"] * 0.45)
        retention = min(95.0, 38 + analysis["hook_score"] * 0.32 + analysis["quote_score"] * 0.18)
        title_score = min(100.0, analysis["hook_score"] * 0.45 + analysis["viral_score"] * 0.55 + 6)
        performance = "High" if analysis["viral_score"] >= 70 else "Moderate" if analysis["viral_score"] >= 45 else "Experimental"
        topic = context["topic"]
        audience = f"{topic} viewers" if topic != "Gaming" else "Gaming and livestream viewers"
        packages = {
            "youtube_shorts": {"title": title, "description": caption, "hook": hook, "hashtags": hashtags[:5]},
            "tiktok": {"caption": caption, "hook": hook, "hashtags": hashtags[:6]},
            "instagram_reels": {"caption": caption, "hook": hook, "hashtags": hashtags[:8]},
        }
        return {
            "suggested_title": title,
            "title_alternatives": titles[:5],
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
            "platform_packages": packages,
            "clip_type": context["clip_type"],
            "packaging_context": context,
        }

    def _rank_titles_for_creator(self, candidates: list[str], clip_id: int) -> list[str]:
        profile = self.title_style_profile()
        history = self.published_titles()
        old_titles = [str(value) for value in history.get("title", [])]
        package_history = self.db.frame(
            "SELECT title FROM creator_package_history WHERE clip_candidate_id<>?", (int(clip_id),)
        )
        old_titles += [str(value) for value in package_history.get("title", [])]
        preferred, avoided = set(profile["preferred_words"]), set(profile["avoided_words"])
        target_words = float(profile["average_words"] or 8)
        scored = []
        for index, candidate in enumerate(candidates):
            tokens = set(re.findall(r"[a-z0-9']+", candidate.lower()))
            style = 0.0
            if profile["example_count"]:
                style = 20 - abs(len(candidate.split()) - target_words) * 2
                style += len(tokens & preferred) * 3 - len(tokens & avoided) * 6
                style += 8 if candidate.endswith("?") == (profile["question_rate"] >= .5) else 0
                first_person = bool(re.search(r"\b(i|we|my|our)\b", candidate, re.I))
                style += 6 if first_person == (profile["first_person_rate"] >= .5) else 0
            similarity = max((self._similarity(candidate, old) for old in old_titles), default=0.0)
            duplicate_penalty = 100 if similarity >= .92 else 45 * max(0.0, similarity - .62)
            scored.append((style - duplicate_penalty - index * .01, candidate))
        return [title for _, title in sorted(scored, reverse=True)]

    @classmethod
    def _extract_context(cls, text: str, metadata: str, analysis: dict[str, Any],
                         *, focus_text: str | None = None,
                         context_segment_count: int = 1) -> dict[str, Any]:
        clean = re.sub(r"\s+", " ", text).strip()
        lowered = clean.lower()
        topic = cls._topic_label(f"{metadata} {clean}".lower())
        subject = cls._subject(lowered)
        action = cls._action(lowered)
        clip_type, emotion = cls._clip_type(lowered, analysis, action)
        quote = cls._strongest_quote(focus_text or clean)
        outcome = cls._outcome(lowered, subject, clip_type)
        subject_occurrences = len(re.findall(rf"\b{re.escape(subject)}s?\b", lowered))
        subject_confidence = min(0.95, 0.42 + subject_occurrences * 0.16)
        if subject == "moment":
            subject_confidence = 0.2
        action_confidence = 0.82 if action != "react" else 0.42
        outcome_confidence = 0.78 if clip_type not in {"REACTION", "SURPRISE"} else 0.52
        event_confidence = round(
            subject_confidence * 0.45 + action_confidence * 0.30
            + outcome_confidence * 0.25, 2
        )
        fallback_mode = "quote" if event_confidence < 0.60 else "event"
        return {
            "subject": subject,
            "action": action,
            "outcome": outcome,
            "quote": quote,
            "emotion": emotion,
            "clip_type": clip_type,
            "topic": topic,
            "confidence": {
                "subject": round(subject_confidence, 2),
                "action": round(action_confidence, 2),
                "outcome": round(outcome_confidence, 2),
                "event": event_confidence,
            },
            "fallback_mode": fallback_mode,
            "context_segment_count": int(context_segment_count),
        }

    @staticmethod
    def _topic_label(lowered: str) -> str:
        for tokens, label in (
            (("minecraft", "pixelmon", "cobblemon"), "Minecraft"),
            (("tarkov", "escape from tarkov"), "Escape from Tarkov"),
            (("rimworld", "rim world"), "RimWorld"),
            (("pokemon", "pokémon"), "Pokémon"),
            (("zomboid", "project zomboid"), "Project Zomboid"),
        ):
            if any(token in lowered for token in tokens):
                return label
        return "Gaming"

    @staticmethod
    def _subject(lowered: str) -> str:
        preferred = (
            "colonist", "colonists", "sheep", "coffee", "tunnel", "colony", "raid", "boss", "wolf", "zombie",
            "pokemon", "pokémon", "village", "base", "cave", "dragon", "enemy", "chat",
        )
        for token in preferred:
            if token in lowered:
                return "colonist" if token == "colonists" else token
        words = re.findall(r"[a-z][a-z'-]+", lowered)
        stop = {
            "this", "that", "there", "what", "with", "from", "have", "just",
            "they", "them", "your", "about", "which", "would", "could", "finally",
            "thing", "things", "stuff", "something", "someone", "person", "people",
            "item", "piece", "part", "place", "time", "way", "pants",
        }
        useful = [word for word in words if len(word) > 3 and word not in stop]
        return useful[0] if useful else "moment"

    @staticmethod
    def _action(lowered: str) -> str:
        for tokens, label in (
            (("destroy", "killed", "kill"), "destroy"),
            (("found", "find", "discover", "secret"), "discover"),
            (("died", "death", "failed", "lost"), "fail"),
            (("won", "win", "saved", "survived"), "win"),
            (("attack", "fight", "shot", "shoot"), "fight"),
            (("built", "build"), "build"),
            (("caught", "catch"), "catch"),
            (("debate", "debating", "discuss", "wear", "wearing"), "discuss"),
        ):
            if any(token in lowered for token in tokens):
                return label
        return "react"

    @staticmethod
    def _clip_type(lowered: str, analysis: dict[str, Any], action: str) -> tuple[str, str]:
        if any(token in lowered for token in ("hallucination", "confused", "what did i", "brain")):
            return "CONFUSION", "confusion"
        if action == "fail":
            return "FAIL", "frustration"
        if action == "win":
            return "VICTORY", "excitement"
        if action == "discover":
            return "DISCOVERY", "surprise"
        if action in {"destroy", "fight"}:
            return "CHAOS", "anticipation"
        if "accident" in lowered or "mistake" in lowered:
            return "ACCIDENT", "surprise"
        if analysis.get("humor_score", 0) >= 45:
            return "FUNNY_QUOTE", "humor"
        if analysis.get("surprise_score", 0) >= analysis.get("emotion_score", 0):
            return "SURPRISE", "surprise"
        return "REACTION", "reaction"

    @staticmethod
    def _strongest_quote(text: str) -> str:
        sentences = [part.strip() for part in re.findall(r"[^.!?]+[.!?]?", text) if part.strip()]
        if not sentences:
            return text[:100]
        return max(
            sentences,
            key=lambda sentence: (
                any(token in sentence.lower() for token in ("finally", "never", "secret", "destroy", "insane", "no way")),
                5 <= len(sentence.split()) <= 16,
                len(sentence),
            ),
        )[:120]

    @classmethod
    def _quote_title_options(cls, context: dict[str, Any]) -> list[str]:
        quote = re.sub(r"\s+", " ", str(context.get("quote") or "")).strip(" .")
        if not quote:
            quote = "What Just Happened?"
        standalone = quote[:80]
        if standalone[-1:] not in "?!":
            standalone += "?" if standalone.lower().startswith(("can ", "could ", "do ", "did ", "is ", "are ", "what ", "why ", "how ")) else ""
        subject = cls._title_case_subject(context.get("subject") or "moment")
        return [
            standalone,
            f"We Somehow Ended Up Debating {subject}",
            f"This Conversation About {subject} Got Weird",
            f"I Was Not Ready for the {subject} Question",
            f"Chat Had Questions About {subject}",
        ]

    @staticmethod
    def _outcome(lowered: str, subject: str, clip_type: str) -> str:
        if "finally" in lowered:
            return f"the {subject} problem finally reached its payoff"
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
        }.get(clip_type, "the moment produced a payoff")

    @classmethod
    def _title_options(cls, context: dict[str, Any]) -> list[str]:
        subject = cls._title_case_subject(context["subject"])
        topic = context["topic"]
        clip_type = context["clip_type"]
        action = context["action"]
        if clip_type == "CHAOS" and context["subject"] == "sheep":
            return [
                "The Sheep Never Saw This Coming",
                "We Finally Declared War on the Sheep",
                "Our Colony Finally Snapped",
                "The Sheep Problem Is Officially Over",
                "This RimWorld Problem Required Violence",
            ]
        templates = {
            "CONFUSION": [
                f"{subject} Completely Broke My Brain",
                f"I Have No Explanation for the {subject} Situation",
                f"This {subject} Conversation Went Off the Rails",
                f"What Did I Just Say About {subject}?",
                f"The {subject} Moment That Made No Sense",
            ],
            "DISCOVERY": [
                f"I Was Not Supposed to Find This {subject}",
                f"The Hidden {subject} I Almost Missed",
                f"Finding This {subject} Changed the Entire Run",
                f"I Finally Found the {subject}",
                f"Nobody Warned Me About This {subject}",
            ],
            "FAIL": [
                f"The {subject} Plan Failed Immediately",
                f"This {subject} Mistake Cost Me Everything",
                f"I Knew the {subject} Plan Was a Bad Idea",
                f"Everything Fell Apart Because of {subject}",
                f"The Most Avoidable {subject} Fail",
            ],
            "VICTORY": [
                f"We Finally Beat the {subject}",
                f"The {subject} Victory We Actually Earned",
                f"This Changed the Entire {topic} Run",
                f"I Cannot Believe We Pulled This Off",
                f"The Exact Moment the Run Turned Around",
            ],
            "FUNNY_QUOTE": [
                f"The Funniest Thing Said About {subject}",
                f"Chat Lost It Over the {subject}",
                f"This {subject} Joke Got Better Every Second",
                f"The Timing on This {subject} Moment Was Perfect",
                f"I Could Not Stop Laughing at This",
            ],
            "SURPRISE": [
                f"The {subject} Caught Everyone Off Guard",
                f"This {subject} Moment Escalated Instantly",
                f"Nobody Expected the {subject} to Do This",
                f"The Stream Took a Wild Turn Because of {subject}",
                f"That Was the Last Thing I Expected from {subject}",
            ],
            "REACTION": [
                f"My Reaction to the {subject} Says Everything",
                f"The {subject} Left Me Speechless",
                f"This {subject} Moment Caught Me Off Guard",
                f"The Exact Moment I Understood the {subject}",
                f"I Still Cannot Believe the {subject} Did This",
            ],
            "CHAOS": [
                f"We Finally Chose Violence Against the {subject}",
                f"The {subject} Became Public Enemy Number One",
                f"This {subject} Problem Got Completely Out of Control",
                f"Our Only Solution Was to {action.title()} the {subject}",
                f"The {subject} Had No Idea What Was Coming",
            ],
            "ACCIDENT": [
                f"The {subject} Accident That Changed Everything",
                f"I Did Not Mean to Do This to the {subject}",
                f"One Mistake Created Total {subject} Chaos",
                f"This Was Definitely Not the Plan",
                f"The Accidental {subject} Moment I Cannot Explain",
            ],
        }
        return templates.get(clip_type, templates["REACTION"])

    def _deduplicate_titles(self, candidates: list[str], clip_id: int) -> list[str]:
        history = self.db.frame(
            "SELECT title FROM creator_package_history WHERE clip_candidate_id<>?",
            (int(clip_id),),
        )
        existing = [str(value) for value in history.get("title", [])]
        accepted: list[str] = []
        for candidate in candidates:
            if all(self._similarity(candidate, old) < 0.85 for old in existing + accepted):
                accepted.append(candidate)
        for candidate in candidates:
            if candidate not in accepted:
                accepted.append(candidate)
        return accepted

    @staticmethod
    def _similarity(left: str, right: str) -> float:
        return SequenceMatcher(None, left.lower().strip(), right.lower().strip()).ratio()

    @classmethod
    def _social_caption(cls, context: dict[str, Any]) -> tuple[str, str]:
        subject = context["subject"]
        clip_type = context["clip_type"]
        captions = {
            "CHAOS": f"The {subject} situation finally reached its breaking point 😂 Did we go too far?",
            "CONFUSION": f"I still have no idea what was happening with the {subject} here 😂 What did you hear?",
            "DISCOVERY": f"I almost walked right past this {subject}. Would you have noticed it?",
            "FAIL": f"The {subject} plan failed exactly how you would expect. Would you have tried it anyway?",
            "VICTORY": f"We finally pulled off the {subject} win. Was the payoff worth it?",
            "FUNNY_QUOTE": f"The {subject} timing absolutely destroyed me 😂 Who else would have lost it?",
            "SURPRISE": f"The {subject} escalated much faster than expected. Did you see that coming?",
            "ACCIDENT": f"The {subject} accident was definitely not part of the plan. What would you have done?",
            "REACTION": f"My reaction to the {subject} says everything. How would you have reacted?",
        }
        return captions.get(clip_type, captions["REACTION"]), "clip-specific-engagement"

    @classmethod
    def _hook_line(cls, context: dict[str, Any]) -> str:
        subject = context["subject"]
        return {
            "CHAOS": f"The {subject} had absolutely no idea what we were planning.",
            "CONFUSION": f"The {subject} made this conversation stop making sense.",
            "DISCOVERY": f"I nearly missed the most important {subject} in the run.",
            "FAIL": f"The {subject} plan gets worse every second.",
            "VICTORY": f"This was the moment the {subject} run finally paid off.",
            "FUNNY_QUOTE": f"One line about the {subject} broke the entire stream.",
            "SURPRISE": f"Nobody expected the {subject} to become the problem.",
            "ACCIDENT": f"One accidental {subject} decision changed everything.",
            "REACTION": f"Watch the exact moment I realize what the {subject} means.",
        }.get(context["clip_type"], f"The {subject} changed everything.")

    @staticmethod
    def _contextual_hashtags(context: dict[str, Any]) -> list[str]:
        topic_tags = {
            "Minecraft": ["#Minecraft", "#MinecraftShorts", "#MinecraftFunny"],
            "Escape from Tarkov": ["#EscapeFromTarkov", "#Tarkov", "#TarkovMoments"],
            "RimWorld": ["#RimWorld", "#RimWorldStories", "#ColonySim"],
            "Pokémon": ["#Pokemon", "#PokemonGaming", "#PokemonMoments"],
            "Project Zomboid": ["#ProjectZomboid", "#ZombieSurvival", "#ZomboidMoments"],
        }
        type_tags = {
            "CHAOS": "#GamingChaos", "CONFUSION": "#FunnyMoments",
            "DISCOVERY": "#HiddenDetails", "FAIL": "#GamingFails",
            "VICTORY": "#GamingWins", "FUNNY_QUOTE": "#GamingComedy",
            "SURPRISE": "#Unexpected", "ACCIDENT": "#GamingMistakes",
            "REACTION": "#StreamerReaction",
        }
        tags = topic_tags.get(context["topic"], ["#Gaming", "#GamingClips"])
        tags += [type_tags.get(context["clip_type"], "#StreamerMoments"), "#TwitchClips", "#GamingShorts"]
        return list(dict.fromkeys(tags))[:8]

    @staticmethod
    def _packaging_reasoning(text: str, analysis: dict[str, Any], context: dict[str, Any]) -> list[str]:
        reasons = [
            f"Detected a {context['clip_type'].lower().replace('_', ' ')} moment centered on {context['subject']}.",
            f"The key action is '{context['action']}' and {context['outcome']}.",
        ]
        confidence = context.get("confidence", {})
        reasons.append(
            f"Event confidence is {float(confidence.get('event', 0)):.0%} using "
            f"{context.get('context_segment_count', 1)} surrounding transcript segment(s)."
        )
        if context.get("fallback_mode") == "quote":
            reasons.append("Event confidence was below 60%, so titles use the strongest standalone quote.")
        if context["quote"]:
            reasons.append(f"The strongest standalone quote is: “{context['quote']}”.")
        if analysis["hook_score"] >= 50:
            reasons.append("The opening creates enough curiosity to stop a scroll.")
        if len(text.split()) <= 70:
            reasons.append("The moment is compact enough for short-form pacing.")
        reasons.append("The caption references the actual event and asks a direct question.")
        return reasons

    @staticmethod
    def _title_case_subject(subject: str) -> str:
        special = {"pokemon": "Pokémon", "pokémon": "Pokémon"}
        return special.get(subject, subject.title())
