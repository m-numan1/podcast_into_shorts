'use client';

import React, { useState, useRef, useEffect } from 'react';
import {
  Play,
  Pause,
  Volume2,
  VolumeX,
  Maximize2,
  Download,
  Sparkles,
  Share2,
  Copy,
  Check,
  Flame,
  Zap,
  Film,
  Layers,
  Palette,
  Clock,
  TrendingUp,
  RefreshCw,
  Sliders,
} from 'lucide-react';
import { ClipItem, AspectRatio, SubtitlePresetId } from '@/types/api';

interface ViralClipCardProps {
  clip: ClipItem;
  sourceMedia: string;
  defaultAspectRatio?: AspectRatio;
  defaultSubtitlePreset?: SubtitlePresetId;
  onRenderClip: (clip: ClipItem, ratio: AspectRatio, preset: SubtitlePresetId) => Promise<void>;
}

const PRESET_OPTIONS: { id: SubtitlePresetId; name: string; icon: string }[] = [
  { id: 'hormozi', name: 'Hormozi Bold', icon: '⚡' },
  { id: 'capcut', name: 'CapCut Neon', icon: '✨' },
  { id: 'mrbeast', name: 'MrBeast Punch', icon: '🔥' },
  { id: 'single_word', name: 'Single Word', icon: '🎯' },
  { id: 'minimal', name: 'Clean Minimal', icon: '🕊️' },
];

