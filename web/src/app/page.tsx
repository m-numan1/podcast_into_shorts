'use client';

import React, { useState, useEffect, useRef } from 'react';
import { Header } from '@/components/Header';
import { InputStudio } from '@/components/InputStudio';
import { ProcessingStepper } from '@/components/ProcessingStepper';
import { ViralClipsFeed } from '@/components/ViralClipsFeed';
import {
  AnalyzePayload,
  JobStatusResponse,
  ClipItem,
  BackendHealth,
  AspectRatio,
  SubtitlePresetId,
} from '@/types/api';
import { Sparkles, Check, Film, ArrowRight, Zap, ShieldCheck } from 'lucide-react';

export default function Home() {
  const [health, setHealth] = useState<BackendHealth>({
    online: false,
    scoring_mode: 'heuristic',
  });
  const [activeTab, setActiveTab] = useState<'studio' | 'clips' | 'pricing' | 'docs'>('studio');

  // Job execution state
  const [jobId, setJobId] = useState<string | null>(null);
  const [jobStatus, setJobStatus] = useState<'idle' | 'running' | 'done' | 'error'>('idle');
  const [logs, setLogs] = useState<string[]>([]);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [failedStage, setFailedStage] = useState<string | undefined>();
  const [errorMsg, setErrorMsg] = useState<string | undefined>();

  // Results state
  const [clips, setClips] = useState<ClipItem[]>([]);
  const [sourceMedia, setSourceMedia] = useState<string>('');
  const [episodeTitle, setEpisodeTitle] = useState<string | undefined>();
  const [aspectRatio, setAspectRatio] = useState<AspectRatio>('9:16');
  const [subtitlePreset, setSubtitlePreset] = useState<SubtitlePresetId>('hormozi');

  // Polling ref
  const pollTimerRef = useRef<NodeJS.Timeout | null>(null);

  // Health Check
  const checkHealth = async () => {
    try {
      const res = await fetch('/api/health');
      const data = await res.json();
      setHealth({
        online: data.online !== false,
        scoring_mode: data.scoring_mode || 'heuristic',
        embedding_backend: data.embedding_backend || 'FastEmbed',
        model_name: data.model_name,
        provider: data.provider,
      });
    } catch {
      setHealth({ online: false, scoring_mode: 'offline' });
    }
  };

  useEffect(() => {
    checkHealth();
    const interval = setInterval(checkHealth, 8000);
    return () => clearInterval(interval);
  }, []);

  // Stop Polling
  const stopPolling = () => {
    if (pollTimerRef.current) {
      clearInterval(pollTimerRef.current);
      pollTimerRef.current = null;
    }
  };

  // Poll Job Status
  const startPolling = (id: string) => {
    stopPolling();
    pollTimerRef.current = setInterval(async () => {
      try {
        const res = await fetch(`/api/status?job_id=${encodeURIComponent(id)}`);
        if (!res.ok) return;
        const data: JobStatusResponse = await res.json();

        setLogs(data.logs || []);
        setWarnings(data.warnings || []);

        if (data.status === 'running') {
          setJobStatus('running');
        } else if (data.status === 'done') {
          stopPolling();
          setJobStatus('done');
          setClips(data.clips || []);
          if (data.title) setEpisodeTitle(data.title);
          if (data.source || data.media_file_path) {
            setSourceMedia(data.source || data.media_file_path || '');
          }
        } else if (data.status === 'error') {
          stopPolling();
          setJobStatus('error');
          setFailedStage(data.failed_stage);
          setErrorMsg(data.error);
        }
      } catch (err: any) {
        console.error('Polling error:', err);
      }
    }, 800);
  };

  // Trigger analysis from InputStudio
  const handleStartAnalysis = async (payload: AnalyzePayload) => {
    setJobStatus('running');
    setLogs([`[start] Ingestion initiated for source: ${payload.source}`]);
    setClips([]);
    setWarnings([]);
    setErrorMsg(undefined);
    setFailedStage(undefined);
    setSourceMedia(payload.source);
    if (payload.aspect_ratio) setAspectRatio(payload.aspect_ratio);
    if (payload.subtitle_preset) setSubtitlePreset(payload.subtitle_preset);

    try {
      const res = await fetch('/api/analyze', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          source: payload.source,
          aspect_ratio: payload.aspect_ratio || '9:16',
          subtitle_preset: payload.subtitle_preset || 'hormozi',
        }),
      });

      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Failed to start analysis');

      setJobId(data.job_id);
      startPolling(data.job_id);
    } catch (err: any) {
      setJobStatus('error');
      setErrorMsg(err.message || 'Could not connect to Python backend.');
    }
  };

  // Update a single clip when rendered on-demand
  const handleUpdateClip = (updatedClip: ClipItem) => {
    setClips((prev) =>
      prev.map((c) => (c.rank === updatedClip.rank ? { ...c, ...updatedClip } : c))
    );
  };

  return (
    <div className="min-h-screen flex flex-col bg-[#090D16] text-gray-100 selection:bg-indigo-500 selection:text-white font-sans antialiased">
      {/* Header */}
      <Header
        health={health}
        onRefreshHealth={checkHealth}
        onSelectTab={setActiveTab}
        activeTab={activeTab}
      />

      {/* Main Content Area */}
      <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-8 py-8 space-y-8">
        {/* Backend Offline Banner */}
        {!health.online && (
          <div className="rounded-2xl p-4 bg-gradient-to-r from-rose-500/10 via-rose-500/5 to-transparent border border-rose-500/30 text-rose-300 text-xs flex items-center justify-between shadow-xl">
            <div className="flex items-center space-x-3">
              <div className="w-8 h-8 rounded-xl bg-rose-500/20 flex items-center justify-center text-rose-400 shrink-0 font-bold">
                !
              </div>
              <div>
                <strong className="font-semibold text-white block">
                  AI Pipeline Server Offline
                </strong>
                <span>
                  Start the backend engine with <code className="bg-black/40 px-1.5 py-0.5 rounded text-rose-200">python app.py</code> to run live AI speech transcription & video reframing.
                </span>
              </div>
            </div>
            <button
              onClick={checkHealth}
              className="px-3.5 py-1.5 rounded-xl bg-rose-500/20 hover:bg-rose-500/30 text-rose-200 font-semibold text-xs transition-all shrink-0 ml-3"
            >
              Check Status
            </button>
          </div>
        )}

        {/* Tab 1: Studio */}
        {activeTab === 'studio' && (
          <div className="space-y-8">
            {/* Unified Ingestion Studio */}
            <InputStudio
              onStartAnalysis={handleStartAnalysis}
              isLoading={jobStatus === 'running'}
            />

            {/* Real-Time Processing Stepper */}
            <ProcessingStepper
              status={jobStatus}
              logs={logs}
              warnings={warnings}
              failedStage={failedStage}
              errorMsg={errorMsg}
            />

            {/* Viral Clips Feed Grid */}
            {clips.length > 0 && (
              <ViralClipsFeed
                clips={clips}
                sourceMedia={sourceMedia}
                defaultAspectRatio={aspectRatio}
                defaultSubtitlePreset={subtitlePreset}
                episodeTitle={episodeTitle}
                onUpdateClip={handleUpdateClip}
              />
            )}
          </div>
        )}

        {/* Tab 2: My Projects / Clips */}
        {activeTab === 'clips' && (
          <div className="space-y-6">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-2xl font-black text-white">Project Library</h2>
                <p className="text-xs text-gray-400">Review and export all generated viral shorts.</p>
              </div>
              <button
                onClick={() => setActiveTab('studio')}
                className="px-4 py-2 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-bold transition-all shadow-md shadow-indigo-600/20"
              >
                + New Episode
              </button>
            </div>

            {clips.length > 0 ? (
              <ViralClipsFeed
                clips={clips}
                sourceMedia={sourceMedia}
                defaultAspectRatio={aspectRatio}
                defaultSubtitlePreset={subtitlePreset}
                episodeTitle={episodeTitle}
                onUpdateClip={handleUpdateClip}
              />
            ) : (
              <div className="p-12 rounded-3xl bg-white/[0.02] border border-white/[0.06] text-center space-y-4 max-w-md mx-auto">
                <div className="w-12 h-12 rounded-2xl bg-indigo-500/10 text-indigo-400 mx-auto flex items-center justify-center">
                  <Film className="w-6 h-6" />
                </div>
                <h3 className="text-base font-bold text-white">No Clips Extracted Yet</h3>
                <p className="text-xs text-gray-400 leading-relaxed">
                  Paste any YouTube URL or upload an episode in the Studio to instantly generate viral clips with animated captions.
                </p>
                <button
                  onClick={() => setActiveTab('studio')}
                  className="px-4 py-2 rounded-xl bg-indigo-600 text-white text-xs font-bold hover:bg-indigo-500 transition-all"
                >
                  Go to ClipPulse Studio
                </button>
              </div>
            )}
          </div>
        )}

        {/* Tab 3: Pricing */}
        {activeTab === 'pricing' && (
          <div className="space-y-8 max-w-5xl mx-auto py-4">
            <div className="text-center space-y-2">
              <h2 className="text-3xl font-extrabold text-white">
                Simple, Transparent Plans for <span className="bg-gradient-to-r from-indigo-400 via-purple-400 to-pink-400 bg-clip-text text-transparent">Creators</span>
              </h2>
              <p className="text-xs sm:text-sm text-gray-400">
                Repurpose long-form content into TikToks, Shorts & Reels 10x faster.
              </p>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
              {[
                {
                  name: 'Starter',
                  price: '$0',
                  sub: 'Free forever',
                  features: ['30 mins audio processing / month', 'Auto language detection', 'Hormozi & CapCut subtitle styles', '720p HD MP4 export'],
                  cta: 'Current Plan',
                  popular: false,
                },
                {
                  name: 'Creator Pro',
                  price: '$29',
                  sub: 'per month',
                  features: ['300 mins audio processing', 'All 5 Subtitle Animation Presets', '1080x1920 60fps Ultra HD', 'No watermarks', 'Fast GPU worker queues'],
                  cta: 'Upgrade to Pro',
                  popular: true,
                },
                {
                  name: 'Agency Studio',
                  price: '$79',
                  sub: 'per month',
                  features: ['Unlimited audio processing', 'Custom brand font upload', 'Multi-speaker active speaker tracking', 'Priority 24/7 support'],
                  cta: 'Contact Sales',
                  popular: false,
                },
              ].map((tier) => (
                <div
                  key={tier.name}
                  className={`rounded-3xl p-6 border flex flex-col justify-between space-y-6 ${
                    tier.popular
                      ? 'bg-gradient-to-b from-[#141A2E] to-[#0E1322] border-indigo-500 shadow-2xl shadow-indigo-500/20 relative'
                      : 'bg-[#0D1220]/70 border-white/[0.08]'
                  }`}
                >
                  {tier.popular && (
                    <div className="absolute -top-3 left-1/2 -translate-x-1/2 px-3 py-0.5 rounded-full bg-gradient-to-r from-indigo-500 to-pink-500 text-white text-[10px] font-black uppercase tracking-wider shadow-md">
                      Most Popular
                    </div>
                  )}

                  <div className="space-y-4">
                    <div>
                      <h3 className="text-lg font-bold text-white">{tier.name}</h3>
                      <div className="flex items-baseline space-x-1 mt-2">
                        <span className="text-3xl font-black text-white font-mono">{tier.price}</span>
                        <span className="text-xs text-gray-400">{tier.sub}</span>
                      </div>
                    </div>

                    <ul className="space-y-2.5 text-xs text-gray-300">
                      {tier.features.map((f, i) => (
                        <li key={i} className="flex items-center space-x-2">
                          <Check className="w-4 h-4 text-emerald-400 shrink-0" />
                          <span>{f}</span>
                        </li>
                      ))}
                    </ul>
                  </div>

                  <button
                    onClick={() => setActiveTab('studio')}
                    className={`w-full py-2.5 rounded-xl font-bold text-xs transition-all ${
                      tier.popular
                        ? 'bg-gradient-to-r from-indigo-600 via-purple-600 to-pink-600 text-white shadow-lg shadow-indigo-500/25 hover:opacity-95'
                        : 'bg-white/[0.06] hover:bg-white/[0.1] text-white'
                    }`}
                  >
                    {tier.cta}
                  </button>
                </div>
              ))}
            </div>
          </div>
        )}
      </main>

      {/* Footer */}
      <footer className="w-full border-t border-white/[0.06] py-6 px-4 sm:px-8 text-center text-xs text-gray-500">
        <div className="max-w-7xl mx-auto flex flex-col sm:flex-row items-center justify-between gap-3">
          <p>© 2026 ClipPulse AI • Powered by Whisper, FastEmbed & LLM Virality Scoring</p>
          <div className="flex items-center space-x-4">
            <span className="hover:text-gray-300 cursor-pointer" onClick={() => setActiveTab('studio')}>Studio</span>
            <span className="hover:text-gray-300 cursor-pointer" onClick={() => setActiveTab('clips')}>My Projects</span>
            <span className="hover:text-gray-300 cursor-pointer" onClick={() => setActiveTab('pricing')}>Pricing</span>
          </div>
        </div>
      </footer>
    </div>
  );
}
