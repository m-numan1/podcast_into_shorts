import os
from pathlib import Path
from pydantic import BaseModel, Field
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

class Settings(BaseModel):
    # App General Config
    app_name: str = "AI Video Editor for Podcasters"
    env: str = Field(default_factory=lambda: os.getenv("ENV", "development"))
    output_dir: Path = Field(default_factory=lambda: BASE_DIR / "outputs")
    cache_dir: Path = Field(default_factory=lambda: BASE_DIR / "cache")
    
    # LLM Settings
    openai_api_key: str = Field(default_factory=lambda: os.getenv("OPENAI_API_KEY", ""))
    gemini_api_key: str = Field(default_factory=lambda: os.getenv("GEMINI_API_KEY", ""))
    default_llm_provider: str = Field(default_factory=lambda: os.getenv("DEFAULT_LLM_PROVIDER", "mock"))
    default_model: str = Field(default_factory=lambda: os.getenv("DEFAULT_MODEL", "gpt-4o"))
    
    # Embedding Settings (use 384 for mock/offline mode; change to 1536 for OpenAI text-embedding-3-small)
    embedding_model: str = "text-embedding-3-small"
    embedding_dim: int = 384
    
    # Editor Criteria Constraints
    target_clip_count_min: int = 5
    target_clip_count_max: int = 20
    min_clip_duration_sec: float = 15.0
    max_clip_duration_sec: float = 90.0
    optimal_clip_duration_sec: float = 45.0
    
    def ensure_directories(self):
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

settings = Settings()
settings.ensure_directories()
