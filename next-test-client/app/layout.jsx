import "./globals.css";

export const metadata = {
  title: "Video API Tester",
  description: "Test client for merge, beat-sync, frame-accurate trim, reverse, speed, and frame extraction endpoints"
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
