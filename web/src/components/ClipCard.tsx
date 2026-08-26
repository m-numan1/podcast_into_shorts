'use client';

import React, { useState } from 'react';
import { ClipItem } from '@/types/api';

interface ClipCardProps {
  clip: ClipItem;
  aspectRatio?: string;
  onOpenScoreDetails?: (clip: ClipItem) => void;
}

export const ClipCard: React.FC<ClipCardProps> = ({ clip, aspectRatio = '9:16', onOpenScoreDetails }) => {
  const [isPlaying, setIsPlaying] = useState<boolean>(false);

  // Extract video URL if rendered
  let videoUrl = '';
  let filename = '';
  if (clip.rendered_file_path) {
    const parts = clip.rendered_file_path.split(/[\\/]/);
    filename = parts[parts.length - 1];
    if (filename) {
      videoUrl = `/renders/${encodeURIComponent(filename)}`;
    }
  }

  // Score color helper
  const getScoreBadge = (score: number) => {
    if (score >= 8.0) return 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40';
    if (score >= 6.0) return 'bg-indigo-500/20 text-indigo-300 border-indigo-500/40';
    return 'bg-amber-500/20 text-amber-300 border-amber-500/40';
  };

  return (
    <div className="glass-panel-interactive rounded-2xl p-5 border border-white/10 relative overflow-hidden flex flex-col justify-between space-y-4">
      {/* Top Header: Rank & Title */}
      <div className="flex items-start justify-between space-x-3">
        <div className="space-y-1 pr-12">
          <div className="flex items-center space-x-2">
            <span className="px-2.5 py-0.5 rounded-full text-xs font-bold bg-indigo-600 text-white shadow-md shadow-indigo-600/30">
              #{clip.rank}
            </span>
            <span className="text-xs text-amber-400 font-mono font-semibold">
              {clip.start_timestamp} - {clip.end_timestamp} ({clip.duration_seconds.toFixed(1)}s)
            </span>
          </div>
          <h3 className="text-base font-bold text-white leading-snug line-clamp-2">
            {clip.title}
          </h3>
        </div>

        {/* Overall Score Badge */}
        <div className={`absolute top-4 right-4 px-2.5 py-1 rounded-xl border font-mono text-xs font-bold ${getScoreBadge(clip.overall_score)}`}>
          {clip.overall_score.toFixed(1)} <span className="text-[10px] opacity-75">/ 10</span>
        </div>
      </div>

      {/* Hook Quote Box */}
      {clip.hook && (
        <div className="p-3 rounded-xl bg-indigo-500/10 border-l-4 border-indigo-500 text-indigo-200 text-xs italic">
          <strong className="not-italic font-semibold text-indigo-400 block mb-0.5">Hook Opening:</strong>
          &ldquo;{clip.hook}&rdquo;
        </div>
      )}

      {/* Video Player Section (if rendered) */}
      {videoUrl ? (
        <div className="relative rounded-xl overflow-hidden bg-black border border-slate-800 shadow-inner group">
          <video
            controls
            preload="metadata"
            src={videoUrl}
            onPlay={() => setIsPlaying(true)}
            onPause={() => setIsPlaying(false)}
            className={`w-full bg-black rounded-xl object-contain ${
              aspectRatio === '9:16' ? 'max-h-[360px] aspect-[9/16]' : aspectRatio === '1:1' ? 'max-h-[300px] aspect-square' : 'max-h-[240px] aspect-video'
            }`}
          />

          <div className="p-2 bg-slate-900/90 border-t border-slate-800 flex items-center justify-between">
            <span className="text-[11px] text-gray-400 font-mono truncate max-w-[200px]" title={filename}>
              {filename}
            </span>
            <a
              href={videoUrl}
              download={filename}
              className="px-3 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white font-semibold text-xs transition-all flex items-center space-x-1.5 shadow-md shadow-emerald-600/20"
            >
              <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
              </svg>
              <span>Download MP4</span>
            </a>
          </div>
        </div>
      ) : (
        <div className="p-4 rounded-xl bg-slate-900/60 border border-slate-800/80 text-center text-xs text-gray-400">
          Video not re-encoded yet. Click &ldquo;Render All Shorts&rdquo; to cut & generate MP4.
        </div>
      )}

      {/* Metrics Row */}
      <div className="grid grid-cols-3 gap-2 py-1">
        <div className="p-2 rounded-xl bg-slate-900/50 border border-slate-800 text-center">
          <div className="text-[10px] text-gray-400 uppercase font-semibold">Virality</div>
          <div className="text-xs font-bold text-cyan-400 font-mono">{clip.virality_score.toFixed(1)} / 10</div>
        </div>
        <div className="p-2 rounded-xl bg-slate-900/50 border border-slate-800 text-center">
          <div className="text-[10px] text-gray-400 uppercase font-semibold">Confidence</div>
          <div className="text-xs font-bold text-indigo-400 font-mono">{clip.confidence_score.toFixed(1)} / 10</div>
        </div>
        <div className="p-2 rounded-xl bg-slate-900/50 border border-slate-800 text-center">
          <div className="text-[10px] text-gray-400 uppercase font-semibold">Retention</div>
          <div className="text-xs font-bold text-emerald-400 font-mono truncate">{clip.viewer_retention_prediction || 'High'}</div>
        </div>
      </div>

      {/* Summary & Reasoning Footer */}
      <div className="text-xs text-gray-300 space-y-1 pt-1 border-t border-slate-800/80">
        <p className="line-clamp-2"><strong className="text-white">Summary:</strong> {clip.one_sentence_summary}</p>
        {clip.why_this_clip_was_selected && (
          <p className="text-gray-400 line-clamp-2"><strong className="text-gray-300">Why selected:</strong> {clip.why_this_clip_was_selected}</p>
        )}
      </div>

      {/* Suggested Hashtags */}
      {clip.suggested_hashtags && clip.suggested_hashtags.length > 0 && (
        <div className="flex flex-wrap gap-1 pt-1">
          {clip.suggested_hashtags.map((tag, idx) => (
            <span key={idx} className="px-2 py-0.5 rounded-md bg-slate-800/90 text-indigo-300 text-[10px] border border-slate-700">
              {tag.startsWith('#') ? tag : `#${tag}`}
            </span>
          ))}
        </div>
      )}
    </div>
  );
};
