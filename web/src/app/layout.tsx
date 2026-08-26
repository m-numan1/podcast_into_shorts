import "./globals.css";

export const metadata = {
  title: "Podcast to Shorts AI | Short-Form Video Extractor",
  description: "Finds self-contained short clips in long-form podcasts and renders vertical 9:16 MP4 shorts with burned-in AI captions.",
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
