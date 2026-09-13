'use client';

import React, { useState, useRef } from 'react';
import {
  Sparkles,
  Youtube,
  FileVideo,
  Music,
  UploadCloud,
  ChevronDown,
  CheckCircle2,
  Zap,
  Flame,
  Target,
  Feather,
  Sliders,
  Play,
  Film,
  Link as LinkIcon,
} from 'lucide-react';
import { AspectRatio, SubtitlePresetId, SubtitlePresetOption, AnalyzePayload } from '@/types/api';

const SUBTITLE_PRESETS: SubtitlePresetOption[] = [
  {
    id: 'hormozi',
    name: 'Hormozi Bold',
    tagline: 'Yellow Pop',
    icon: '⚡',
    badgeColor: 'from-amber-400 to-yellow-500 text-black',
    sampleStyle: 'bg-yellow-400 text-black font-black uppercase px-2 py-0.5 rounded shadow-lg',
  },
  {
    id: 'capcut',
    name: 'CapCut Neon',
    tagline: 'Cyan Glow',
    icon: '✨',
    badgeColor: 'from-cyan-400 to-blue-500 text-white',
    sampleStyle: 'bg-cyan-500/30 text-cyan-300 font-extrabold px-2 py-0.5 rounded border border-cyan-400 shadow-[0_0_12px_rgba(6,182,212,0.6)]',
  },
  {
    id: 'mrbeast',
    name: 'MrBeast Punch',
    tagline: 'Green Punch',
    icon: '🔥',
    badgeColor: 'from-emerald-400 to-green-500 text-black',
    sampleStyle: 'bg-emerald-400 text-black font-black uppercase px-2 py-0.5 rounded shadow-[0_0_10px_rgba(16,185,129,0.7)]',
  },
  {
    id: 'single_word',
    name: 'Single Word',
    tagline: 'Rapid Fire',
    icon: '🎯',
    badgeColor: 'from-indigo-400 to-purple-500 text-white',
    sampleStyle: 'bg-indigo-600 text-white font-black tracking-wider px-2 py-0.5 rounded scale-105 shadow-md',
  },
  {
    id: 'minimal',
    name: 'Clean Minimal',
    tagline: 'Subtle Bottom',
    icon: '🕊️',
    badgeColor: 'from-slate-300 to-gray-400 text-slate-900',
    sampleStyle: 'bg-black/60 text-white font-medium px-2 py-0.5 rounded text-[11px] border border-white/20',
  },
];

interface InputStudioProps {
  onStartAnalysis: (payload: AnalyzePayload) => void;
  isLoading: boolean;
}

