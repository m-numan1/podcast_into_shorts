import { NextRequest, NextResponse } from 'next/server';

const BACKEND_URL = process.env.BACKEND_URL || 'http://127.0.0.1:8000';

export async function GET(req: NextRequest) {
  try {
    const { searchParams } = new URL(req.url);
    const jobId = searchParams.get('job_id');
    if (!jobId) {
      return NextResponse.json({ error: 'job_id parameter is required' }, { status: 400 });
    }

    const res = await fetch(`${BACKEND_URL}/api/status?job_id=${encodeURIComponent(jobId)}`, {
      cache: 'no-store',
    });
    const data = await res.json();
    return NextResponse.json(data, { status: res.status });
  } catch (error: any) {
    return NextResponse.json(
      { error: `Backend status error: ${error?.message || 'Server offline'}` },
      { status: 503 }
    );
  }
}
