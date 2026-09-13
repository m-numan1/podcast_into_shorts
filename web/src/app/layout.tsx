import "./globals.css";

export const metadata = {
  title: "ClipPulse AI | AI Podcast-to-Shorts Video Clipping Platform",
  description: "Turn 1-hour long podcasts into viral vertical 9:16 Shorts, Reels & TikToks with AI hook detection, animated subtitles, and dynamic reframing.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="h-full antialiased dark">
      <body className="min-h-full flex flex-col bg-[#090D16] text-gray-100 selection:bg-indigo-500 selection:text-white">
        {children}
      </body>
    </html>
  );
}
