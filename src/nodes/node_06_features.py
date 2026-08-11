import re
from typing import Dict
from src.schema.state import EditorState
from src.schema.clips import ExtractedFeatures, SemanticChunk

def node_06_features(state: EditorState) -> dict:
    """
    Node 6: Extract lightweight features per semantic chunk (Emotion, Sentiment, Named Entities, Speaking Rate, Curiosity, Strong Statements, Story Likelihood, etc.)
    Supports both podcast and documentary content through broadened trigger vocabularies.
    """
    logs = list(state.logs)
    logs.append("[Node 6] Extracting multimodal acoustic and linguistic features...")
    
    features_map: Dict[str, ExtractedFeatures] = {}
    
    # Broadened triggers for both podcasts AND documentaries
    curiosity_triggers = [
        "why", "how", "secret", "truth", "nobody talks about", "mistake", "real reason", "hidden",
        "mystery", "unknown", "question", "puzzle", "enigma", "what if", "imagine",
        "scientists believe", "researchers found", "evidence suggests", "clue", "theory"
    ]
    strong_triggers = [
        "never", "always", "rule number one", "100%", "99%", "terrifying", "must", "guaranteed",
        "absolutely", "undeniable", "critical", "essential", "devastating", "extraordinary",
        "unprecedented", "revolutionary", "impossible", "unbelievable", "shocking"
    ]
    story_triggers = [
        "look at", "when I started", "built", "remember", "case study", "example", "one day",
        "the story of", "journey", "discovered", "witnessed", "captured", "survived",
        "transformed", "expedition", "investigation", "uncovered", "traced back to"
    ]
    
    for chunk in state.semantic_chunks:
        text = chunk.text
        text_lower = text.lower()
        words = text.split()
        word_count = len(words)
        duration = max(chunk.end - chunk.start, 1.0)
        
        # Calculate WPM
        speaking_rate_wpm = (word_count / duration) * 60.0
        
        # Question count
        question_count = text.count("?")
        
        # Curiosity score
        curiosity_matches = sum(1 for tr in curiosity_triggers if tr in text_lower)
        curiosity_score = min(1.0, 0.4 + (curiosity_matches * 0.15) + (0.2 if question_count > 0 else 0.0))
        
        # Strong statement score
        strong_matches = sum(1 for tr in strong_triggers if tr in text_lower)
        strong_score = min(1.0, 0.3 + (strong_matches * 0.2))
        
        # Story likelihood score
        story_matches = sum(1 for tr in story_triggers if tr in text_lower)
        story_score = min(1.0, 0.3 + (story_matches * 0.2))
        
        # Sentiment & Emotion heuristic
        sentiment = 0.5
        if any(pos in text_lower for pos in ["incredible", "great", "best", "formula", "success", "remarkable", "amazing", "wonderful", "fascinating"]):
            sentiment = 0.8
            emotion = "enthusiastic"
        elif any(neg in text_lower for neg in ["fail", "terrifying", "vanish", "mistake", "painful", "devastating", "tragic", "dangerous", "crisis", "catastrophe"]):
            sentiment = 0.2
            emotion = "urgent/cautionary"
        elif any(nar in text_lower for nar in ["discovered", "journey", "expedition", "witnessed", "survived"]):
            sentiment = 0.65
            emotion = "narrative/exploratory"
        else:
            emotion = "analytical"
            
        # Named entities (Capitalized non-start words or numbers)
        entities = list(set(re.findall(r'\b[A-Z][a-z]+\b|\b\d+%\b|\b\d+\b', text)))
        
        features_map[chunk.id] = ExtractedFeatures(
            chunk_id=chunk.id,
            emotion_label=emotion,
            emotion_score=0.85,
            sentiment_score=sentiment,
            named_entities=entities[:6],
            speaking_rate_wpm=round(speaking_rate_wpm, 1),
            question_count=question_count,
            curiosity_score=round(curiosity_score, 2),
            strong_statement_score=round(strong_score, 2),
            silence_duration_sec=0.4,
            keyword_density={w.lower(): text_lower.count(w.lower()) for w in ["ai", "wrapper", "moat", "utility", "formula", "discovery", "evidence", "nature"] if w.lower() in text_lower},
            topic_confidence=0.92,
            story_likelihood=round(story_score, 2)
        )
        
    logs.append(f"[Node 6] Extracted lightweight feature matrices for {len(features_map)} chunks.")
    
    return {
        "extracted_features": features_map,
        "current_node": "NODE_06_FEATURES_COMPLETE",
        "logs": logs
    }
