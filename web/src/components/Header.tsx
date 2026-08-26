'use client';

import React from 'react';

interface HeaderProps {
  isOnline: boolean;
  scoringMode: string;
  onRefreshHealth: () => void;
}

export const Header: React.FC<HeaderProps> = ({ isOnline, scoringMode, onRefreshHealth }) => {
  return (
    <header className="sticky top-0 z-40 w-full glass-panel border-b border-white/10 px-4 py-3 sm:px-6">
      <div className="max-w-4xl mx-auto flex items-center justify-between">
        {/* Brand Logo & Name */}
        <div className="flex items-center space-x-3">
          <div className="relative flex items-center justify-center w-10 h-10 rounded-xl bg-gradient-to-tr from-indigo-600 via-indigo-500 to-cyan-400 p-[1px] shadow-lg shadow-indigo-500/20">
            <div className="w-full h-full bg-slate-950 rounded-[11px] flex items-center justify-center">
              <svg className="w-5 h-5 text-indigo-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" />
              </svg>
            </div>
          </div>
          <div>
            <div className="flex items-center space-x-2">
              <h1 className="text-base font-bold tracking-tight text-white sm:text-lg">
                Podcast <span className="gradient-text">Shorts AI</span>
              </h1>
              <span className="px-2 py-0.5 text-[10px] font-semibold tracking-wide rounded-full bg-indigo-500/20 text-indigo-300 border border-indigo-500/30">
                PRO 2.0
              </span>
            </div>
            <p className="text-xs text-gray-400 hidden sm:block">AI Short-Form Video Extractor & Re-framer</p>
          </div>
        </div>

        {/* Live Status Indicators */}
        <div className="flex items-center space-x-2">
          {/* Scoring Mode pill */}
          <div className={`px-2.5 py-1 rounded-full text-xs font-medium border flex items-center space-x-1.5 ${
            scoringMode === 'llm'
              ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30'
              : 'bg-amber-500/10 text-amber-300 border-amber-500/30'
          }`}>
            <span className={`w-1.5 h-1.5 rounded-full ${scoringMode === 'llm' ? 'bg-emerald-400 animate-pulse' : 'bg-amber-400'}`}></span>
            <span className="capitalize">{scoringMode} Mode</span>
          </div>

          {/* Server Connection status button */}
          <button
            onClick={onRefreshHealth}
            title="Click to re-check backend connection"
            className={`p-1.5 rounded-lg border text-xs flex items-center space-x-1 transition-all ${
              isOnline
                ? 'bg-slate-900/80 border-slate-800 text-gray-300 hover:text-white'
                : 'bg-rose-500/10 border-rose-500/30 text-rose-400'
            }`}
          >
            <span className={`w-2 h-2 rounded-full ${isOnline ? 'bg-emerald-500' : 'bg-rose-500 animate-ping'}`}></span>
            <span className="hidden md:inline">{isOnline ? 'Backend Ready' : 'Backend Offline'}</span>
          </button>
        </div>
      </div>
    </header>
  );
};
