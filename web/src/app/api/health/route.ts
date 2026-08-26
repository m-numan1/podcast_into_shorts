import { NextResponse } from 'next/server';

const BACKEND_URL = process.env.BACKEND_URL || 'http://127.0.0.1:8000';

export async function GET() {
  try {
    const res = await fetch(`${BACKEND_URL}/health`, { cache: 'no-store' });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    return NextResponse.json({ ...data, online: true });
  } catch (error: any) {
    return NextResponse.json(
      { online: false, scoring_mode: 'offline', error: error?.message || 'Disconnected' },
      { status: 200 }
    );
  }
}
