'use client';

import React, { useState, useEffect, useRef } from 'react';
import { Header } from '@/components/Header';
import { InputCard } from '@/components/InputCard';
import { StatusDrawer } from '@/components/StatusDrawer';
import { ClipCard } from '@/components/ClipCard';
import { BatchRenderBar } from '@/components/BatchRenderBar';
import { AnalyzePayload, TrimPayload, JobStatusResponse, ClipItem } from '@/types/api';

export default function Home() {
  const [isOnline, setIsOnline] = useState<boolean>(true);
  const [scoringMode, setScoringMode] = useState<string>('heuristic');
  const [activeTab, setActiveTab] = useState<'create' | 'clips' | 'logs'>('create');

  // Job execution state
  const [jobId, setJobId] = useState<string | null>(null);
  const [jobStatus, setJobStatus] = useState<'idle' | 'running' | 'done' | 'error'>('idle');
  const [logs, setLogs] = useState<string[]>([]);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [failedStage, setFailedStage] = useState<string | undefined>();
  const [errorMsg, setErrorMsg] = useState<string | undefined>();

  // Results state
  const [clips, setClips] = useState<ClipItem[]>([]);
  const [isSynthetic, setIsSynthetic] = useState<boolean>(false);
  const [provenanceMode, setProvenanceMode] = useState<string>('');
  const [sourceMedia, setSourceMedia] = useState<string>('');
  const [aspectRatio, setAspectRatio] = useState<'9:16' | '1:1' | '16:9'>('9:16');
  const [enableHookBanner, setEnableHookBanner] = useState<boolean>(true);

  // Polling ref
  const pollTimerRef = useRef<NodeJS.Timeout | null>(null);

  // Health Check
  const checkHealth = async () => {
    try {
      const res = await fetch('/api/health');
      const data = await res.json();
      setIsOnline(data.online !== false);
      if (data.scoring_mode) {
        setScoringMode(data.scoring_mode);
      }
    } catch {
      setIsOnline(false);
    }
  };

  useEffect(() => {
    checkHealth();
    const interval = setInterval(checkHealth, 10000);
    return () => clearInterval(interval);
  }, []);

  // Cleanup polling timer
  const stopPolling = () => {
    if (pollTimerRef.current) {
      clearInterval(pollTimerRef.current);
      pollTimerRef.current = null;
    }
  };

  // Poll job status
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
          setIsSynthetic(!!data.is_synthetic);
          if (data.provenance?.scoring_mode) {
            setProvenanceMode(data.provenance.scoring_mode);
          }
          if (data.source || data.media_file_path) {
            setSourceMedia(data.source || data.media_file_path || '');
          }
          if (data.clips && data.clips.length > 0) {
            setActiveTab('clips');
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

  // Trigger analysis
  const handleStartAnalysis = async (payload: AnalyzePayload) => {
    setJobStatus('running');
    setLogs([`[start] Initializing pipeline job...`]);
    setClips([]);
    setWarnings([]);
    setErrorMsg(undefined);
    setFailedStage(undefined);
    setAspectRatio(payload.aspect_ratio);
    setEnableHookBanner(payload.enable_hook_banner);

    try {
      const res = await fetch('/api/analyze', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
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

  // Trigger Batch Trim
  const handleStartTrim = async (payload: TrimPayload) => {
    setJobStatus('running');
    setLogs((prev) => [...prev, `[start trim] Batch cutting ${payload.clips.length} clips from JSON...`]);

    try {
      const res = await fetch('/api/trim', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });

      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Failed to start trim job');

      setJobId(data.job_id);
      startPolling(data.job_id);
    } catch (err: any) {
      setJobStatus('error');
      setErrorMsg(err.message || 'Trim operation failed.');
    }
  };

  return (
    <div className="min-h-screen flex flex-col bg-[#090D16] text-gray-100 selection:bg-indigo-500 selection:text-white pb-20">
      {/* Header */}
      <Header isOnline={isOnline} scoringMode={scoringMode} onRefreshHealth={checkHealth} />

      {/* Main Container */}
      <main className="flex-1 max-w-4xl w-full mx-auto px-4 py-6 space-y-6">
        {/* Offline Warning Banner */}
        {!isOnline && (
          <div className="p-4 rounded-2xl bg-rose-500/10 border border-rose-500/30 text-rose-300 text-xs flex items-center justify-between shadow-lg">
            <div className="flex items-center space-x-3">
              <div className="w-8 h-8 rounded-xl bg-rose-500/20 flex items-center justify-center text-rose-400 shrink-0">
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                </svg>
              </div>
              <div>
                <strong className="font-semibold text-white block">Python Backend Offline (`python app.py`)</strong>
                <span>Run `python app.py` on port 8000 to enable real video analysis & rendering.</span>
              </div>
            </div>
            <button
              onClick={checkHealth}
              className="px-3 py-1.5 rounded-lg bg-rose-500/20 hover:bg-rose-500/30 text-rose-200 font-semibold text-xs transition-all shrink-0 ml-3"
            >
              Retry
            </button>
          </div>
        )}

        {/* Synthetic / Heuristic Notice Banners */}
        {isSynthetic && (
          <div className="p-3.5 rounded-2xl bg-amber-500/10 border border-amber-500/30 text-amber-200 text-xs flex items-center space-x-3">
            <span className="px-2 py-0.5 rounded-md bg-amber-500/20 text-amber-300 font-bold uppercase text-[10px]">Synthetic Fixture</span>
            <span>Demo fixture mode active. These outputs are for UI demonstration only.</span>
          </div>
        )}

        {provenanceMode === 'heuristic' && !isSynthetic && (
          <div className="p-3.5 rounded-2xl bg-indigo-500/10 border border-indigo-500/30 text-indigo-200 text-xs flex items-center space-x-3">
            <span className="px-2 py-0.5 rounded-md bg-indigo-500/20 text-indigo-300 font-bold uppercase text-[10px]">Heuristic Mode</span>
            <span>Scored without LLM keys. Rankings are derived from audio acoustic cues and speech rate.</span>
          </div>
        )}

        {/* Input Configuration Card */}
        <InputCard onStartAnalysis={handleStartAnalysis} isLoading={jobStatus === 'running'} />

        {/* Live Pipeline Status & Logs Drawer */}
        <StatusDrawer
          status={jobStatus}
          logs={logs}
          failedStage={failedStage}
          errorMsg={errorMsg}
          warnings={warnings}
        />

        {/* Batch Render Action Bar */}
        {clips.length > 0 && (
          <BatchRenderBar
            clips={clips}
            sourceUrl={sourceMedia}
            onStartTrim={handleStartTrim}
            isTrimming={jobStatus === 'running'}
            aspectRatio={aspectRatio}
            enableHookBanner={enableHookBanner}
          />
        )}

        {/* Clips Showcase Grid Header */}
        {clips.length > 0 && (
          <div className="space-y-4 pt-2">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-lg font-bold text-white flex items-center space-x-2">
                  <span>Extracted Shorts</span>
                  <span className="px-2.5 py-0.5 rounded-full text-xs bg-indigo-500/20 text-indigo-300 border border-indigo-500/30 font-mono">
                    {clips.length} Clips
                  </span>
                </h2>
                <p className="text-xs text-gray-400">Ranked by virality potential, hook strength & listener retention.</p>
              </div>
            </div>

            {/* Clip Grid */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {clips.map((clip) => (
                <ClipCard key={clip.rank} clip={clip} aspectRatio={aspectRatio} />
              ))}
            </div>
          </div>
        )}
      </main>

      {/* Floating Mobile Bottom Navigation Bar */}
      <nav className="fixed bottom-0 left-0 right-0 z-50 glass-panel border-t border-white/10 px-6 py-2.5 max-w-lg mx-auto rounded-t-2xl shadow-2xl">
        <div className="flex items-center justify-around text-xs">
          <button
            onClick={() => setActiveTab('create')}
            className={`flex flex-col items-center space-y-1 transition-colors ${
              activeTab === 'create' ? 'text-indigo-400 font-bold' : 'text-gray-400 hover:text-gray-200'
            }`}
          >
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
            </svg>
            <span>Extractor</span>
          </button>

          <button
            onClick={() => setActiveTab('clips')}
            className={`flex flex-col items-center space-y-1 transition-colors relative ${
              activeTab === 'clips' ? 'text-indigo-400 font-bold' : 'text-gray-400 hover:text-gray-200'
            }`}
          >
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
            </svg>
            <span>Clips ({clips.length})</span>
            {clips.length > 0 && (
              <span className="absolute -top-1 right-2 w-2 h-2 rounded-full bg-emerald-400 animate-ping"></span>
            )}
          </button>

          <button
            onClick={() => setActiveTab('logs')}
            className={`flex flex-col items-center space-y-1 transition-colors ${
              activeTab === 'logs' ? 'text-indigo-400 font-bold' : 'text-gray-400 hover:text-gray-200'
            }`}
          >
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
            </svg>
            <span>Logs</span>
          </button>
        </div>
      </nav>
    </div>
  );
}
