'use client';

import React, { useState } from 'react';
import { TrimPayload, ClipItem } from '@/types/api';

interface BatchRenderBarProps {
  clips: ClipItem[];
  sourceUrl: string;
  onStartTrim: (payload: TrimPayload) => void;
  isTrimming: boolean;
  aspectRatio: '9:16' | '1:1' | '16:9';
  enableHookBanner: boolean;
}

export const BatchRenderBar: React.FC<BatchRenderBarProps> = ({
  clips,
  sourceUrl,
  onStartTrim,
  isTrimming,
  aspectRatio,
  enableHookBanner,
}) => {
  const [fastMode, setFastMode] = useState<boolean>(true);

  if (!clips || clips.length === 0) return null;

  const handleTrimClick = () => {
    onStartTrim({
      source: sourceUrl,
      clips,
      fast: fastMode,
      aspect_ratio: aspectRatio,
      enable_hook_banner: enableHookBanner,
    });
  };

  return (
    <div className="glass-panel rounded-2xl p-4 border border-emerald-500/30 bg-emerald-950/20 shadow-lg flex flex-col sm:flex-row items-center justify-between gap-3">
      <div className="flex items-center space-x-3 w-full sm:w-auto">
        <div className="w-9 h-9 rounded-xl bg-emerald-500/20 border border-emerald-500/40 flex items-center justify-center text-emerald-400 shrink-0">
          <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z" />
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
        </div>
        <div>
          <h4 className="text-sm font-bold text-white flex items-center space-x-2">
            <span>Render All {clips.length} Short Clips</span>
            <span className="px-2 py-0.5 rounded-full text-[10px] bg-emerald-500/20 text-emerald-300 font-mono">
              Ready
            </span>
          </h4>
          <p className="text-xs text-gray-400">
            Cut and export formatted MP4 video shorts from JSON clip timestamps.
          </p>
        </div>
      </div>

      <div className="flex items-center space-x-3 w-full sm:w-auto justify-end">
        <label className="flex items-center space-x-2 text-xs text-gray-300 cursor-pointer">
          <input
            type="checkbox"
            checked={fastMode}
            onChange={(e) => setFastMode(e.target.checked)}
            disabled={isTrimming}
            className="w-4 h-4 rounded text-emerald-600 focus:ring-emerald-500 bg-slate-900 border-slate-700"
          />
          <span title="Fast Cut uses ffmpeg -c copy for instant trimming without re-encoding">Fast Cut (-c copy)</span>
        </label>

        <a
          href="/outputs/captions.txt"
          download="captions.txt"
          target="_blank"
          rel="noopener noreferrer"
          className="py-2.5 px-3.5 rounded-xl bg-slate-800 border border-slate-700 hover:border-indigo-500/50 text-indigo-300 hover:text-white font-bold text-xs shadow-md transition-all flex items-center space-x-1.5 shrink-0"
          title="Download complete video transcript and short captions TXT file"
        >
          <svg className="w-4 h-4 text-indigo-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
          </svg>
          <span>Captions TXT</span>
        </a>

        <button
          onClick={handleTrimClick}
          disabled={isTrimming}
          className="py-2.5 px-5 rounded-xl bg-gradient-to-r from-emerald-600 to-teal-500 text-white font-bold text-xs shadow-lg shadow-emerald-600/25 hover:shadow-emerald-600/40 hover:scale-[1.02] active:scale-[0.98] transition-all disabled:opacity-50 flex items-center space-x-2 shrink-0"
        >
          {isTrimming ? (
            <>
              <svg className="animate-spin h-3.5 w-3.5 text-white" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
              </svg>
              <span>Trimming Shorts...</span>
            </>
          ) : (
            <>
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
              </svg>
              <span>Export All MP4s</span>
            </>
          )}
        </button>
      </div>
    </div>
  );
};
