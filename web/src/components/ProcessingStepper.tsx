'use client';

import React, { useState, useEffect, useRef } from 'react';
import {
  Download,
  Mic,
  BrainCircuit,
  Film,
  Terminal,
  ChevronDown,
  CheckCircle2,
  AlertTriangle,
  XCircle,
  Loader2,
  Sparkles,
} from 'lucide-react';

interface ProcessingStepperProps {
  status: 'idle' | 'running' | 'done' | 'error';
  logs: string[];
  warnings?: string[];
  failedStage?: string;
  errorMsg?: string;
}

interface StepInfo {
  id: number;
  title: string;
  subtitle: string;
  icon: React.ReactNode;
  keywords: string[];
}

const STEPS: StepInfo[] = [
  {
    id: 1,
    title: 'Downloading & Extraction',
    subtitle: 'Extracting clean 16kHz audio stream',
    icon: <Download className="w-4 h-4" />,
    keywords: ['download', 'extract', 'media', 'audio', 'ytdlp', 'ffmpeg', 'stream'],
  },
  {
    id: 2,
    title: 'AI Transcription & Alignment',
    subtitle: 'Auto-detecting language & word timestamps',
    icon: <Mic className="w-4 h-4" />,
    keywords: ['whisper', 'transcrib', 'speech', 'timestamp', 'language', 'segments'],
  },
  {
    id: 3,
    title: 'Viral Hook & Narrative Scoring',
    subtitle: 'Hook detection, retention & virality analysis',
    icon: <BrainCircuit className="w-4 h-4" />,
    keywords: ['scoring', 'rank', 'viral', 'hook', 'candidate', 'gemini', 'openai', 'llm', 'semantic'],
  },
  {
    id: 4,
    title: 'Reframing & Subtitle Synthesis',
    subtitle: '9:16 vertical crop & word-level animation',
    icon: <Film className="w-4 h-4" />,
    keywords: ['render', 'subtitles', 'preset', 'burn', 'card', 'video', 'encode', 'completed'],
  },
];

