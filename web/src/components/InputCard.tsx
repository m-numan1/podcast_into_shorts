'use client';

import React, { useState } from 'react';
import { AnalyzePayload } from '@/types/api';

interface InputCardProps {
  onStartAnalysis: (payload: AnalyzePayload) => void;
  isLoading: boolean;
}

export const InputCard: React.FC<InputCardProps> = ({ onStartAnalysis, isLoading }) => {
  const [source, setSource] = useState<string>('');
  const [isDemo, setIsDemo] = useState<boolean>(false);
  const [shouldRender, setShouldRender] = useState<boolean>(true);
  const [aspectRatio, setAspectRatio] = useState<'9:16' | '1:1' | '16:9'>('9:16');
  const [enableHookBanner, setEnableHookBanner] = useState<boolean>(true);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!source.trim() && !isDemo) {
      alert('Please enter a valid YouTube URL, local file path, or check Demo Mode.');
      return;
    }
    onStartAnalysis({
      source: source.trim(),
      demo: isDemo,
      render: shouldRender,
      aspect_ratio: aspectRatio,
      enable_hook_banner: enableHookBanner,
    });
  };

  return (
    <div className="glass-panel rounded-2xl p-5 sm:p-6 shadow-xl relative overflow-hidden border border-white/10">
      {/* Background ambient lighting */}
      <div className="absolute -top-24 -right-24 w-48 h-48 bg-indigo-600/20 rounded-full blur-3xl pointer-events-none"></div>
      <div className="absolute -bottom-24 -left-24 w-48 h-48 bg-cyan-600/15 rounded-full blur-3xl pointer-events-none"></div>

      <form onSubmit={handleSubmit} className="relative z-10 space-y-5">
        <div>
          <label htmlFor="source-input" className="block text-xs font-semibold uppercase tracking-wider text-gray-300 mb-2">
            Media Source (YouTube URL or Local Path)
          </label>
          <div className="relative">
            <div className="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none text-gray-400">
              <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
              </svg>
            </div>
            <input
              id="source-input"
              type="text"
              value={source}
              onChange={(e) => setSource(e.target.value)}
              disabled={isDemo || isLoading}
              placeholder={isDemo ? 'Using synthetic demo fixture...' : 'https://www.youtube.com/watch?v=...'}
              className="w-full pl-11 pr-4 py-3 bg-slate-900/90 border border-slate-700/70 rounded-xl text-white placeholder-gray-500 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500/50 focus:border-indigo-500 transition-all disabled:opacity-50"
            />
          </div>
        </div>

        {/* Format & Aspect Ratio Selector */}
        <div>
          <label className="block text-xs font-semibold uppercase tracking-wider text-gray-300 mb-2">
            Output Aspect Ratio Format
          </label>
          <div className="grid grid-cols-3 gap-2">
            {[
              { id: '9:16', label: '9:16 Vertical', sub: 'Shorts/TikTok/Reels' },
              { id: '1:1', label: '1:1 Square', sub: 'Insta/LinkedIn' },
              { id: '16:9', label: '16:9 Landscape', sub: 'YT Highlights' },
            ].map((ratio) => (
              <button
                key={ratio.id}
                type="button"
                onClick={() => setAspectRatio(ratio.id as any)}
                disabled={isLoading}
                className={`py-2.5 px-3 rounded-xl border text-left transition-all ${
                  aspectRatio === ratio.id
                    ? 'bg-indigo-600/20 border-indigo-500 text-white shadow-lg shadow-indigo-500/10'
                    : 'bg-slate-900/50 border-slate-800 text-gray-400 hover:border-slate-700 hover:text-gray-200'
                }`}
              >
                <div className="text-xs font-bold">{ratio.label}</div>
                <div className="text-[10px] text-gray-400 truncate">{ratio.sub}</div>
              </button>
            ))}
          </div>
        </div>

        {/* Checkbox Toggles Grid */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 pt-1">
          <label className="flex items-center space-x-3 p-2.5 rounded-xl bg-slate-900/40 border border-slate-800/80 cursor-pointer hover:border-slate-700 transition-all">
            <input
              type="checkbox"
              checked={isDemo}
              onChange={(e) => setIsDemo(e.target.checked)}
              disabled={isLoading}
              className="w-4 h-4 rounded text-indigo-600 focus:ring-indigo-500 bg-slate-800 border-slate-700"
            />
            <div className="text-xs">
              <span className="font-medium text-white block">Demo Mode</span>
              <span className="text-gray-400 text-[10px]">Use built-in synthetic fixture</span>
            </div>
          </label>

          <label className="flex items-center space-x-3 p-2.5 rounded-xl bg-slate-900/40 border border-slate-800/80 cursor-pointer hover:border-slate-700 transition-all">
            <input
              type="checkbox"
              checked={shouldRender}
              onChange={(e) => setShouldRender(e.target.checked)}
              disabled={isLoading}
              className="w-4 h-4 rounded text-indigo-600 focus:ring-indigo-500 bg-slate-800 border-slate-700"
            />
            <div className="text-xs">
              <span className="font-medium text-white block">Auto Render MP4</span>
              <span className="text-gray-400 text-[10px]">Cut & re-frame video clips</span>
            </div>
          </label>

          <label className="flex items-center space-x-3 p-2.5 rounded-xl bg-slate-900/40 border border-slate-800/80 cursor-pointer hover:border-slate-700 transition-all sm:col-span-2">
            <input
              type="checkbox"
              checked={enableHookBanner}
              onChange={(e) => setEnableHookBanner(e.target.checked)}
              disabled={isLoading}
              className="w-4 h-4 rounded text-indigo-600 focus:ring-indigo-500 bg-slate-800 border-slate-700"
            />
            <div className="text-xs">
              <span className="font-medium text-white block">Burn AI Hook Banner Overlay</span>
              <span className="text-gray-400 text-[10px]">Adds eye-catching title caption banner to rendered shorts</span>
            </div>
          </label>
        </div>

        {/* Submit Button */}
        <button
          type="submit"
          disabled={isLoading}
          className="w-full py-3.5 px-6 rounded-xl bg-gradient-to-r from-indigo-600 via-indigo-500 to-cyan-500 text-white font-semibold text-sm shadow-lg shadow-indigo-500/25 hover:shadow-indigo-500/40 hover:scale-[1.01] active:scale-[0.99] transition-all disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center space-x-2"
        >
          {isLoading ? (
            <>
              <svg className="animate-spin -ml-1 mr-2 h-4 w-4 text-white" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
              </svg>
              <span>Analyzing & Extracting Shorts...</span>
            </>
          ) : (
            <>
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z" />
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              <span>Start AI Clip Extraction</span>
            </>
          )}
        </button>
      </form>
    </div>
  );
};