export const ViralClipCard: React.FC<ViralClipCardProps> = ({
  clip,
  sourceMedia,
  defaultAspectRatio = '9:16',
  defaultSubtitlePreset = 'hormozi',
  onRenderClip,
}) => {
  const [isPlaying, setIsPlaying] = useState<boolean>(false);
  const [isMuted, setIsMuted] = useState<boolean>(false);
  const [currentTime, setCurrentTime] = useState<number>(0);
  const [duration, setDuration] = useState<number>(0);
  const [selectedRatio, setSelectedRatio] = useState<AspectRatio>(defaultAspectRatio);
  const [selectedPreset, setSelectedPreset] = useState<SubtitlePresetId>(defaultSubtitlePreset);
  const [copiedCaption, setCopiedCaption] = useState<boolean>(false);
  const [copiedHashtag, setCopiedHashtag] = useState<string | null>(null);
  const [isRendering, setIsRendering] = useState<boolean>(false);
  const [isPresetDropdownOpen, setIsPresetDropdownOpen] = useState<boolean>(false);

  const videoRef = useRef<HTMLVideoElement>(null);

  // Derive video URL if rendered
  let videoUrl = '';
  let filename = '';
  if (clip.rendered_file_path) {
    const parts = clip.rendered_file_path.split(/[\\/]/);
    filename = parts[parts.length - 1];
    if (filename) {
      videoUrl = `/renders/${encodeURIComponent(filename)}`;
    }
  }

  // Virality score badge helper
  const getViralityBadge = (score: number) => {
    // Score can be on 0-10 or 0-100 scale
    const normalized = score <= 10 ? Math.round(score * 10) : Math.round(score);
    if (normalized >= 90) {
      return {
        score: normalized,
        text: 'High Viral Potential',
        icon: '🔥',
        classes: 'bg-emerald-500/15 border-emerald-500/40 text-emerald-300 shadow-emerald-500/10',
        dot: 'bg-emerald-400',
      };
    }
    if (normalized >= 75) {
      return {
        score: normalized,
        text: 'Good Reach',
        icon: '⚡',
        classes: 'bg-indigo-500/15 border-indigo-500/40 text-indigo-300 shadow-indigo-500/10',
        dot: 'bg-indigo-400',
      };
    }
    return {
      score: normalized,
      text: 'Moderate Hook',
      icon: '📊',
      classes: 'bg-slate-700/30 border-slate-600/40 text-slate-300 shadow-slate-500/10',
      dot: 'bg-slate-400',
    };
  };

  const badgeInfo = getViralityBadge(clip.virality_score || clip.overall_score);

  // Handle Video Player Controls
  const togglePlay = () => {
    if (!videoRef.current) return;
    if (isPlaying) {
      videoRef.current.pause();
      setIsPlaying(false);
    } else {
      videoRef.current.play();
      setIsPlaying(true);
    }
  };

  const toggleMute = () => {
    if (!videoRef.current) return;
    videoRef.current.muted = !isMuted;
    setIsMuted(!isMuted);
  };

  const handleTimeUpdate = () => {
    if (videoRef.current) {
      setCurrentTime(videoRef.current.currentTime);
      setDuration(videoRef.current.duration || 0);
    }
  };

  const handleSeek = (e: React.ChangeEvent<HTMLInputElement>) => {
    const val = parseFloat(e.target.value);
    if (videoRef.current) {
      videoRef.current.currentTime = val;
      setCurrentTime(val);
    }
  };

  const formatTime = (secs: number) => {
    if (isNaN(secs)) return '0:00';
    const m = Math.floor(secs / 60);
    const s = Math.floor(secs % 60);
    return `${m}:${s < 10 ? '0' : ''}${s}`;
  };

  const handleFullscreen = () => {
    if (videoRef.current) {
      if (videoRef.current.requestFullscreen) {
        videoRef.current.requestFullscreen();
      }
    }
  };

  // Trigger on-demand rendering
  const handleTriggerRender = async () => {
    setIsRendering(true);
    try {
      await onRenderClip(clip, selectedRatio, selectedPreset);
    } finally {
      setIsRendering(false);
    }
  };

  // Copy Caption
  const copyCaption = () => {
    const textToCopy = `${clip.title}\n\n${clip.one_sentence_summary || ''}\n\n${(clip.suggested_hashtags || []).map(t => t.startsWith('#') ? t : `#${t}`).join(' ')}`;
    navigator.clipboard.writeText(textToCopy);
    setCopiedCaption(true);
    setTimeout(() => setCopiedCaption(false), 2000);
  };

  const copyHashtagPill = (tag: string) => {
    const clean = tag.startsWith('#') ? tag : `#${tag}`;
    navigator.clipboard.writeText(clean);
    setCopiedHashtag(clean);
    setTimeout(() => setCopiedHashtag(null), 1500);
  };

  return (
    <div className="rounded-3xl bg-[#0D1220]/90 border border-white/[0.08] p-5 sm:p-6 shadow-2xl backdrop-blur-xl flex flex-col justify-between space-y-5 hover:border-white/[0.15] transition-all group">
      {/* Top Header Row: Rank, Timestamps & Score Badge */}
      <div className="flex items-start justify-between gap-3">
        <div className="space-y-1.5 flex-1 min-w-0">
          <div className="flex items-center space-x-2">
            <span className="px-2.5 py-0.5 rounded-full text-xs font-black bg-gradient-to-r from-indigo-500 to-purple-600 text-white shadow-md shadow-indigo-500/20">
              #{clip.rank}
            </span>
            <span className="text-xs text-amber-400 font-mono font-semibold flex items-center space-x-1">
              <Clock className="w-3.5 h-3.5 inline mr-1 opacity-80" />
              {clip.start_timestamp} - {clip.end_timestamp} ({clip.duration_seconds.toFixed(1)}s)
            </span>
          </div>
          <h3 className="text-base sm:text-lg font-bold text-white leading-snug line-clamp-2 group-hover:text-indigo-200 transition-colors">
            {clip.title}
          </h3>
        </div>

        {/* Virality Score Badge */}
        <div
          className={`shrink-0 px-3 py-1.5 rounded-2xl border shadow-lg flex items-center space-x-2 ${badgeInfo.classes}`}
          title={`Virality Score: ${badgeInfo.score}/100`}
        >
          <span className="text-sm">{badgeInfo.icon}</span>
          <div>
            <div className="text-xs font-black font-mono leading-none">
              {badgeInfo.score} <span className="text-[10px] opacity-75 font-normal">/ 100</span>
            </div>
            <div className="text-[9px] font-semibold uppercase tracking-wider opacity-80 mt-0.5">
              {badgeInfo.text}
            </div>
          </div>
        </div>
      </div>

      {/* Video Preview Box (9:16 Vertical) */}
      <div className="relative w-full rounded-2xl overflow-hidden bg-black/80 border border-white/[0.08] shadow-inner flex flex-col items-center justify-center min-h-[360px]">
        {videoUrl ? (
          <div className="relative w-full h-full flex flex-col items-center justify-center group/player">
            <video
              ref={videoRef}
              src={videoUrl}
              onTimeUpdate={handleTimeUpdate}
              onEnded={() => setIsPlaying(false)}
              className={`w-full bg-black object-contain cursor-pointer ${
                selectedRatio === '9:16'
                  ? 'max-h-[420px] aspect-[9/16]'
                  : selectedRatio === '1:1'
                  ? 'max-h-[360px] aspect-square'
                  : 'max-h-[260px] aspect-video'
              }`}
              onClick={togglePlay}
            />

            {/* Custom Overlay Controls */}
            <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/90 via-black/50 to-transparent p-3 space-y-2 opacity-90 group-hover/player:opacity-100 transition-opacity">
              {/* Progress Slider */}
              <input
                type="range"
                min={0}
                max={duration || 100}
                step={0.1}
                value={currentTime}
                onChange={handleSeek}
                className="w-full h-1 bg-white/20 rounded-lg appearance-none cursor-pointer accent-indigo-500"
              />

              <div className="flex items-center justify-between text-xs text-white">
                <div className="flex items-center space-x-2">
                  <button onClick={togglePlay} className="p-1 rounded-md hover:bg-white/10 transition-colors">
                    {isPlaying ? <Pause className="w-4 h-4" /> : <Play className="w-4 h-4" />}
                  </button>
                  <button onClick={toggleMute} className="p-1 rounded-md hover:bg-white/10 transition-colors">
                    {isMuted ? <VolumeX className="w-4 h-4" /> : <Volume2 className="w-4 h-4" />}
                  </button>
                  <span className="font-mono text-[11px] text-gray-300">
                    {formatTime(currentTime)} / {formatTime(duration || clip.duration_seconds)}
                  </span>
                </div>

                <div className="flex items-center space-x-2">
                  <span className="text-[10px] font-mono uppercase px-1.5 py-0.5 rounded bg-white/10 text-gray-300">
                    {selectedRatio}
                  </span>
                  <button onClick={handleFullscreen} className="p-1 rounded-md hover:bg-white/10 transition-colors">
                    <Maximize2 className="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>
            </div>
          </div>
        ) : (
          /* Thumbnail / Hook Placeholder with On-Demand Render Trigger */
          <div className="w-full h-full min-h-[360px] p-6 flex flex-col items-center justify-between text-center bg-gradient-to-b from-[#141A2E] via-[#0E1322] to-[#0A0D17] relative">
            {/* Top Hook Overlay Badge */}
            <div className="w-full">
              <span className="inline-flex items-center space-x-1.5 px-3 py-1 rounded-full bg-indigo-500/20 border border-indigo-500/30 text-indigo-300 text-[11px] font-bold">
                <Sparkles className="w-3 h-3 text-indigo-400" />
                <span>Ready for Instant Subtitle Synthesis</span>
              </span>
            </div>

            {/* Middle: Hook Sentence in Big Quote */}
            <div className="max-w-xs my-auto space-y-2">
              <p className="text-white text-base font-extrabold italic leading-snug drop-shadow-md">
                &ldquo;{clip.hook || clip.title}&rdquo;
              </p>
              <p className="text-xs text-gray-400">
                AI identified this moment as having peak audience emotional resonance.
              </p>
            </div>

            {/* Instant Render & Preview Trigger */}
            <div className="w-full pt-4">
              <button
                type="button"
                onClick={handleTriggerRender}
                disabled={isRendering}
                className="w-full py-3 px-5 rounded-xl bg-gradient-to-r from-indigo-500 via-purple-600 to-pink-500 text-white font-bold text-xs shadow-lg shadow-indigo-500/20 hover:shadow-indigo-500/40 hover:scale-[1.01] active:scale-[0.99] transition-all flex items-center justify-center space-x-2 disabled:opacity-50"
              >
                {isRendering ? (
                  <>
                    <RefreshCw className="w-4 h-4 animate-spin text-white" />
                    <span>Rendering MP4 with FFmpeg...</span>
                  </>
                ) : (
                  <>
                    <Zap className="w-4 h-4 text-amber-300 fill-amber-300" />
                    <span>⚡ Render & Preview MP4</span>
                  </>
                )}
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Editorial AI Insights */}
      <div className="space-y-2.5">
        {/* Hook opening */}
        {clip.hook && (
          <div className="p-3 rounded-2xl bg-indigo-500/10 border-l-4 border-indigo-500 text-indigo-200 text-xs italic">
            <strong className="not-italic font-bold text-indigo-300 block mb-0.5">🔥 Hook Statement:</strong>
            &ldquo;{clip.hook}&rdquo;
          </div>
        )}

        {/* Why it went viral & Retention */}
        <div className="p-3 rounded-2xl bg-white/[0.02] border border-white/[0.06] space-y-1.5 text-xs text-gray-300">
          <div className="flex items-center justify-between">
            <span className="font-semibold text-white flex items-center space-x-1.5">
              <TrendingUp className="w-3.5 h-3.5 text-emerald-400" />
              <span>Why It Went Viral:</span>
            </span>
            <span className="px-2 py-0.5 rounded-md bg-emerald-500/20 text-emerald-300 text-[10px] font-mono font-bold">
              {clip.viewer_retention_prediction || 'High 70%+ Watch-through'}
            </span>
          </div>
          <p className="text-gray-400 text-[11px] leading-relaxed">
            {clip.why_this_clip_was_selected || clip.one_sentence_summary || 'Strong emotional polarity and educational takeaway in the first 3 seconds.'}
          </p>
        </div>
      </div>

      {/* Social Caption & Hashtags Drawer */}
      <div className="rounded-2xl bg-white/[0.02] border border-white/[0.06] p-3 space-y-2 text-xs">
        <div className="flex items-center justify-between">
          <span className="font-semibold text-white text-[11px] flex items-center space-x-1">
            <Share2 className="w-3 h-3 text-indigo-400" />
            <span>AI Suggested Caption:</span>
          </span>
          <button
            onClick={copyCaption}
            className="text-[10px] font-semibold text-indigo-300 hover:text-white flex items-center space-x-1 p-1 rounded hover:bg-white/[0.04] transition-colors"
          >
            {copiedCaption ? <Check className="w-3 h-3 text-emerald-400" /> : <Copy className="w-3 h-3" />}
            <span>{copiedCaption ? 'Copied!' : 'Copy Caption'}</span>
          </button>
        </div>

        <p className="text-[11px] text-gray-400 line-clamp-2">
          {clip.one_sentence_summary || clip.title}
        </p>

        {/* Copyable Hashtags Pills */}
        {clip.suggested_hashtags && clip.suggested_hashtags.length > 0 && (
          <div className="flex flex-wrap gap-1.5 pt-1">
            {clip.suggested_hashtags.map((tag, idx) => {
              const clean = tag.startsWith('#') ? tag : `#${tag}`;
              const isCopied = copiedHashtag === clean;
              return (
                <button
                  key={idx}
                  onClick={() => copyHashtagPill(tag)}
                  className={`px-2 py-0.5 rounded-lg text-[10px] font-mono transition-all flex items-center space-x-1 border ${
                    isCopied
                      ? 'bg-emerald-500/20 border-emerald-500 text-emerald-300'
                      : 'bg-white/[0.03] border-white/[0.08] text-indigo-300 hover:bg-white/[0.08] hover:text-white'
                  }`}
                  title="Click to copy hashtag"
                >
                  <span>{clean}</span>
                  {isCopied && <Check className="w-2.5 h-2.5 text-emerald-400" />}
                </button>
              );
            })}
          </div>
        )}
      </div>

      {/* Card Action Bar */}
      <div className="pt-2 border-t border-white/[0.08] space-y-3">
        {/* Aspect Ratio and Preset Options Bar */}
        <div className="flex flex-wrap items-center justify-between gap-2">
          {/* Format Quick Toggle */}
          <div className="flex items-center space-x-1 bg-black/40 p-1 rounded-xl border border-white/[0.06]">
            {(['9:16', '1:1', '16:9'] as AspectRatio[]).map((ratio) => (
              <button
                key={ratio}
                onClick={() => setSelectedRatio(ratio)}
                className={`px-2 py-1 rounded-lg text-[10px] font-bold transition-all ${
                  selectedRatio === ratio
                    ? 'bg-indigo-600 text-white shadow-sm'
                    : 'text-gray-400 hover:text-gray-200'
                }`}
              >
                {ratio}
              </button>
            ))}
          </div>

          {/* Subtitle Style Switcher Dropdown */}
          <div className="relative">
            <button
              onClick={() => setIsPresetDropdownOpen(!isPresetDropdownOpen)}
              className="px-2.5 py-1.5 rounded-xl bg-white/[0.04] hover:bg-white/[0.08] border border-white/[0.08] text-xs text-gray-300 hover:text-white transition-all flex items-center space-x-1.5"
            >
              <Palette className="w-3.5 h-3.5 text-indigo-400" />
              <span className="text-[11px] font-semibold">
                {PRESET_OPTIONS.find((p) => p.id === selectedPreset)?.name}
              </span>
            </button>

            {isPresetDropdownOpen && (
              <div className="absolute right-0 bottom-full mb-1 w-44 rounded-xl bg-[#141A2E] border border-white/[0.1] shadow-2xl p-1.5 z-30 space-y-1">
                {PRESET_OPTIONS.map((preset) => (
                  <button
                    key={preset.id}
                    onClick={() => {
                      setSelectedPreset(preset.id);
                      setIsPresetDropdownOpen(false);
                    }}
                    className={`w-full text-left px-2.5 py-1.5 rounded-lg text-xs flex items-center space-x-2 transition-all ${
                      selectedPreset === preset.id
                        ? 'bg-indigo-600 text-white font-bold'
                        : 'text-gray-300 hover:bg-white/[0.06]'
                    }`}
                  >
                    <span>{preset.icon}</span>
                    <span>{preset.name}</span>
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Primary Action Buttons */}
        <div className="flex items-center gap-2">
          {videoUrl ? (
            <>
              {/* Direct Download MP4 */}
              <a
                href={videoUrl}
                download={filename || `clip_${clip.rank}.mp4`}
                className="flex-1 py-2.5 px-4 rounded-xl bg-gradient-to-r from-emerald-600 to-emerald-500 hover:from-emerald-500 hover:to-emerald-400 text-white font-bold text-xs shadow-lg shadow-emerald-500/20 transition-all flex items-center justify-center space-x-1.5"
              >
                <Download className="w-4 h-4" />
                <span>⬇️ Download MP4</span>
              </a>

              {/* Re-render button */}
              <button
                type="button"
                onClick={handleTriggerRender}
                disabled={isRendering}
                className="py-2.5 px-3 rounded-xl bg-white/[0.04] hover:bg-white/[0.08] border border-white/[0.08] text-gray-300 hover:text-white text-xs font-semibold transition-all flex items-center space-x-1.5 disabled:opacity-50"
                title="Re-render with selected aspect ratio or subtitle preset"
              >
                <RefreshCw className={`w-3.5 h-3.5 ${isRendering ? 'animate-spin text-indigo-400' : ''}`} />
                <span>Re-render</span>
              </button>
            </>
          ) : (
            <button
              type="button"
              onClick={handleTriggerRender}
              disabled={isRendering}
              className="w-full py-2.5 px-4 rounded-xl bg-gradient-to-r from-indigo-600 via-purple-600 to-indigo-600 hover:opacity-95 text-white font-bold text-xs shadow-lg shadow-indigo-500/20 transition-all flex items-center justify-center space-x-2 disabled:opacity-50"
            >
              {isRendering ? (
                <>
                  <RefreshCw className="w-4 h-4 animate-spin" />
                  <span>Encoding MP4...</span>
                </>
              ) : (
                <>
                  <Film className="w-4 h-4" />
                  <span>🎬 Export Clip ({selectedRatio})</span>
                </>
              )}
            </button>
          )}
        </div>
      </div>
    </div>
  );
};
