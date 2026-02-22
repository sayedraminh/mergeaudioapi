import "./globals.css";

export const metadata = {
  title: "Video API Tester",
  description: "Test client for video merge, beat-sync, and trim endpoints"
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
