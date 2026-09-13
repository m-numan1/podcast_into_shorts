'use client';

import React from 'react';
import { Sparkles, Zap, Cpu, BookOpen, FolderGit2, RefreshCw, Layers, ExternalLink } from 'lucide-react';
import { BackendHealth } from '@/types/api';

interface HeaderProps {
  health: BackendHealth;
  onRefreshHealth: () => void;
  onSelectTab?: (tab: 'studio' | 'clips' | 'pricing' | 'docs') => void;
  activeTab?: string;
}

export const Header: React.FC<HeaderProps> = ({
  health,
  onRefreshHealth,
  onSelectTab,
  activeTab = 'studio',
}) => {
  // Format model badge text
  const getModelBadgeText = () => {
    if (!health.online) return 'Backend Offline';
    const provider = health.provider || (health.scoring_mode === 'llm' ? 'Gemini' : 'Heuristic');
    const embed = health.embedding_backend || 'FastEmbed';
    const capitalizedProvider = provider.charAt(0).toUpperCase() + provider.slice(1);
    const capitalizedEmbed = embed.charAt(0).toUpperCase() + embed.slice(1);
    return `${capitalizedProvider} / ${capitalizedEmbed} active`;
  };

  return (
    <header className="sticky top-0 z-50 w-full backdrop-blur-xl bg-[#090D16]/80 border-b border-white/[0.08] px-4 sm:px-8 py-3.5 transition-all">
      <div className="max-w-7xl mx-auto flex items-center justify-between">
        {/* Brand Logo & Name */}
        <div className="flex items-center space-x-3.5 cursor-pointer" onClick={() => onSelectTab?.('studio')}>
          <div className="relative group">
            <div className="absolute -inset-0.5 bg-gradient-to-r from-indigo-500 via-purple-500 to-pink-500 rounded-xl blur opacity-75 group-hover:opacity-100 transition duration-300"></div>
            <div className="relative w-10 h-10 rounded-xl bg-[#0B101E] border border-white/10 flex items-center justify-center shadow-lg shadow-indigo-500/20">
              <Sparkles className="w-5 h-5 text-indigo-400 animate-pulse" />
            </div>
          </div>

          <div>
            <div className="flex items-center space-x-2">
              <span className="text-lg font-extrabold tracking-tight text-white font-sans">
                ClipPulse<span className="bg-gradient-to-r from-indigo-400 via-purple-400 to-pink-400 bg-clip-text text-transparent"> AI</span>
              </span>
              <span className="px-2 py-0.5 text-[10px] font-bold tracking-wider uppercase rounded-full bg-gradient-to-r from-indigo-500/20 to-purple-500/20 text-indigo-300 border border-indigo-500/30">
                PRO
              </span>
            </div>
            <p className="text-[11px] text-gray-400 hidden sm:block">AI Podcast & Video Repurposing Studio</p>
          </div>
        </div>

        {/* Quick Links Nav */}
        <nav className="hidden md:flex items-center space-x-1 lg:space-x-2 bg-white/[0.03] border border-white/[0.06] rounded-full px-3 py-1 text-xs">
          <button
            onClick={() => onSelectTab?.('studio')}
            className={`px-3 py-1.5 rounded-full font-medium transition-all ${
              activeTab === 'studio'
                ? 'bg-indigo-600/30 text-white border border-indigo-500/40 shadow-sm'
                : 'text-gray-400 hover:text-white'
            }`}
          >
            Create Clips
          </button>
          <button
            onClick={() => onSelectTab?.('clips')}
            className={`px-3 py-1.5 rounded-full font-medium transition-all ${
              activeTab === 'clips'
                ? 'bg-indigo-600/30 text-white border border-indigo-500/40 shadow-sm'
                : 'text-gray-400 hover:text-white'
            }`}
          >
            My Projects
          </button>
          <button
            onClick={() => onSelectTab?.('pricing')}
            className={`px-3 py-1.5 rounded-full font-medium transition-all ${
              activeTab === 'pricing'
                ? 'bg-indigo-600/30 text-white border border-indigo-500/40 shadow-sm'
                : 'text-gray-400 hover:text-white'
            }`}
          >
            Pricing
          </button>
          <a
            href="https://github.com/m-numan1/podcast_into_shorts"
            target="_blank"
            rel="noreferrer"
            className="px-3 py-1.5 rounded-full font-medium text-gray-400 hover:text-white transition-all flex items-center space-x-1"
          >
            <span>Docs</span>
            <ExternalLink className="w-3 h-3 opacity-60" />
          </a>
        </nav>

        {/* Right Side: Status indicator & GitHub */}
        <div className="flex items-center space-x-3">
          {/* Active AI Model Indicator */}
          <div
            onClick={onRefreshHealth}
            title="Click to refresh AI backend health"
            className={`cursor-pointer px-3 py-1.5 rounded-full text-xs font-medium border flex items-center space-x-2 transition-all ${
              health.online
                ? 'bg-emerald-500/10 text-emerald-300 border-emerald-500/30 hover:bg-emerald-500/20'
                : 'bg-rose-500/10 text-rose-300 border-rose-500/30 hover:bg-rose-500/20'
            }`}
          >
            <span className="relative flex h-2 w-2">
              <span
                className={`animate-ping absolute inline-flex h-full w-full rounded-full opacity-75 ${
                  health.online ? 'bg-emerald-400' : 'bg-rose-400'
                }`}
              ></span>
              <span
                className={`relative inline-flex rounded-full h-2 w-2 ${
                  health.online ? 'bg-emerald-500' : 'bg-rose-500'
                }`}
              ></span>
            </span>
            <span className="font-mono text-[11px] font-semibold">{getModelBadgeText()}</span>
            <RefreshCw className="w-3 h-3 text-gray-400 hover:rotate-180 transition-transform duration-500" />
          </div>

          {/* GitHub Repo Button */}
          <a
            href="https://github.com/m-numan1/podcast_into_shorts"
            target="_blank"
            rel="noreferrer"
            className="p-2 rounded-xl bg-white/[0.04] hover:bg-white/[0.08] border border-white/[0.08] text-gray-300 hover:text-white transition-all"
            title="GitHub Repository"
          >
            <FolderGit2 className="w-4 h-4" />
          </a>
        </div>
      </div>
    </header>
  );
};
