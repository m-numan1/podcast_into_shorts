'use client';

import React, { useState, useMemo } from 'react';
import {
  Flame,
  Clock,
  ArrowUpDown,
  Sparkles,
  Layers,
  Filter,
  CheckCircle2,
  Share2,
} from 'lucide-react';
import { ClipItem, AspectRatio, SubtitlePresetId } from '@/types/api';
import { ViralClipCard } from './ViralClipCard';

interface ViralClipsFeedProps {
  clips: ClipItem[];
  sourceMedia: string;
  defaultAspectRatio?: AspectRatio;
  defaultSubtitlePreset?: SubtitlePresetId;
  episodeTitle?: string;
  onUpdateClip: (updatedClip: ClipItem) => void;
}

type SortOption = 'virality' | 'duration' | 'chronological';

export const ViralClipsFeed: React.FC<ViralClipsFeedProps> = ({
  clips,
  sourceMedia,
  defaultAspectRatio = '9:16',
  defaultSubtitlePreset = 'hormozi',
  episodeTitle,
  onUpdateClip,
}) => {
  const [sortBy, setSortBy] = useState<SortOption>('virality');
  const [activeScoreFilter, setActiveScoreFilter] = useState<'all' | 'high' | 'medium'>('all');

  // Render a specific card on demand
  const handleRenderClip = async (clip: ClipItem, ratio: AspectRatio, preset: SubtitlePresetId) => {
    try {
      const res = await fetch('/api/render-card', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          source: sourceMedia,
          clip,
          aspect_ratio: ratio,
          subtitle_preset: preset,
        }),
      });

      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.error || 'Failed to render clip');
      }

      if (data.clip) {
        onUpdateClip(data.clip);
      }
    } catch (err: any) {
      alert(`Render error: ${err.message}`);
    }
  };

  // Sort and filter logic
  const sortedClips = useMemo(() => {
    let result = [...clips];

    // Filter
    if (activeScoreFilter === 'high') {
      result = result.filter((c) => {
        const score = c.virality_score <= 10 ? c.virality_score * 10 : c.virality_score;
        return score >= 90;
      });
    } else if (activeScoreFilter === 'medium') {
      result = result.filter((c) => {
        const score = c.virality_score <= 10 ? c.virality_score * 10 : c.virality_score;
        return score >= 75 && score < 90;
      });
    }

    // Sort
    result.sort((a, b) => {
      if (sortBy === 'virality') {
        return (b.virality_score || b.overall_score) - (a.virality_score || a.overall_score);
      }
      if (sortBy === 'duration') {
        return b.duration_seconds - a.duration_seconds;
      }
      if (sortBy === 'chronological') {
        return a.rank - b.rank;
      }
      return 0;
    });

    return result;
  }, [clips, sortBy, activeScoreFilter]);

  // Calculate episode summary metrics
  const totalDurationSecs = useMemo(() => {
    return clips.reduce((acc, c) => acc + (c.duration_seconds || 0), 0);
  }, [clips]);

  const topViralityScore = useMemo(() => {
    if (clips.length === 0) return 0;
    const maxScore = Math.max(...clips.map((c) => c.virality_score || c.overall_score || 0));
    return maxScore <= 10 ? Math.round(maxScore * 10) : Math.round(maxScore);
  }, [clips]);

  return (
    <div className="w-full space-y-6 pt-4">
      {/* Metrics Summary Bar */}
      <div className="rounded-3xl p-5 sm:p-6 bg-gradient-to-r from-[#101526]/90 via-[#0D1220]/90 to-[#12182B]/90 border border-white/[0.08] shadow-2xl backdrop-blur-2xl flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <div className="flex items-center space-x-2">
            <span className="px-2.5 py-0.5 rounded-full text-xs font-black bg-gradient-to-r from-indigo-500 to-purple-600 text-white shadow-sm font-mono">
              {clips.length} Viral Clips
            </span>
            <span className="text-xs text-emerald-400 font-semibold flex items-center space-x-1">
              <Sparkles className="w-3.5 h-3.5 inline mr-1" />
              Peak Virality: {topViralityScore}/100
            </span>
          </div>

          <h2 className="text-xl sm:text-2xl font-black text-white mt-1">
            {episodeTitle ? episodeTitle : `${clips.length} Viral Clips Detected from Episode`}
          </h2>
          <p className="text-xs text-gray-400 mt-0.5">
            Total short-form content extracted: {Math.round(totalDurationSecs)} seconds across {clips.length} high-engagement segments.
          </p>
        </div>

        {/* Filter and Sort Controls */}
        <div className="flex flex-wrap items-center gap-2">
          {/* Virality Score Filter Buttons */}
          <div className="flex items-center space-x-1 bg-black/40 p-1 rounded-2xl border border-white/[0.06]">
            <button
              onClick={() => setActiveScoreFilter('all')}
              className={`px-3 py-1.5 rounded-xl text-xs font-semibold transition-all ${
                activeScoreFilter === 'all'
                  ? 'bg-indigo-600 text-white shadow-sm'
                  : 'text-gray-400 hover:text-white'
              }`}
            >
              All ({clips.length})
            </button>
            <button
              onClick={() => setActiveScoreFilter('high')}
              className={`px-3 py-1.5 rounded-xl text-xs font-semibold transition-all flex items-center space-x-1 ${
                activeScoreFilter === 'high'
                  ? 'bg-emerald-600 text-white shadow-sm'
                  : 'text-emerald-400/80 hover:text-emerald-300'
              }`}
            >
              <span>🔥 90+ Score</span>
            </button>
          </div>

          {/* Sort Dropdown */}
          <div className="flex items-center space-x-1 bg-black/40 p-1 rounded-2xl border border-white/[0.06]">
            {[
              { id: 'virality', label: 'Virality' },
              { id: 'duration', label: 'Duration' },
              { id: 'chronological', label: 'Chronological' },
            ].map((sort) => (
              <button
                key={sort.id}
                onClick={() => setSortBy(sort.id as SortOption)}
                className={`px-3 py-1.5 rounded-xl text-xs font-semibold transition-all ${
                  sortBy === sort.id
                    ? 'bg-indigo-600 text-white shadow-sm'
                    : 'text-gray-400 hover:text-white'
                }`}
              >
                {sort.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Grid of Viral Clips */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        {sortedClips.map((clip) => (
          <ViralClipCard
            key={clip.rank}
            clip={clip}
            sourceMedia={sourceMedia}
            defaultAspectRatio={defaultAspectRatio}
            defaultSubtitlePreset={defaultSubtitlePreset}
            onRenderClip={handleRenderClip}
          />
        ))}
      </div>
    </div>
  );
};