export const ProcessingStepper: React.FC<ProcessingStepperProps> = ({
  status,
  logs,
  warnings = [],
  failedStage,
  errorMsg,
}) => {
  const [isTerminalOpen, setIsTerminalOpen] = useState<boolean>(true);
  const terminalBottomRef = useRef<HTMLDivElement>(null);

  // Auto-scroll terminal when new logs arrive
  useEffect(() => {
    if (isTerminalOpen && terminalBottomRef.current) {
      terminalBottomRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [logs, isTerminalOpen]);

  if (status === 'idle') return null;

  // Determine current active step based on logs and status
  const calculateCurrentStep = (): number => {
    if (status === 'done') return 4;
    if (status === 'error') {
      if (failedStage?.toLowerCase().includes('download')) return 1;
      if (failedStage?.toLowerCase().includes('transcrib')) return 2;
      if (failedStage?.toLowerCase().includes('score')) return 3;
      return 1;
    }

    // Inspect logs from latest to oldest
    const combined = logs.join(' ').toLowerCase();
    if (combined.includes('rendering') || combined.includes('subtitle') || combined.includes('final_clips')) return 4;
    if (combined.includes('scoring') || combined.includes('candidate') || combined.includes('llm') || combined.includes('viral')) return 3;
    if (combined.includes('whisper') || combined.includes('transcription') || combined.includes('transcrib')) return 2;
    return 1;
  };

  const currentStep = calculateCurrentStep();

  // Approximate progress percentage
  const calculateProgress = (): number => {
    if (status === 'done') return 100;
    if (status === 'error') return Math.max(15, currentStep * 20);
    const stepBase = (currentStep - 1) * 25;
    const subProgress = Math.min(20, Math.floor(logs.length * 1.5));
    return Math.min(95, stepBase + subProgress);
  };

  const progressPercent = calculateProgress();

  return (
    <div className="w-full rounded-3xl p-5 sm:p-7 bg-gradient-to-b from-[#101524]/90 to-[#0A0E17]/95 border border-white/[0.08] shadow-2xl backdrop-blur-2xl space-y-6">
      {/* Header bar with status and circular/linear progress */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div className="flex items-center space-x-3.5">
          <div className="relative">
            {status === 'running' ? (
              <div className="w-11 h-11 rounded-2xl bg-indigo-500/10 border border-indigo-500/30 flex items-center justify-center text-indigo-400 shadow-lg shadow-indigo-500/10">
                <Loader2 className="w-6 h-6 animate-spin text-indigo-400" />
              </div>
            ) : status === 'done' ? (
              <div className="w-11 h-11 rounded-2xl bg-emerald-500/10 border border-emerald-500/30 flex items-center justify-center text-emerald-400 shadow-lg shadow-emerald-500/10">
                <CheckCircle2 className="w-6 h-6 text-emerald-400" />
              </div>
            ) : (
              <div className="w-11 h-11 rounded-2xl bg-rose-500/10 border border-rose-500/30 flex items-center justify-center text-rose-400 shadow-lg shadow-rose-500/10">
                <XCircle className="w-6 h-6 text-rose-400" />
              </div>
            )}
          </div>

          <div>
            <div className="flex items-center space-x-2">
              <h3 className="text-base sm:text-lg font-bold text-white">
                {status === 'running' && 'Analyzing Episode & Mining Viral Hooks...'}
                {status === 'done' && 'Viral Shorts Extracted Successfully!'}
                {status === 'error' && 'Analysis Pipeline Interrupted'}
              </h3>
            </div>
            <p className="text-xs text-gray-400">
              {status === 'running' && 'Processing audio harmonics, language transcription, and narrative hooks'}
              {status === 'done' && 'Scroll down to review ranked clips, preview videos, and export on-demand'}
              {status === 'error' && `Error during: ${failedStage || 'pipeline execution'}`}
            </p>
          </div>
        </div>

        {/* Progress Display */}
        <div className="flex items-center space-x-3 self-end sm:self-center">
          <div className="text-right">
            <span className="text-xl font-extrabold font-mono text-white">{progressPercent}%</span>
            <span className="text-[11px] block text-indigo-400 font-medium">
              {status === 'running' ? 'Active Pipeline' : status === 'done' ? 'Complete' : 'Failed'}
            </span>
          </div>
          <div className="w-12 h-12 relative flex items-center justify-center">
            <svg className="w-12 h-12 -rotate-90 transform" viewBox="0 0 36 36">
              <path
                className="text-white/10"
                strokeWidth="3"
                stroke="currentColor"
                fill="none"
                d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831"
              />
              <path
                className={status === 'error' ? 'text-rose-500' : 'text-indigo-500 transition-all duration-500'}
                strokeDasharray={`${progressPercent}, 100`}
                strokeLinecap="round"
                strokeWidth="3.2"
                stroke="currentColor"
                fill="none"
                d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831"
              />
            </svg>
          </div>
        </div>
      </div>

      {/* Linear progress bar */}
      <div className="w-full bg-white/[0.06] rounded-full h-1.5 overflow-hidden">
        <div
          className={`h-full transition-all duration-500 ${
            status === 'error'
              ? 'bg-rose-500'
              : 'bg-gradient-to-r from-indigo-500 via-purple-500 to-pink-500'
          }`}
          style={{ width: `${progressPercent}%` }}
        ></div>
      </div>

      {/* Multi-Stage Stepper with Checkpoints */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
        {STEPS.map((step) => {
          const isDone = status === 'done' || currentStep > step.id;
          const isActive = status === 'running' && currentStep === step.id;
          const isFailed = status === 'error' && currentStep === step.id;

          return (
            <div
              key={step.id}
              className={`p-3.5 rounded-2xl border transition-all relative overflow-hidden ${
                isDone
                  ? 'bg-emerald-500/[0.04] border-emerald-500/30'
                  : isActive
                  ? 'bg-indigo-600/[0.08] border-indigo-500 shadow-md shadow-indigo-500/10'
                  : isFailed
                  ? 'bg-rose-500/[0.06] border-rose-500/40'
                  : 'bg-white/[0.01] border-white/[0.06] opacity-60'
              }`}
            >
              <div className="flex items-center space-x-2.5">
                <div
                  className={`w-7 h-7 rounded-xl flex items-center justify-center shrink-0 text-xs font-bold ${
                    isDone
                      ? 'bg-emerald-500/20 text-emerald-400'
                      : isActive
                      ? 'bg-indigo-600 text-white animate-pulse'
                      : isFailed
                      ? 'bg-rose-500/20 text-rose-400'
                      : 'bg-white/[0.05] text-gray-500'
                  }`}
                >
                  {isDone ? <CheckCircle2 className="w-4 h-4" /> : step.icon}
                </div>

                <div className="min-w-0">
                  <div className="flex items-center space-x-1.5">
                    <span className="text-xs font-bold text-white truncate">{step.title}</span>
                  </div>
                  <p className="text-[10px] text-gray-400 truncate mt-0.5">{step.subtitle}</p>
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {/* Error Banner */}
      {status === 'error' && errorMsg && (
        <div className="p-4 rounded-2xl bg-rose-500/10 border border-rose-500/30 text-rose-300 text-xs flex items-start space-x-3">
          <XCircle className="w-5 h-5 text-rose-400 shrink-0 mt-0.5" />
          <div>
            <strong className="font-semibold block text-sm text-white">Pipeline Execution Halted:</strong>
            <span className="text-rose-200 mt-1 block">{errorMsg}</span>
          </div>
        </div>
      )}

      {/* Warnings List */}
      {warnings.length > 0 && (
        <div className="p-3.5 rounded-2xl bg-amber-500/10 border border-amber-500/30 text-amber-200 text-xs flex items-start space-x-3">
          <AlertTriangle className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" />
          <div>
            <strong className="font-semibold block text-amber-300">Pipeline Notices:</strong>
            <ul className="list-disc list-inside space-y-0.5 text-[11px] text-amber-200/90 mt-1">
              {warnings.map((w, idx) => (
                <li key={idx}>{w}</li>
              ))}
            </ul>
          </div>
        </div>
      )}

      {/* Live Log Terminal Drawer */}
      <div className="rounded-2xl bg-[#060911] border border-white/[0.08] overflow-hidden">
        <button
          type="button"
          onClick={() => setIsTerminalOpen(!isTerminalOpen)}
          className="w-full px-4 py-3 flex items-center justify-between text-xs font-semibold text-gray-300 bg-white/[0.02] hover:bg-white/[0.04] transition-colors"
        >
          <div className="flex items-center space-x-2">
            <Terminal className="w-4 h-4 text-indigo-400" />
            <span className="font-mono text-xs">Live Terminal Logs</span>
            <span className="text-[10px] px-2 py-0.5 rounded-full bg-white/[0.05] text-gray-400 font-mono">
              {logs.length} lines
            </span>
          </div>
          <div className="flex items-center space-x-2 text-[11px] text-gray-500">
            <span>{isTerminalOpen ? 'Collapse' : 'Expand'}</span>
            <ChevronDown
              className={`w-3.5 h-3.5 transition-transform duration-300 ${
                isTerminalOpen ? 'rotate-180 text-indigo-400' : ''
              }`}
            />
          </div>
        </button>

        {isTerminalOpen && (
          <div className="p-4 max-h-56 overflow-y-auto font-mono text-[11px] leading-relaxed text-gray-300 space-y-1 select-text scrollbar-thin">
            {logs.length === 0 ? (
              <div className="text-gray-600 italic">Awaiting pipeline logs...</div>
            ) : (
              logs.map((line, idx) => {
                const lower = line.toLowerCase();
                const isErr = lower.includes('error') || lower.includes('exception');
                const isWarn = lower.includes('warning') || lower.includes('warn');
                const isHighlight = lower.includes('completed') || lower.includes('clip') || lower.includes('score');

                return (
                  <div key={idx} className="flex items-start space-x-2 break-all">
                    <span className="text-gray-600 select-none text-[10px] w-6 text-right shrink-0">
                      {idx + 1}
                    </span>
                    <span
                      className={
                        isErr
                          ? 'text-rose-400 font-semibold'
                          : isWarn
                          ? 'text-amber-300'
                          : isHighlight
                          ? 'text-emerald-300'
                          : 'text-gray-300'
                      }
                    >
                      {line}
                    </span>
                  </div>
                );
              })
            )}
            <div ref={terminalBottomRef} />
          </div>
        )}
      </div>
    </div>
  );
};
