'use client';

import React, { useState } from 'react';

interface StatusDrawerProps {
  status: 'idle' | 'running' | 'done' | 'error';
  logs: string[];
  failedStage?: string;
  errorMsg?: string;
  warnings?: string[];
  onClose?: () => void;
}

export const StatusDrawer: React.FC<StatusDrawerProps> = ({
  status,
  logs,
  failedStage,
  errorMsg,
  warnings,
}) => {
  const [isExpanded, setIsExpanded] = useState<boolean>(true);

  if (status === 'idle') return null;

  return (
    <div className="glass-panel rounded-2xl p-4 sm:p-5 border border-white/10 space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center space-x-3">
          {status === 'running' && (
            <div className="flex items-end space-x-1 h-5 px-1">
              <div className="w-1 bg-indigo-500 rounded-full wave-bar-1"></div>
              <div className="w-1 bg-cyan-400 rounded-full wave-bar-2"></div>
              <div className="w-1 bg-indigo-400 rounded-full wave-bar-3"></div>
              <div className="w-1 bg-cyan-300 rounded-full wave-bar-4"></div>
            </div>
          )}
          {status === 'done' && (
            <div className="w-6 h-6 rounded-full bg-emerald-500/20 border border-emerald-500/40 flex items-center justify-center text-emerald-400">
              <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
              </svg>
            </div>
          )}
          {status === 'error' && (
            <div className="w-6 h-6 rounded-full bg-rose-500/20 border border-rose-500/40 flex items-center justify-center text-rose-400">
              <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </div>
          )}

          <div>
            <h3 className="text-sm font-bold text-white flex items-center space-x-2">
              <span>
                {status === 'running' && 'Pipeline Processing active'}
                {status === 'done' && 'Processing Complete'}
                {status === 'error' && 'Pipeline Exception'}
              </span>
              <span className="text-xs text-gray-400 font-normal">({logs.length} logs)</span>
            </h3>
            <p className="text-xs text-gray-400">
              {status === 'running' && 'Analyzing podcast, segmenting candidates & scoring clips...'}
              {status === 'done' && 'Clips extracted successfully below.'}
              {status === 'error' && `Failed at stage: ${failedStage || 'pipeline'}`}
            </p>
          </div>
        </div>

        <button
          onClick={() => setIsExpanded(!isExpanded)}
          className="p-1.5 rounded-lg bg-slate-800/80 hover:bg-slate-700/80 text-gray-300 text-xs flex items-center space-x-1"
        >
          <span>{isExpanded ? 'Hide Logs' : 'View Logs'}</span>
          <svg className={`w-3.5 h-3.5 transition-transform ${isExpanded ? 'rotate-180' : ''}`} fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
          </svg>
        </button>
      </div>

      {/* Errors / Warnings Banners */}
      {status === 'error' && errorMsg && (
        <div className="p-3 rounded-xl bg-rose-500/10 border border-rose-500/30 text-rose-300 text-xs">
          <strong className="font-semibold block mb-0.5">Error Details:</strong>
          {errorMsg}
        </div>
      )}

      {warnings && warnings.length > 0 && (
        <div className="p-3 rounded-xl bg-amber-500/10 border border-amber-500/30 text-amber-300 text-xs">
          <strong className="font-semibold block mb-1">Pipeline Warnings:</strong>
          <ul className="list-disc list-inside space-y-0.5 text-[11px] text-amber-200">
            {warnings.map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        </div>
      )}

      {/* Logs Window */}
      {isExpanded && (
        <div className="rounded-xl bg-slate-950 border border-slate-800/90 p-3 max-h-48 overflow-y-auto font-mono text-[11px] leading-relaxed text-gray-300 space-y-1">
          {logs.length === 0 ? (
            <div className="text-gray-600 italic">Initializing log stream...</div>
          ) : (
            logs.map((log, idx) => (
              <div key={idx} className="break-words">
                <span className="text-gray-600 select-none mr-2">[{idx + 1}]</span>
                <span className={log.toLowerCase().includes('error') ? 'text-rose-400 font-semibold' : log.toLowerCase().includes('warn') ? 'text-amber-300' : ''}>
                  {log}
                </span>
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
};