export const InputStudio: React.FC<InputStudioProps> = ({ onStartAnalysis, isLoading }) => {
  const [source, setSource] = useState<string>('');
  const [aspectRatio, setAspectRatio] = useState<AspectRatio>('9:16');
  const [subtitlePreset, setSubtitlePreset] = useState<SubtitlePresetId>('hormozi');
  const [isAdvancedOpen, setIsAdvancedOpen] = useState<boolean>(false);
  const [isDragging, setIsDragging] = useState<boolean>(false);
  const [uploadedFileName, setUploadedFileName] = useState<string | null>(null);

  const fileInputRef = useRef<HTMLInputElement>(null);

  // Auto-detect URL or file type
  const detectSourceType = (input: string) => {
    const val = input.toLowerCase();
    if (val.includes('youtube.com') || val.includes('youtu.be')) return 'youtube';
    if (val.endsWith('.mp4') || val.endsWith('.mov') || val.endsWith('.mkv') || val.endsWith('.webm')) return 'video';
    if (val.endsWith('.mp3') || val.endsWith('.wav') || val.endsWith('.m4a')) return 'audio';
    if (val.startsWith('http://') || val.startsWith('https://')) return 'web-media';
    if (val.length > 0) return 'filepath';
    return null;
  };

  const sourceType = detectSourceType(source);

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  };

  const handleDragLeave = () => {
    setIsDragging(false);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      const file = e.dataTransfer.files[0];
      setUploadedFileName(file.name);
      setSource(file.name);
    }
  };

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      const file = e.target.files[0];
      setUploadedFileName(file.name);
      setSource(file.name);
    }
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!source.trim()) {
      alert('Please paste a YouTube or Podcast link, or drag-and-drop a media file.');
      return;
    }
    onStartAnalysis({
      source: source.trim(),
      aspect_ratio: aspectRatio,
      subtitle_preset: subtitlePreset,
    });
  };

  return (
    <div className="relative w-full rounded-3xl p-6 sm:p-8 bg-gradient-to-b from-[#101524]/90 to-[#0A0E17]/95 border border-white/[0.08] shadow-2xl backdrop-blur-2xl overflow-hidden">
      {/* Decorative ambient background glows */}
      <div className="absolute -top-32 -left-32 w-80 h-80 bg-indigo-600/15 rounded-full blur-[100px] pointer-events-none"></div>
      <div className="absolute -bottom-32 -right-32 w-80 h-80 bg-purple-600/15 rounded-full blur-[100px] pointer-events-none"></div>

      <form onSubmit={handleSubmit} className="relative z-10 space-y-6">
        {/* Card Header & Pitch */}
        <div className="text-center max-w-2xl mx-auto space-y-2">
          <div className="inline-flex items-center space-x-2 px-3 py-1 rounded-full bg-indigo-500/10 border border-indigo-500/20 text-indigo-300 text-xs font-semibold">
            <Sparkles className="w-3.5 h-3.5 text-indigo-400" />
            <span>AI-Powered Virality & Subtitle Synthesis</span>
          </div>
          <h2 className="text-2xl sm:text-3xl font-extrabold text-white tracking-tight">
            Turn 1-Hour Long Podcasts Into <span className="bg-gradient-to-r from-indigo-400 via-purple-400 to-pink-400 bg-clip-text text-transparent">Viral Shorts</span>
          </h2>
          <p className="text-xs sm:text-sm text-gray-400">
            Paste any episode link or upload audio/video. Our AI finds the strongest hooks, reframes to 9:16 vertical, and animates eye-catching captions.
          </p>
        </div>

        {/* Input Section */}
        <div className="space-y-4 max-w-2xl mx-auto">
          {/* Direct URL Input */}
          <div className="relative group">
            <div className="absolute inset-y-0 left-0 pl-4 flex items-center pointer-events-none">
              {sourceType === 'youtube' ? (
                <Youtube className="w-5 h-5 text-red-500" />
              ) : sourceType === 'video' ? (
                <FileVideo className="w-5 h-5 text-indigo-400" />
              ) : sourceType === 'audio' ? (
                <Music className="w-5 h-5 text-emerald-400" />
              ) : (
                <LinkIcon className="w-5 h-5 text-gray-400 group-focus-within:text-indigo-400 transition-colors" />
              )}
            </div>

            <input
              type="text"
              value={source}
              onChange={(e) => {
                setSource(e.target.value);
                setUploadedFileName(null);
              }}
              disabled={isLoading}
              placeholder="Paste YouTube URL, Spotify/Apple podcast, or local file path..."
              className="w-full pl-12 pr-28 py-4 bg-[#0F1424]/90 border border-white/[0.1] rounded-2xl text-white placeholder-gray-500 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500/50 focus:border-indigo-500/80 transition-all shadow-inner disabled:opacity-50"
            />

            {source && (
              <div className="absolute inset-y-0 right-3 flex items-center space-x-2">
                <span className="text-[10px] uppercase font-mono px-2 py-0.5 rounded-md bg-white/[0.06] border border-white/10 text-gray-300">
                  {sourceType || 'Detected'}
                </span>
                <button
                  type="button"
                  onClick={() => {
                    setSource('');
                    setUploadedFileName(null);
                  }}
                  className="text-gray-400 hover:text-white p-1 rounded-md text-xs"
                >
                  ✕
                </button>
              </div>
            )}
          </div>

          {/* OR Divider */}
          <div className="relative flex items-center justify-center">
            <div className="border-t border-white/[0.08] w-full"></div>
            <span className="bg-[#0D1220] px-3 text-[11px] font-semibold uppercase tracking-wider text-gray-500 relative">
              OR
            </span>
            <div className="border-t border-white/[0.08] w-full"></div>
          </div>

          {/* Drag and Drop Zone */}
          <div
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onDrop={handleDrop}
            onClick={() => fileInputRef.current?.click()}
            className={`cursor-pointer rounded-2xl border-2 border-dashed p-5 text-center transition-all ${
              isDragging
                ? 'border-indigo-500 bg-indigo-500/10 scale-[1.01]'
                : uploadedFileName
                ? 'border-emerald-500/50 bg-emerald-500/5'
                : 'border-white/[0.1] bg-[#0F1424]/40 hover:border-white/[0.2] hover:bg-[#0F1424]/70'
            }`}
          >
            <input
              ref={fileInputRef}
              type="file"
              accept=".mp4,.mov,.mp3,.wav,.mkv,.webm"
              onChange={handleFileSelect}
              className="hidden"
            />

            <div className="flex flex-col items-center justify-center space-y-2">
              <div
                className={`w-10 h-10 rounded-xl flex items-center justify-center transition-all ${
                  uploadedFileName
                    ? 'bg-emerald-500/20 text-emerald-400'
                    : 'bg-white/[0.04] text-gray-400 group-hover:text-white'
                }`}
              >
                {uploadedFileName ? <CheckCircle2 className="w-5 h-5" /> : <UploadCloud className="w-5 h-5" />}
              </div>

              {uploadedFileName ? (
                <div>
                  <p className="text-xs font-bold text-white">{uploadedFileName}</p>
                  <p className="text-[11px] text-emerald-400">File selected & ready for analysis</p>
                </div>
              ) : (
                <div>
                  <p className="text-xs font-semibold text-gray-300">
                    <span className="text-indigo-400 hover:underline">Click to upload</span> or drag and drop
                  </p>
                  <p className="text-[11px] text-gray-500">MP4, MOV, MP3, WAV or MKV (up to 2GB)</p>
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Advanced Settings Accordion Drawer */}
        <div className="max-w-2xl mx-auto rounded-2xl bg-white/[0.02] border border-white/[0.06] overflow-hidden">
          <button
            type="button"
            onClick={() => setIsAdvancedOpen(!isAdvancedOpen)}
            className="w-full px-4 py-3 flex items-center justify-between text-xs font-semibold text-gray-300 hover:text-white transition-colors"
          >
            <div className="flex items-center space-x-2">
              <Sliders className="w-3.5 h-3.5 text-indigo-400" />
              <span>Format & Subtitle Preset Settings</span>
              <span className="text-[11px] font-normal text-gray-500">
                ({aspectRatio} • {SUBTITLE_PRESETS.find((p) => p.id === subtitlePreset)?.name})
              </span>
            </div>
            <ChevronDown className={`w-4 h-4 transition-transform duration-300 ${isAdvancedOpen ? 'rotate-180 text-indigo-400' : 'text-gray-500'}`} />
          </button>

          {isAdvancedOpen && (
            <div className="p-4 sm:p-5 border-t border-white/[0.06] space-y-5 bg-[#090D16]/50">
              {/* Target Aspect Ratio */}
              <div>
                <label className="block text-[11px] font-bold uppercase tracking-wider text-gray-400 mb-2.5">
                  Target Aspect Ratio
                </label>
                <div className="grid grid-cols-3 gap-2.5">
                  {[
                    { id: '9:16', label: '9:16 Vertical', sub: 'Shorts • TikTok • Reels' },
                    { id: '1:1', label: '1:1 Square', sub: 'Instagram • LinkedIn' },
                    { id: '16:9', label: '16:9 Landscape', sub: 'YouTube Highlights' },
                  ].map((ratio) => (
                    <button
                      key={ratio.id}
                      type="button"
                      onClick={() => setAspectRatio(ratio.id as AspectRatio)}
                      disabled={isLoading}
                      className={`p-3 rounded-xl border text-left transition-all ${
                        aspectRatio === ratio.id
                          ? 'bg-indigo-600/20 border-indigo-500 text-white shadow-lg shadow-indigo-500/10'
                          : 'bg-white/[0.02] border-white/[0.08] text-gray-400 hover:border-white/[0.15] hover:text-gray-200'
                      }`}
                    >
                      <div className="text-xs font-bold text-white">{ratio.label}</div>
                      <div className="text-[10px] text-gray-400 truncate mt-0.5">{ratio.sub}</div>
                    </button>
                  ))}
                </div>
              </div>

              {/* Subtitle Preset Selector with Visual Preview Chips */}
              <div>
                <label className="block text-[11px] font-bold uppercase tracking-wider text-gray-400 mb-2.5">
                  Subtitle Animation Style Preset
                </label>
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2.5">
                  {SUBTITLE_PRESETS.map((preset) => {
                    const isSelected = subtitlePreset === preset.id;
                    return (
                      <div
                        key={preset.id}
                        onClick={() => setSubtitlePreset(preset.id)}
                        className={`cursor-pointer p-3 rounded-xl border transition-all flex flex-col justify-between space-y-2.5 ${
                          isSelected
                            ? 'bg-indigo-600/15 border-indigo-500 shadow-md shadow-indigo-500/10'
                            : 'bg-white/[0.02] border-white/[0.08] hover:border-white/[0.15]'
                        }`}
                      >
                        <div className="flex items-center justify-between">
                          <div className="flex items-center space-x-2">
                            <span className="text-base">{preset.icon}</span>
                            <div>
                              <div className="text-xs font-bold text-white">{preset.name}</div>
                              <div className="text-[10px] text-gray-400">{preset.tagline}</div>
                            </div>
                          </div>
                          {isSelected && <CheckCircle2 className="w-4 h-4 text-indigo-400" />}
                        </div>

                        {/* Visual Simulation Chip */}
                        <div className="h-8 bg-black/50 rounded-lg flex items-center justify-center p-1 border border-white/[0.05]">
                          <span className={preset.sampleStyle}>SAMPLE TEXT</span>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>
          )}
        </div>

        {/* CTA Button */}
        <div className="max-w-2xl mx-auto pt-2">
          <button
            type="submit"
            disabled={isLoading || !source.trim()}
            className="w-full relative group overflow-hidden rounded-2xl p-[1px] font-semibold text-sm shadow-xl shadow-indigo-500/25 disabled:opacity-50 disabled:cursor-not-allowed transition-all"
          >
            <div className="absolute inset-0 bg-gradient-to-r from-indigo-500 via-purple-500 to-pink-500 transition-all duration-300 group-hover:scale-105 group-hover:opacity-90"></div>
            <div className="relative px-6 py-4 rounded-[15px] bg-[#0B0F1C]/80 hover:bg-[#0B0F1C]/50 transition-colors flex items-center justify-center space-x-2 text-white">
              {isLoading ? (
                <>
                  <div className="w-5 h-5 border-2 border-white/20 border-t-white rounded-full animate-spin"></div>
                  <span className="font-bold text-sm">Processing & Finding Viral Clips...</span>
                </>
              ) : (
                <>
                  <Sparkles className="w-5 h-5 text-indigo-300 group-hover:rotate-12 transition-transform" />
                  <span className="font-bold text-base tracking-wide">✨ Get Viral Clips with AI</span>
                </>
              )}
            </div>
          </button>
        </div>
      </form>
    </div>
  );
};
