export interface ClipItem {
  rank: number;
  title: string;
  start_timestamp: string;
  end_timestamp: string;
  duration_seconds: number;
  hook?: string;
  overall_score: number;
  virality_score: number;
  confidence_score: number;
  viewer_retention_prediction: string;
  start_adjustment_sec: number;
  end_adjustment_sec: number;
  one_sentence_summary: string;
  why_this_clip_was_selected?: string;
  suggested_hashtags?: string[];
  rendered_file_path?: string;
}

export interface ProvenanceInfo {
  scoring_mode: 'llm' | 'heuristic';
  embedding_backend?: string;
  is_synthetic?: boolean;
}

export interface JobStatusResponse {
  job_id?: string;
  status: 'running' | 'done' | 'error';
  logs?: string[];
  warnings?: string[];
  failed_stage?: string;
  error?: string;
  clips?: ClipItem[];
  is_synthetic?: boolean;
  provenance?: ProvenanceInfo;
  source?: string;
  media_file_path?: string;
  title?: string;
}

export interface AnalyzePayload {
  source: string;
  demo?: boolean;
  render?: boolean;
  aspect_ratio: '9:16' | '1:1' | '16:9';
  enable_hook_banner: boolean;
}

export interface TrimPayload {
  source: string;
  clips: ClipItem[];
  fast: boolean;
  aspect_ratio: '9:16' | '1:1' | '16:9';
  enable_hook_banner: boolean;
}
